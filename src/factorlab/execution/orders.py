"""M8-03：deterministic net order planning——TargetPortfolio → OrderBatch。

单 execution event planner（一次调用 = 一个 decision_date → 一个 OrderBatch）：
    target + schedule + PRE_EXECUTION state + snapshot + quantity rules
        → planning equity @ raw open → ideal target shares（floor）
        → delta → SELL（sellable cap + quantity projection）
                → BUY（quantity projection + sell-first funding +
                     proportional funding scale）
        → net OrderBatch（每 code 至多 1 行，code ASC）

边界声明：
- **没有 ExecutionSpec 参数**：调仓时刻的现金 authority 是 PortfolioState.cash
  （M8-01B 后 ExecutionSpec 只剩 initial_cash——每次调仓重读会重置账户现金）
- 只消费参数提供的 evidence：不访问 DB / SignalArtifact / StrategySpec；
  不改 PortfolioState；不产生 Fill/Trade/cost/NAV（M8-04/05/06）
- has_daily 是 **sizing price evidence**（非 tradability）：非 all-cash 的
  planning universe 必须全部 has_daily=True（用 raw open 反推 target shares /
  计算 equity / 计划卖出回款）；all-cash target 不需要 open（target shares=0，
  只需生成 SELL intent，是否成交属 M8-04）
- has_limit / has_suspend_record / pre_close 不参与规划（M8-04 才定义
  fillability）
- buy_budget 可能计入 planned sell notional（规划层 sell-first funding）——
  **不代表 sell 已成交**；M8-04 必须按实际 sell fills 重新执行现金约束
"""

from __future__ import annotations

import datetime
import math

import polars as pl

from factorlab.domain.execution import (ExecutionSchedule, ExecutionTiming,
                                        MarketOpenSnapshot, OrderBatch,
                                        PortfolioState, PortfolioStatePhase,
                                        QuantityRuleKind)
from factorlab.domain.portfolio import TargetPortfolio
from factorlab.execution.rules import is_valid_buy_quantity, is_valid_sell_quantity

# 最终 buy notional 的 float 容差（raw open 为 Float64；不能实质性超现金）
_BUDGET_TOL = 1e-10

_EMPTY_ORDERS = pl.DataFrame(
    {"code": pl.Series([], dtype=pl.String),
     "side": pl.Series([], dtype=pl.String),
     "quantity": pl.Series([], dtype=pl.Int64)})


