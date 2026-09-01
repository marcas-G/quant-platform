"""M8-04C：cost-aware realized funding + FillBatch——OrderBatch/assessment/state
→ actual modeled fills。

```
1. cross-object validation（metadata / identity / state / snapshot / rules）
2. quantity-rule / inventory revalidation（所有订单含 blocked——市场 blocked
   不掩盖 state/order corruption）
3. realize FILLABLE SELLs（full fill——无 market partial）
4. actual net sell proceeds（ExecutionCostBreakdown.effective_cash_delta）
5. available buy cash = state.cash + Σ actual net SELL proceeds
6. FILLABLE BUY candidates
7. iterative cost-aware buy funding（global proportional scale → quantity
   projection → re-cost → repeat 直到 cash-feasible；无 greedy redistribution）
8. build FillBatch（sparse：filled>0 才有一行）
9. final cash safety check（cash_after >= 0 严格，无 tolerance/clamp）
```

关键边界：
- market eligibility authority = OpenFillAssessment（只读 disposition，不重判
  suspension/limit queue）；snapshot 仅用于 reference-price consistency +
  slippage legal-bound（down <= execution_price <= up，越界 ValueError 不
  clipping——bounded slippage model 未实现）
- 成本唯一 authority = compute_execution_cost（不手写第二份费用公式）；
  BUY partial 费用基于 filled_quantity 重算
- SELL proceeds 先于 BUY funding 入账（deterministic accounting convention，
  不是交易所微观顺序声明）；blocked SELL 提供 0 现金
- 不修改任何输入；不创建 POST state；无 NAV/PnL；NEXT_OPEN only
"""

from __future__ import annotations

import math

import polars as pl

from factorlab.domain.execution import (ExecutionDataQualityError,
                                        ExecutionTiming, FillBatch,
                                        MarketOpenSnapshot, OpenFillAssessment,
                                        OpenOrderDisposition, OrderBatch,
                                        OrderSide, PortfolioState,
                                        PortfolioStatePhase, QuantityRuleKind)
from factorlab.execution.rules import SecurityQuantityRules
from factorlab.execution.costs import compute_execution_cost
from factorlab.execution.rules import (is_valid_buy_quantity,
                                       is_valid_sell_quantity,
                                       project_buy_quantity)
from factorlab.execution.spec import ExecutionCostSpec

_EMPTY_FILLS = pl.DataFrame(
    {"code": pl.Series([], dtype=pl.String),
     "side": pl.Series([], dtype=pl.String),
     "order_quantity": pl.Series([], dtype=pl.Int64),
     "filled_quantity": pl.Series([], dtype=pl.Int64),
     "reference_price": pl.Series([], dtype=pl.Float64),
     "execution_price": pl.Series([], dtype=pl.Float64),
     "gross_notional": pl.Series([], dtype=pl.Float64),
     "commission": pl.Series([], dtype=pl.Float64),
     "stamp_tax": pl.Series([], dtype=pl.Float64),
     "transfer_fee": pl.Series([], dtype=pl.Float64),
     "total_fees": pl.Series([], dtype=pl.Float64),
     "effective_cash_delta": pl.Series([], dtype=pl.Float64)})


def _check_price_bounds(breakdown, code: str, up_limit: float,
                        down_limit: float) -> None:
    """slippage 产生的 execution_price 必须落在合法 market limits 内。

    越界 → 普通 ValueError（raw market 数据合法，问题在 cost/slippage model
    配置——不是 ExecutionDataQualityError）；禁止 clipping（bounded slippage
    model 未实现）。
    """
    p = breakdown.execution_price
    if p > up_limit or p < down_limit:
        raise ValueError(
            f"{code} cost-model slippage crosses legal market limit："
            f"execution_price={p} 不在 [down={down_limit}, up={up_limit}]——"
            f"bounded slippage model is not implemented（不 clipping）")


