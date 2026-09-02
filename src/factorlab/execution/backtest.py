"""M8-06B：backtest runtime——编排已关闭 execution primitives → BacktestResult。

run_backtest 只做 orchestration（M8-06A §3 契约）：
    每 decision：schedule → snapshot → orders → assessment → fills → POST
    → accounting → NAV entry（open-based marks）→ advance → 下一 PRE
    （execution 间隔 > 1 个交易日时纯 re-date——无 fills/CA 期间状态只变日期）

约束：
- 不接收 StrategySpec/SignalArtifact；不引入 strategy logic
- execution_spec 必须显式传入（cost model 显式选择）
- MarksPolicy v1 = OPEN_BASED：POST holdings 以 execution date 的 raw
  open 标记；任一持仓缺 open evidence → ExecutionDataQualityError
  （无 stale/suspension valuation policy——M8-06A 开放问题 1）
- 全链 fail fast（ExecutionDataQualityError/ValueError 直接传播）
- zero-cost zero-slippage 每 event 断言 value-neutrality（POST NAV ==
  PRE NAV @ 同 basis open marks）；slippage-free 时 NAV drag == total_fees
- memory-only runtime object（无 persistence/DB 写入）

依赖边界：只 import 既有 primitive modules + domain——无 strategy/engine/
duckdb 直连。
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import polars as pl

from factorlab.domain.accounting import PortfolioMarkSnapshot
from factorlab.domain.backtest import (BacktestResult, ExecutionArtifact,
                                       NavSeries)
from factorlab.domain.execution import (ExecutionDataQualityError,
                                        OpenOrderDisposition, PortfolioState,
                                        PortfolioStatePhase)
from factorlab.domain.portfolio import TargetPortfolio
from factorlab.execution.accounting import summarize_execution_accounting
from factorlab.execution.calendar import resolve_execution_schedule
from factorlab.execution.fillability import assess_open_fillability
from factorlab.execution.fills import realize_open_fills
from factorlab.execution.market import load_market_open_snapshot
from factorlab.execution.orders import construct_order_batch
from factorlab.execution.overnight import advance_to_next_trading_day
from factorlab.execution.rules import resolve_security_quantity_rules
from factorlab.execution.spec import ExecutionSpec
from factorlab.execution.state import apply_fill_batch
from factorlab.execution.valuation import value_portfolio

_EMPTY_POS = pl.DataFrame(
    {"code": pl.Series([], dtype=pl.String),
     "quantity": pl.Series([], dtype=pl.Int64),
     "sellable_quantity": pl.Series([], dtype=pl.Int64)})


class MarksPolicy(Enum):
    """NAV marks 来源策略（v1 只实现 OPEN_BASED）。"""

    OPEN_BASED = "open_based"


def _marks_from_snapshot(snapshot, codes: list[str], date) -> PortfolioMarkSnapshot:
    """integration 层：snapshot.open → PortfolioMarkSnapshot（valuation.py
    不 import snapshot）。任一 code 缺 open evidence → DataQualityError。"""
    rows = []
    for code in sorted(codes):
        r = snapshot.frame.filter(pl.col("code") == code)
        if r.height != 1:
            raise ValueError(f"snapshot 缺 {code}")
        open_ = r["open"][0]
        if open_ is None:
            raise ExecutionDataQualityError(
                f"open-based marks：{code} 在 {date} 缺 open evidence "
                f"(has_daily=False)——无 stale/suspension mark policy，fail run")
        rows.append((code, open_))
    frame = pl.DataFrame(rows, schema=["code", "mark_price"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("mark_price").cast(pl.Float64))
    return PortfolioMarkSnapshot(as_of_date=date, frame=frame)


def run_backtest(
    target: TargetPortfolio,
    execution_spec: ExecutionSpec,
    db_path: Path,
    *,
    marks: MarksPolicy = MarksPolicy.OPEN_BASED,
    decision_range: tuple | None = None,
) -> BacktestResult:
    """按 target.decision_dates 顺序编排完整 execution pipeline。

    Raises:
        TypeError / ValueError / NotImplementedError / ExecutionDataQualityError
          ——全部直接传播（fail fast，不 per-day skip）
    """
    if not isinstance(target, TargetPortfolio):
        raise TypeError(
            f"target 必须为 TargetPortfolio（收到 {type(target).__name__}）")
    if not isinstance(execution_spec, ExecutionSpec):
        raise TypeError(
            f"execution_spec 必须显式传入 ExecutionSpec（收到 "
            f"{type(execution_spec).__name__}——cost model 显式选择 Gate）")
    if not isinstance(db_path, Path):
        raise TypeError(
            f"db_path 必须为 pathlib.Path（收到 {type(db_path).__name__}）")
    if marks is not MarksPolicy.OPEN_BASED:
        raise NotImplementedError(
            f"MarksPolicy v1 仅支持 OPEN_BASED（收到 {marks!r}——"
            f"caller-explicit/stale policy 未实现）")

    # ---- 决策序列 ----
    all_dates = list(target.decision_dates)
    if decision_range is not None:
        lo, hi = decision_range
        all_dates = [d for d in all_dates if lo <= d <= hi]
    if not all_dates:
        raise ValueError("decision_range 内无任何 decision——empty run 拒绝")

    # ---- schedule（全 target——construct_order_batch 要求全局一致）----
    schedule = resolve_execution_schedule(target, db_path)

    def _exec_date(d):
        r = schedule.frame.filter(pl.col("decision_date") == d)
        return r["execution_date"][0]

    # ---- 初始 PRE state @ 第一 execution date ----
    state = PortfolioState(as_of_date=_exec_date(all_dates[0]),
                           phase=PortfolioStatePhase.PRE_EXECUTION,
                           cash=execution_spec.initial_cash,
                           positions=_EMPTY_POS)

    artifacts = []
    nav_rows = []
    for i, decision_d in enumerate(all_dates):
        exec_date = _exec_date(decision_d)
        if state.as_of_date != exec_date:
            if state.as_of_date > exec_date:
                raise ValueError(
                    f"state date {state.as_of_date} 超过 event date {exec_date}")
            # 纯 re-date：间隔日无 fills/CA——cash/quantity/sellable 不变
            state = PortfolioState(as_of_date=exec_date,
                                   phase=PortfolioStatePhase.PRE_EXECUTION,
                                   cash=state.cash, positions=state.positions)

        # ---- 市场证据（planning codes = current ∪ target(d)）----
        t_rows = target.frame.filter(pl.col("decision_date") == decision_d)
        codes = sorted(set(state.positions["code"].to_list())
                       | set(t_rows["code"].to_list()))
        snapshot = load_market_open_snapshot(db_path, execution_date=exec_date,
                                             codes=codes)
        rules = resolve_security_quantity_rules(db_path, codes)

        # ---- 已关闭 pipeline ----
        orders = construct_order_batch(target, schedule, state, snapshot,
                                       rules, decision_date=decision_d)
        assessment = assess_open_fillability(orders, snapshot)
        fills = realize_open_fills(orders, assessment, state, snapshot, rules,
                                   execution_spec.cost_model)
        post = apply_fill_batch(state, fills)
        accounting = summarize_execution_accounting(state, fills, post)

        # ---- open-based marks + valuation + sanity ----
        pre_codes = state.positions["code"].to_list()
        post_codes = post.positions["code"].to_list()
        pre_marks = _marks_from_snapshot(snapshot, pre_codes, exec_date)
        post_marks = _marks_from_snapshot(snapshot, post_codes, exec_date)
        pre_nav = value_portfolio(state, pre_marks)
        post_nav = value_portfolio(post, post_marks)
        total_fees = fills.frame["total_fees"].sum() if fills.frame.height \
            else 0.0
        slippage_free = fills.frame.height == 0 or bool(
            (fills.frame["execution_price"]
             == fills.frame["reference_price"]).all())
        if slippage_free:
            if post_nav.nav != pre_nav.nav - total_fees:
                raise RuntimeError(
                    f"{exec_date} value-neutrality sanity 失败：POST NAV "
                    f"{post_nav.nav} != PRE NAV {pre_nav.nav} - fees "
                    f"{total_fees}")

        # ---- disposition 计数（只读诊断）----
        counts = [0, 0, 0, 0]
        if assessment.frame.height:
            for disp in assessment.frame["disposition"].to_list():
                counts[list(OpenOrderDisposition).index(OpenOrderDisposition(disp))] += 1

        artifact = ExecutionArtifact(
            decision_date=decision_d, execution_date=exec_date,
            pre_state=state, orders=orders, assessment=assessment,
            fills=fills, post_state=post, accounting=accounting,
            nav=post_nav, disposition_counts=tuple(counts))
        artifacts.append(artifact)
        nav_rows.append((exec_date, post.cash, post_nav.market_value,
                         post_nav.nav))

        # ---- overnight → 下一 PRE（最后 event 也 advance——final_state）----
        state = advance_to_next_trading_day(post, fills, db_path)

    nav_frame = pl.DataFrame(nav_rows, schema=["execution_date", "cash",
                                               "market_value", "nav"],
                             orient="row")
    nav_frame = nav_frame.with_columns(
        pl.col("execution_date").cast(pl.Date),
        pl.col("cash").cast(pl.Float64),
        pl.col("market_value").cast(pl.Float64),
        pl.col("nav").cast(pl.Float64))
    return BacktestResult(artifacts=tuple(artifacts),
                          nav_series=NavSeries(frame=nav_frame),
                          final_state=state)
