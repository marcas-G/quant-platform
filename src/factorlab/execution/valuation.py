"""M8-05B：point-in-time portfolio valuation——PortfolioState + explicit marks
→ PortfolioValuation。

- marks 是 caller 提供的显式 per-share mark authority（假设与
  PortfolioState.quantity 同一 share-unit basis）；kernel 不做 price
  sourcing / stale-price / suspension valuation policy / corporate-action
  修正（禁止 qfq/hfq/adj_factor 推断）
- **exact coverage**：set(marks.code) == set(state.positions.code)
  （missing mark / extra mark → ValueError——one position ↔ one explicit
  mark 的可审计边界）
- 资产所有权基于 quantity（sellable_quantity 不参与估值）
- position MV = quantity × mark；market_value = Σ MV；NAV = cash +
  market_value（货币金额，不是 normalized index）；全部 exact，
  overflow/non-finite → ValueError
- 不读 DB / 不 import market loaders
"""

from __future__ import annotations

import math

import polars as pl

from factorlab.domain.accounting import (PortfolioMarkSnapshot,
                                         PortfolioValuation)
from factorlab.domain.execution import PortfolioState


def value_portfolio(
    state: PortfolioState,
    marks: PortfolioMarkSnapshot,
) -> PortfolioValuation:
    """以显式 marks 对 PortfolioState 做 point-in-time valuation。

    Raises:
        TypeError: state/marks 类型不匹配
        ValueError: date 不对齐 / mark coverage 不精确 / overflow
    """
    if not isinstance(state, PortfolioState):
        raise TypeError(
            f"state 必须为 PortfolioState（收到 {type(state).__name__}）")
    if not isinstance(marks, PortfolioMarkSnapshot):
        raise TypeError(
            f"marks 必须为 PortfolioMarkSnapshot（收到 {type(marks).__name__}）")
    if state.as_of_date != marks.as_of_date:
        raise ValueError(
            f"state.as_of_date {state.as_of_date} != marks.as_of_date "
            f"{marks.as_of_date}")

    pos_codes = set(state.positions["code"].to_list())
    mark_map: dict[str, float] = {}
    for code, price in marks.frame.iter_rows():
        mark_map[code] = price
    if set(mark_map) != pos_codes:
        missing = sorted(pos_codes - set(mark_map))
        extra = sorted(set(mark_map) - pos_codes)
        raise ValueError(
            f"marks 必须精确覆盖 positions（missing {missing}，extra {extra}"
            f"）——one position ↔ one explicit mark，kernel 不默默忽略")

    rows = []
    for code, quantity, _sellable in state.positions.iter_rows():
        mv = quantity * mark_map[code]
        if not math.isfinite(mv) or mv <= 0:
            raise ValueError(
                f"{code} market_value {mv} 非法（quantity × mark 溢出/非正）")
        rows.append((code, quantity, mark_map[code], mv))
    frame = pl.DataFrame(rows, schema=["code", "quantity", "mark_price",
                                       "market_value"], orient="row")
    if frame.height:
        frame = frame.with_columns(pl.col("code").cast(pl.String),
                                   pl.col("quantity").cast(pl.Int64),
                                   pl.col("mark_price").cast(pl.Float64),
                                   pl.col("market_value").cast(pl.Float64))
        frame = frame.sort("code")
    else:
        frame = pl.DataFrame(
            {"code": pl.Series([], dtype=pl.String),
             "quantity": pl.Series([], dtype=pl.Int64),
             "mark_price": pl.Series([], dtype=pl.Float64),
             "market_value": pl.Series([], dtype=pl.Float64)})
    market_value = frame["market_value"].sum() if frame.height else 0.0
    nav = state.cash + market_value

    return PortfolioValuation(as_of_date=state.as_of_date,
                              phase=state.phase,
                              cash=state.cash,
                              market_value=market_value,
                              nav=nav,
                              frame=frame)
