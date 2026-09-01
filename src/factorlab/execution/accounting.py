"""M8-05B：execution accounting——PRE state + FillBatch + POST state →
ExecutionAccountingSummary。

只聚合，不重算：
- cash_before = pre.cash；net_cash_delta = Σ FillBatch.effective_cash_delta
  （与 M8-04D 同一 polars sum 表达）；cash_after = post.cash
- **cash bridge 严格**：post.cash == pre.cash + Σ delta（否则 ValueError
  "POST cash is inconsistent with PRE cash + FillBatch effective_cash_delta"）
- buy/sell gross 与 commission/stamp/transfer 直接聚合 FillBatch 列；
  total_fees = commission + stamp_tax + transfer_fee（固定 aggregation
  order，与 FillBatch 每行 total 同表达式结构——禁止按 rates 反算）
- 不 import execution.costs/spec/market/DB；不做 position transition math
  （M8-04D/E authority）；不含 market value / PnL
"""

from __future__ import annotations

import polars as pl

from factorlab.domain.accounting import ExecutionAccountingSummary
from factorlab.domain.execution import (ExecutionTiming, FillBatch,
                                        PortfolioState, PortfolioStatePhase)


def summarize_execution_accounting(
    pre_state: PortfolioState,
    fills: FillBatch,
    post_state: PortfolioState,
) -> ExecutionAccountingSummary:
    """汇总单 execution event 的 realized accounting（cash bridge 校验）。

    Raises:
        TypeError: 任一参数类型不匹配
        ValueError: phase/date/cash bridge 违规
        NotImplementedError: NEXT_CLOSE（v1 仅 NEXT_OPEN）
    """
    if not isinstance(pre_state, PortfolioState):
        raise TypeError(
            f"pre_state 必须为 PortfolioState（收到 {type(pre_state).__name__}）")
    if not isinstance(fills, FillBatch):
        raise TypeError(f"fills 必须为 FillBatch（收到 {type(fills).__name__}）")
    if not isinstance(post_state, PortfolioState):
        raise TypeError(
            f"post_state 必须为 PortfolioState（收到 {type(post_state).__name__}）")
    if pre_state.phase is not PortfolioStatePhase.PRE_EXECUTION:
        raise ValueError(
            f"pre_state.phase 必须为 PRE_EXECUTION（收到 {pre_state.phase.value}）")
    if post_state.phase is not PortfolioStatePhase.POST_EXECUTION:
        raise ValueError(
            f"post_state.phase 必须为 POST_EXECUTION"
            f"（收到 {post_state.phase.value}）")
    if (pre_state.as_of_date != fills.execution_date
            or post_state.as_of_date != fills.execution_date):
        raise ValueError(
            f"pre_state.as_of_date / post_state.as_of_date 必须与 "
            f"fills.execution_date 全部一致（{pre_state.as_of_date} / "
            f"{post_state.as_of_date} / {fills.execution_date}）")
    if fills.execution_timing is not ExecutionTiming.NEXT_OPEN:
        raise NotImplementedError(
            f"{fills.execution_timing.value} accounting 尚未实现——"
            f"M8 v1 仅 NEXT_OPEN")

    f = fills.frame
    net_cash_delta = f["effective_cash_delta"].sum() if f.height else 0.0
    # cash bridge（与 M8-04D 同一 Float64 reduction path——不允许
    # Decimal/round/clamp）
    if post_state.cash != pre_state.cash + net_cash_delta:
        raise ValueError(
            f"POST cash is inconsistent with PRE cash + FillBatch "
            f"effective_cash_delta：{post_state.cash} != "
            f"{pre_state.cash} + {net_cash_delta}")

    buys = f.filter(pl.col("side") == "buy")
    sells = f.filter(pl.col("side") == "sell")
    buy_gross = buys["gross_notional"].sum() if buys.height else 0.0
    sell_gross = sells["gross_notional"].sum() if sells.height else 0.0
    commission = f["commission"].sum() if f.height else 0.0
    stamp = f["stamp_tax"].sum() if f.height else 0.0
    transfer = f["transfer_fee"].sum() if f.height else 0.0

    return ExecutionAccountingSummary(
        execution_date=fills.execution_date,
        cash_before=pre_state.cash,
        buy_gross_notional=buy_gross,
        sell_gross_notional=sell_gross,
        commission=commission,
        stamp_tax=stamp,
        transfer_fee=transfer,
        total_fees=commission + stamp + transfer,
        net_cash_delta=net_cash_delta,
        cash_after=post_state.cash,
    )
