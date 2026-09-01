"""M8-04D：same-day POST_EXECUTION PortfolioState transition——apply_fill_batch。

```
PRE_EXECUTION PortfolioState + FillBatch
        ↓
POST_EXECUTION PortfolioState（新 immutable state）
```

只消费 state + fills：
- cash 唯一来源 state.cash；cash 变化唯一来源 fills.frame.effective_cash_delta
  （不重算 execution_price×qty / gross-fees / compute_execution_cost）
- 持仓唯一来源 state.positions；成交数量唯一来源 filled_quantity
  （不重判 fillability/成本/funding/market prices——都已在 FillBatch 产生前关闭）
- T+1 核心：当天 BUY → quantity += fill、sellable_quantity **不变**；
  SELL → quantity -= fill、sellable_quantity -= fill（卖掉的是可卖库存）
- sparse holdings：quantity==0 → 该 code 行删除；全卖光 → typed empty
- FillBatch 是唯一 actual-fill authority：不做 side netting / 不重新聚合
- 不修改输入；输出经真正 PortfolioState constructor 验证

只依赖 stdlib + polars + factorlab.domain.execution（无 cost/market/rules/
DB/strategy 依赖）。
"""

from __future__ import annotations

import math

import polars as pl

from factorlab.domain.execution import (ExecutionTiming, FillBatch,
                                        PortfolioState, PortfolioStatePhase)

_INT64_MAX = 2**63 - 1


def apply_fill_batch(
    state: PortfolioState,
    fills: FillBatch,
) -> PortfolioState:
    """把 FillBatch 应用到 PRE_EXECUTION state → 新 POST_EXECUTION state。

    Raises:
        TypeError: state/fills 类型不匹配
        ValueError: phase/date/现金不一致/SELL inventory/Int64 overflow
        NotImplementedError: NEXT_CLOSE（v1 仅 NEXT_OPEN）
    """
    if not isinstance(state, PortfolioState):
        raise TypeError(
            f"state 必须为 PortfolioState（收到 {type(state).__name__}）")
    if not isinstance(fills, FillBatch):
        raise TypeError(f"fills 必须为 FillBatch（收到 {type(fills).__name__}）")
    if state.phase is not PortfolioStatePhase.PRE_EXECUTION:
        raise ValueError(
            f"state.phase 必须为 PRE_EXECUTION（收到 {state.phase.value}——"
            f"防止同一 FillBatch 重复应用）")
    if state.as_of_date != fills.execution_date:
        raise ValueError(
            f"state.as_of_date {state.as_of_date} != fills.execution_date "
            f"{fills.execution_date}")
    if fills.execution_timing is not ExecutionTiming.NEXT_OPEN:
        raise NotImplementedError(
            f"{fills.execution_timing.value} state transition 尚未实现——"
            f"M8-04D v1 仅支持 NEXT_OPEN（不借纯 state math 宣称 NEXT_CLOSE）")

    # ---- cash transition（与 M8-04C 同一 Float64 表达）----
    post_cash = state.cash + fills.frame["effective_cash_delta"].sum()
    if not math.isfinite(post_cash) or post_cash < 0:
        raise ValueError(
            f"FillBatch is not cash-consistent with provided PRE_EXECUTION "
            f"state：post_cash = {post_cash}（必须 finite >= 0；无 tolerance/"
            f"clamp）")

    # ---- positions transition（增量式——从 PRE positions 出发）----
    pos: dict[str, list[int]] = {}
    for code, qty, sellable in state.positions.iter_rows():
        pos[code] = [qty, sellable]
    for code, side, filled in fills.frame.select(
            ["code", "side", "filled_quantity"]).iter_rows():
        if side == "buy":
            old = pos.get(code, [0, 0])
            new_q = old[0] + filled
            if new_q > _INT64_MAX:
                raise ValueError(
                    f"BUY {code} Int64 overflow：{old[0]} + {filled} > "
                    f"2**63-1——fail fast")
            pos[code] = [new_q, old[1]]      # T+1：sellable 不变
        else:
            if code not in pos:
                raise ValueError(
                    f"SELL {code} 在 PRE state 无 position——禁止 implicit "
                    f"short / negative position")
            qty, sellable = pos[code]
            if filled > qty:
                raise ValueError(f"SELL {code} {filled} 超出 quantity {qty}")
            if filled > sellable:
                raise ValueError(
                    f"SELL {code} {filled} 超出 sellable_quantity {sellable}")
            new_q, new_s = qty - filled, sellable - filled
            if new_q == 0:
                del pos[code]                # sparse：full liquidation 删除行
            else:
                pos[code] = [new_q, new_s]

    rows = [(c, q, s) for c, (q, s) in sorted(pos.items())]
    frame = pl.DataFrame(rows, schema=["code", "quantity", "sellable_quantity"],
                         orient="row")
    if frame.height:
        frame = frame.with_columns(pl.col("code").cast(pl.String),
                                   pl.col("quantity").cast(pl.Int64),
                                   pl.col("sellable_quantity").cast(pl.Int64))
    else:
        frame = pl.DataFrame(
            {"code": pl.Series([], dtype=pl.String),
             "quantity": pl.Series([], dtype=pl.Int64),
             "sellable_quantity": pl.Series([], dtype=pl.Int64)})

    return PortfolioState(as_of_date=state.as_of_date,
                          phase=PortfolioStatePhase.POST_EXECUTION,
                          cash=post_cash,
                          positions=frame)