def _project_buy_quantity(rule: QuantityRuleKind, max_quantity: int) -> int:
    """返回 <= max_quantity 的最大合法 BUY quantity；不存在则 0。"""
    if rule is QuantityRuleKind.ROUND_LOT_100:
        return (max_quantity // 100) * 100
    if rule is QuantityRuleKind.STAR_MIN_200_STEP_1:
        return max_quantity if max_quantity >= 200 else 0
    if rule is QuantityRuleKind.BSE_MIN_100_STEP_1:
        return max_quantity if max_quantity >= 100 else 0
    raise ValueError(f"unknown QuantityRuleKind {rule!r}")


def _project_sell_quantity(
    rule: QuantityRuleKind,
    *,
    holding_quantity: int,
    max_quantity: int,
) -> int:
    """返回不超过 max_quantity 的最大合法 SELL quantity；不存在则 0。

    - ROUND_LOT_100：整手（100/200/...）或一次完整零股 remainder（R, R+100,
      R+200, ...）中取 <= max 的最大值
    - STAR（最小 200）/ BSE（最小 100）：holding < 最小单位只能全量卖出
      （L >= H → H）；否则 L >= 最小单位 → L
    - 绝不超卖 target（max_quantity 已含 desired_sell 上限）
    """
    h = holding_quantity
    if rule is QuantityRuleKind.ROUND_LOT_100:
        best = 0
        lots = (max_quantity // 100) * 100
        if lots >= 100:
            best = lots
        remainder = h % 100
        if remainder > 0 and max_quantity >= remainder:
            odd = remainder + 100 * ((max_quantity - remainder) // 100)
            best = max(best, odd)
        return best
    if rule is QuantityRuleKind.STAR_MIN_200_STEP_1:
        if h < 200:
            return h if max_quantity >= h else 0
        return max_quantity if max_quantity >= 200 else 0
    if rule is QuantityRuleKind.BSE_MIN_100_STEP_1:
        if h < 100:
            return h if max_quantity >= h else 0
        return max_quantity if max_quantity >= 100 else 0
    raise ValueError(f"unknown QuantityRuleKind {rule!r}")


def construct_order_batch(
    target: TargetPortfolio,
    schedule: ExecutionSchedule,
    state: PortfolioState,
    snapshot: MarketOpenSnapshot,
    quantity_rules,
    *,
    decision_date: datetime.date,
) -> OrderBatch:
    """规划一个 execution event 的净订单（见模块 docstring）。

    Raises:
        TypeError: 任一输入类型不匹配（不自动转换）
        ValueError: cross-object invariant / coverage / sizing evidence 违规
        NotImplementedError: NEXT_CLOSE timing（M8-03 v1 仅 NEXT_OPEN）
        RuntimeError: 内部不变量破坏（安全网，不应触发）
    """
    # ---- type guards（显式，不自动转换）----
    from factorlab.execution.rules import SecurityQuantityRules
    if not isinstance(target, TargetPortfolio):
        raise TypeError(
            f"target 必须为 TargetPortfolio（收到 {type(target).__name__}）")
    if not isinstance(schedule, ExecutionSchedule):
        raise TypeError(
            f"schedule 必须为 ExecutionSchedule（收到 {type(schedule).__name__}）")
    if not isinstance(state, PortfolioState):
        raise TypeError(
            f"state 必须为 PortfolioState（收到 {type(state).__name__}）")
    if not isinstance(snapshot, MarketOpenSnapshot):
        raise TypeError(
            f"snapshot 必须为 MarketOpenSnapshot（收到 {type(snapshot).__name__}）")
    if not isinstance(quantity_rules, SecurityQuantityRules):
        raise TypeError(
            f"quantity_rules 必须为 SecurityQuantityRules（收到 "
            f"{type(quantity_rules).__name__}）")
    if not isinstance(decision_date, datetime.date) \
            or isinstance(decision_date, datetime.datetime):
        raise ValueError(
            f"decision_date 必须为 datetime.date（datetime.datetime/str/None 均拒绝，"
            f"收到 {decision_date!r}）")

    # ---- target ↔ schedule 全局对应（数量/顺序/日期严格一致）----
    schedule_dates = tuple(schedule.frame["decision_date"].to_list())
    if schedule_dates != target.decision_dates:
        raise ValueError(
            f"schedule.decision_date 必须与 target.decision_dates 完全一致"
            f"（数量/顺序/日期）——missing/extra/不同顺序均 fail")
    authority = target.meta.source_timing.default_earliest_execution
    timings = schedule.frame["execution_timing"].unique().to_list()
    if timings != [authority.value]:
        raise ValueError(
            f"schedule.execution_timing 必须全部 == target timing authority "
            f"{authority.value}（收到 {timings}）")

    # ---- selected decision / event row / NEXT_OPEN only ----
    if decision_date not in target.decision_dates:
        raise ValueError(
            f"decision_date {decision_date} 不在 target.decision_dates 中——"
            f"selected decision 必须存在（all-cash 日以 0 rows 显式表达）")
    event_rows = schedule.frame.filter(
        pl.col("decision_date") == decision_date)
    if event_rows.height != 1:
        raise ValueError(
            f"selected decision_date {decision_date} 在 schedule 中必须恰好 "
            f"1 row（收到 {event_rows.height} 行）")
    event = event_rows.row(0)
    event_execution_date = event[1]
    event_timing = ExecutionTiming(event[2])
    if event_timing is not ExecutionTiming.NEXT_OPEN:
        raise NotImplementedError(
            f"{event_timing.value} market sizing path 尚未实现——M8-03 v1 仅支持 "
            f"NEXT_OPEN（MarketOpenSnapshot）；禁止拿 daily.open 冒充 next_close")

    # ---- execution date / phase cross-object invariants ----
    if event_execution_date != snapshot.execution_date:
        raise ValueError(
            f"schedule.execution_date {event_execution_date} != "
            f"snapshot.execution_date {snapshot.execution_date}")
    if event_execution_date != state.as_of_date:
        raise ValueError(
            f"schedule.execution_date {event_execution_date} != "
            f"state.as_of_date {state.as_of_date}")
    if state.phase is not PortfolioStatePhase.PRE_EXECUTION:
        raise ValueError(
            f"state.phase 必须为 PRE_EXECUTION（收到 {state.phase.value}——"
            f"不能从已执行后的 state 再生成同一批订单）")

    # ---- selected target slice（0 rows = 显式 all-cash，≠ 无决策）----
    selected_target = target.frame.filter(
        pl.col("decision_date") == decision_date)
    is_all_cash = selected_target.height == 0

    # ---- planning universe = current ∪ target，code ASC ----
    current_codes = state.positions["code"].to_list()
    target_codes = selected_target["code"].to_list()
    planning_codes = sorted(set(current_codes) | set(target_codes))

    # ---- snapshot / rules 精确覆盖 planning_codes（missing/extra 均 fail）----
    snap_codes = set(snapshot.frame["code"].to_list())
    rule_codes = set(quantity_rules.frame["code"].to_list())
    plan_set = set(planning_codes)
    if snap_codes != plan_set:
        missing = sorted(plan_set - snap_codes)
        extra = sorted(snap_codes - plan_set)
        raise ValueError(
            f"snapshot 必须精确覆盖 planning_codes（missing {missing}，"
            f"extra {extra}）——订单规划 evidence scope 必须明确唯一")
    if rule_codes != plan_set:
        missing = sorted(plan_set - rule_codes)
        extra = sorted(rule_codes - plan_set)
        raise ValueError(
            f"quantity_rules 必须精确覆盖 planning_codes（missing {missing}，"
            f"extra {extra}）")

    # 空 planning universe（无持仓 + 显式 all-cash）→ 空 OrderBatch
    if not planning_codes:
        return OrderBatch(decision_date=decision_date,
                          execution_date=event_execution_date,
                          execution_timing=event_timing,
                          orders=_EMPTY_ORDERS)

    # ---- evidence / rule / position maps（frame 已稳定排序 → 迭代确定性）----
    open_by_code: dict[str, float] = {}
    has_daily_by_code: dict[str, bool] = {}
    for code, open_, _pre_close, _up, _down, has_daily, _has_limit, \
            _has_suspend in snapshot.frame.iter_rows():
        open_by_code[code] = open_
        has_daily_by_code[code] = has_daily
    rule_by_code: dict[str, QuantityRuleKind] = {}
    for code, _market, rule_str in quantity_rules.frame.iter_rows():
        rule_by_code[code] = QuantityRuleKind(rule_str)
    qty_by_code: dict[str, int] = {}
    sellable_by_code: dict[str, int] = {}
    for code, quantity, sellable in state.positions.iter_rows():
        qty_by_code[code] = quantity
        sellable_by_code[code] = sellable

    # ---- sizing evidence：非 all-cash 要求全 universe has_daily=True ----
    if not is_all_cash:
        missing_evidence = [c for c in planning_codes
                            if not has_daily_by_code.get(c, False)]
        if missing_evidence:
            raise ValueError(
                f"{missing_evidence} missing sizing price evidence "
                f"(has_daily=False)——M8-03 需以 raw open 计算 planning equity / "
                f"target shares / sell funding；fillability 判定属 M8-04")

    # ---- planning equity / target value / ideal target shares ----
    # （all-cash：target shares=0，无需 equity——只生成 SELL intent）
    equity = 0.0
    if not is_all_cash:
        equity = state.cash + sum(
            qty_by_code.get(c, 0) * open_by_code[c] for c in planning_codes)
        ideal_by_code: dict[str, int] = {}
        for _date, code, weight in selected_target.iter_rows():
            target_value = weight * equity
            ideal_by_code[code] = math.floor(target_value / open_by_code[code])

    # ---- delta / SELL（sellable cap + quantity projection）----
    sell_orders: list[tuple[str, int]] = []     # (code, quantity)
    sell_notional = 0.0
    for code in planning_codes:
        current_qty = qty_by_code.get(code, 0)
        ideal = ideal_by_code.get(code, 0) if not is_all_cash else 0
        delta = ideal - current_qty
        if delta < 0:
            desired_sell = -delta
            sell_limit = min(desired_sell, sellable_by_code.get(code, 0))
            projected = _project_sell_quantity(
                rule_by_code[code], holding_quantity=current_qty,
                max_quantity=sell_limit)
            if projected > 0:
                sell_orders.append((code, projected))
                if not is_all_cash:
                    sell_notional += projected * open_by_code[code]

    # ---- BUY（provisional projection → sell-first funding → 比例缩放）----
    buy_budget = state.cash + (sell_notional if not is_all_cash else 0.0)
    provisional: list[tuple[str, int]] = []
    for code in planning_codes:
        current_qty = qty_by_code.get(code, 0)
        ideal = ideal_by_code.get(code, 0) if not is_all_cash else 0
        delta = ideal - current_qty
        if delta > 0:
            projected = _project_buy_quantity(rule_by_code[code], delta)
            if projected > 0:
                provisional.append((code, projected))
    provisional_notional = sum(
        q * open_by_code[c] for c, q in provisional) if not is_all_cash else 0.0

    final_buys: list[tuple[str, int]] = []
    if provisional:
        if provisional_notional <= buy_budget:
            final_buys = list(provisional)
        else:
            funding_scale = buy_budget / provisional_notional
            for code, q in provisional:
                scaled_cap = math.floor(q * funding_scale)
                projected = _project_buy_quantity(rule_by_code[code], scaled_cap)
                if projected > 0:
                    final_buys.append((code, projected))

    # ---- funding invariant（final spend <= buy_budget，float 容差内）----
    final_spend = sum(q * open_by_code[c] for c, q in final_buys)
    tol = _BUDGET_TOL * max(1.0, buy_budget)
    if final_spend > buy_budget + tol:
        raise RuntimeError(
            f"final planned buy notional {final_spend} 超出 buy_budget "
            f"{buy_budget}（容差 {tol}）——funding-scale invariant 破坏，"
            f"不允许 silent negative planned cash")

    # ---- build net orders（每 code 至多 1 行；quantity > 0；code ASC）----
    order_rows: list[tuple[str, str, int]] = []
    for code, q in sell_orders:
        order_rows.append((code, "sell", q))
    for code, q in final_buys:
        order_rows.append((code, "buy", q))
    orders = pl.DataFrame(order_rows, schema=["code", "side", "quantity"],
                          orient="row")
    if orders.height:
        orders = orders.with_columns(
            pl.col("code").cast(pl.String),
            pl.col("side").cast(pl.String),
            pl.col("quantity").cast(pl.Int64))
        orders = orders.sort("code")
    else:
        orders = _EMPTY_ORDERS

    # ---- authority 验证（安全网：projection 保证，重复检查防回归）----
    holding_map = qty_by_code
    sellable_map = sellable_by_code
    for row in orders.iter_rows():
        code, side, q = row
        rule = rule_by_code[code]
        if side == "buy":
            if not is_valid_buy_quantity(rule, q):
                raise RuntimeError(
                    f"BUY {code} {q} 未通过 is_valid_buy_quantity（{rule.value}）")
        else:
            holding = holding_map[code]
            if not is_valid_sell_quantity(rule, holding_quantity=holding,
                                          sell_quantity=q):
                raise RuntimeError(
                    f"SELL {code} {q}（holding {holding}）未通过 "
                    f"is_valid_sell_quantity（{rule.value}）")
            if q > sellable_map[code]:
                raise RuntimeError(
                    f"SELL {code} {q} 超出 sellable_quantity "
                    f"{sellable_map[code]}（T+1 cap）")

    return OrderBatch(decision_date=decision_date,
                      execution_date=event_execution_date,
                      execution_timing=event_timing,
                      orders=orders)