def realize_open_fills(
    orders: OrderBatch,
    assessment: OpenFillAssessment,
    state: PortfolioState,
    snapshot: MarketOpenSnapshot,
    quantity_rules: SecurityQuantityRules,
    cost_spec: ExecutionCostSpec,
) -> FillBatch:
    """realize NEXT_OPEN actual modeled fills（见模块 docstring）。

    Raises:
        TypeError: 任一参数类型不匹配
        ValueError: cross-object / inventory / quantity-rule / slippage-bound 违规
        NotImplementedError: NEXT_CLOSE（v1 仅 NEXT_OPEN）
        RuntimeError: 迭代 progress 破坏 / 最终现金为负（安全网）
    """
    if not isinstance(orders, OrderBatch):
        raise TypeError(f"orders 必须为 OrderBatch（收到 {type(orders).__name__}）")
    if not isinstance(assessment, OpenFillAssessment):
        raise TypeError(
            f"assessment 必须为 OpenFillAssessment（收到 {type(assessment).__name__}）")
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
    if not isinstance(cost_spec, ExecutionCostSpec):
        raise TypeError(
            f"cost_spec 必须为 ExecutionCostSpec（收到 {type(cost_spec).__name__}）")

    if orders.execution_timing is not ExecutionTiming.NEXT_OPEN:
        raise NotImplementedError(
            f"{orders.execution_timing.value} realized funding 尚未实现——"
            f"M8-04C v1 仅支持 NEXT_OPEN")

    # ---- 1. cross-object validation ----
    if (orders.decision_date != assessment.decision_date
            or orders.execution_date != assessment.execution_date
            or orders.execution_timing is not assessment.execution_timing):
        raise ValueError(
            f"OrderBatch 与 OpenFillAssessment metadata 必须一致（decision/"
            f"execution/timing）")
    if not assessment.frame.select(["code", "side", "quantity"]).equals(
            orders.orders):
        raise ValueError(
            f"assessment.frame(code,side,quantity) 必须与 orders.orders 逐行"
            f"完全一致（多/少/错行均 fail——不 sort/join 后比较）")
    if state.as_of_date != orders.execution_date:
        raise ValueError(
            f"state.as_of_date {state.as_of_date} != orders.execution_date "
            f"{orders.execution_date}")
    if state.phase is not PortfolioStatePhase.PRE_EXECUTION:
        raise ValueError(
            f"state.phase 必须为 PRE_EXECUTION（收到 {state.phase.value}）")
    if snapshot.execution_date != orders.execution_date:
        raise ValueError(
            f"snapshot.execution_date {snapshot.execution_date} != "
            f"orders.execution_date {orders.execution_date}")

    order_codes = set(orders.orders["code"].to_list())
    snap_codes = set(snapshot.frame["code"].to_list())
    rule_codes = set(quantity_rules.frame["code"].to_list())
    if not order_codes <= snap_codes:
        raise ValueError(
            f"order codes 不在 snapshot 中：{sorted(order_codes - snap_codes)}"
            f"（cross-object coverage bug）")
    if not order_codes <= rule_codes:
        raise ValueError(
            f"order codes 不在 quantity_rules 中："
            f"{sorted(order_codes - rule_codes)}")

    # maps
    snap_map: dict[str, tuple[float, float, float]] = {}
    for code, open_, _pc, up, dn, *_rest in snapshot.frame.iter_rows():
        snap_map[code] = (open_, up, dn)
    rule_map: dict[str, QuantityRuleKind] = {}
    for code, _mkt, rule_str in quantity_rules.frame.iter_rows():
        rule_map[code] = QuantityRuleKind(rule_str)
    pos_map: dict[str, tuple[int, int]] = {}
    for code, qty, sellable in state.positions.iter_rows():
        pos_map[code] = (qty, sellable)

    # ---- 2. quantity-rule / inventory revalidation（含 blocked）----
    # 逐行以 orders 顺序验证，然后按 code 索引 assessment disposition
    ass_map = {}
    for code, side, qty, disp, price in assessment.frame.iter_rows():
        ass_map[code] = (side, qty, disp, price)
    for code, side, qty in orders.orders.iter_rows():
        a_side, a_qty, disp, _p = ass_map[code]
        if a_side != side or a_qty != qty:
            raise ValueError(f"assessment row mismatch for {code}")
        rule = rule_map[code]
        if side == "buy":
            if not is_valid_buy_quantity(rule, qty):
                raise ValueError(
                    f"BUY {code} {qty} 未通过 is_valid_buy_quantity"
                    f"（{rule}）——order quantity 必须重新验证")
        else:
            if code not in pos_map:
                raise ValueError(
                    f"SELL {code} 在 PRE state 无 position——inventory check "
                    f"fail（blocked 订单也必须通过）")
            hold, sellable = pos_map[code]
            if qty > sellable:
                raise ValueError(
                    f"SELL {code} {qty} 超出 sellable_quantity {sellable}")
            if qty > hold:
                raise ValueError(f"SELL {code} {qty} 超出 holding {hold}")
            if not is_valid_sell_quantity(rule, holding_quantity=hold,
                                          sell_quantity=qty):
                raise ValueError(
                    f"SELL {code} {qty}（holding {hold}）未通过 "
                    f"is_valid_sell_quantity（{rule}）")

    # ---- 3/4. realize FILLABLE SELLs + actual net proceeds ----
    rows: list[tuple] = []
    sell_net = 0.0
    for code, side, qty in orders.orders.iter_rows():
        a_side, a_qty, disp, fillable_price = ass_map[code]
        if side != "sell" or disp != OpenOrderDisposition.FILLABLE.value:
            continue
        open_, up, dn = snap_map[code]
        if fillable_price != open_:
            raise ValueError(
                f"{code} assessment.fillable_price {fillable_price} != "
                f"snapshot.open {open_}（reference-price consistency）")
        breakdown = compute_execution_cost(
            side=OrderSide.SELL, reference_price=fillable_price,
            quantity=qty, spec=cost_spec)
        _check_price_bounds(breakdown, code, up, dn)
        rows.append((code, "sell", qty, qty, fillable_price,
                     breakdown.execution_price, breakdown.gross_notional,
                     breakdown.commission, breakdown.stamp_tax,
                     breakdown.transfer_fee, breakdown.total_fees,
                     breakdown.effective_cash_delta))
        sell_net += breakdown.effective_cash_delta

    # ---- 5/6/7. FILLABLE BUY funding（迭代比例缩量）----
    available = state.cash + sell_net
    buy_candidates: list[tuple[str, int, float, str, float, float]] = []
    for code, side, qty in orders.orders.iter_rows():
        a_side, a_qty, disp, fillable_price = ass_map[code]
        if side != "buy" or disp != OpenOrderDisposition.FILLABLE.value:
            continue
        open_, up, dn = snap_map[code]
        if fillable_price != open_:
            raise ValueError(
                f"{code} assessment.fillable_price {fillable_price} != "
                f"snapshot.open {open_}")
        # slippage 与 price bounds 与 qty 无关——先验证一次
        probe = compute_execution_cost(side=OrderSide.BUY,
                                       reference_price=fillable_price,
                                       quantity=1, spec=cost_spec)
        _check_price_bounds(probe, code, up, dn)
        buy_candidates.append((code, qty, fillable_price, rule_map[code],
                               up, dn))

    def _required(q: int, price: float,
                  rule: QuantityRuleKind) -> float:
        b = compute_execution_cost(side=OrderSide.BUY, reference_price=price,
                                   quantity=q, spec=cost_spec)
        return -b.effective_cash_delta

    current: list[tuple[str, int, float, QuantityRuleKind, float, float]] = \
        list(buy_candidates)
    while True:
        total = sum(_required(q, price, rule)
                    for _c, q, price, rule, _u, _d in current)
        if total <= available:
            break
        scale = available / total
        nxt: list[tuple[str, int, float, object, float, float]] = []
        for code, q, price, rule, up, dn in current:
            cap = math.floor(q * scale)
            nq = project_buy_quantity(rule, cap)
            if nq > 0:
                nxt.append((code, nq, price, rule, up, dn))
        if [c for c, *_ in nxt] == [c for c, *_ in current] \
                and [q for _, q, *_ in nxt] == [q for _, q, *_ in current]:
            raise RuntimeError(
                f"BUY funding 迭代无 progress（scale={scale}）——数量未下降，"
                f"禁止无限循环")
        current = nxt
        if not current:
            break

    for code, q, price, _rule, _up, _dn in current:
        breakdown = compute_execution_cost(side=OrderSide.BUY,
                                           reference_price=price,
                                           quantity=q, spec=cost_spec)
        rows.append((code, "buy", q, q, price, breakdown.execution_price,
                     breakdown.gross_notional, breakdown.commission,
                     breakdown.stamp_tax, breakdown.transfer_fee,
                     breakdown.total_fees, breakdown.effective_cash_delta))

    # ---- 8. build FillBatch（code ASC）----
    if rows:
        frame = pl.DataFrame(rows, schema=["code", "side", "order_quantity",
                                           "filled_quantity", "reference_price",
                                           "execution_price", "gross_notional",
                                           "commission", "stamp_tax",
                                           "transfer_fee", "total_fees",
                                           "effective_cash_delta"], orient="row")
        frame = frame.with_columns(
            pl.col("code").cast(pl.String), pl.col("side").cast(pl.String),
            pl.col("order_quantity").cast(pl.Int64),
            pl.col("filled_quantity").cast(pl.Int64),
            pl.col("reference_price").cast(pl.Float64),
            pl.col("execution_price").cast(pl.Float64),
            pl.col("gross_notional").cast(pl.Float64),
            pl.col("commission").cast(pl.Float64),
            pl.col("stamp_tax").cast(pl.Float64),
            pl.col("transfer_fee").cast(pl.Float64),
            pl.col("total_fees").cast(pl.Float64),
            pl.col("effective_cash_delta").cast(pl.Float64))
        frame = frame.sort("code")
    else:
        frame = _EMPTY_FILLS

    # ---- 9. final cash safety（严格 >= 0，无 tolerance/clamp）----
    cash_after = state.cash + frame["effective_cash_delta"].sum()
    if not math.isfinite(cash_after) or cash_after < 0:
        raise RuntimeError(
            f"cash_after {cash_after} 非法（必须 finite >= 0）——funding "
            f"不变量破坏，不允许负现金 tolerance/clamp")

    return FillBatch(decision_date=orders.decision_date,
                     execution_date=orders.execution_date,
                     execution_timing=orders.execution_timing,
                     frame=frame)
