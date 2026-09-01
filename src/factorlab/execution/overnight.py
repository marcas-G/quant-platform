"""M8-04E：overnight T+1 inventory release——POST_EXECUTION(D) →
PRE_EXECUTION(next trade_cal open day)。

```
POST_EXECUTION PortfolioState @ D
        + same-day FillBatch @ D
        + trade_cal
        ↓
PRE_EXECUTION PortfolioState @ next_open_day
```

核心：
- release 数量 = 当天 FillBatch 中 side==BUY 的 **filled_quantity**
  （provenance-aware——**严禁 sellable=quantity 全量释放**：PortfolioState
  不记录每只不可卖股份的原因，只有 FillBatch 携带 same-day T+1 acquisition
  provenance；blocked/funding-zero BUY 不在 FillBatch → 不释放）
- cash 隔夜不变；quantity 不变；无新 code 创建/删除
- 每个 BUY fill 要求：对应 code 存在于 POST state（实际 BUY fill 后却无
  position = state/fill pair 不一致），且 unsellable capacity
  （post_quantity - post_sellable）>= filled_quantity（否则无法解释
  provenance——不允许误释放其它 unavailable inventory）
- calendar authority 唯一 = factorlab.data.calendar.trading_calendar
  （禁止自写 trade_cal SQL / weekday arithmetic / timedelta(days=1)）；
  当前 date 必须 is_open=1；下一开放日 = 严格 > 当前的第一开放日
  （无则 ValueError）；**calendar transition success ≠ market-data
  availability**——不读取 daily/stk_limit/suspend_d，不刷新数据
- 只依赖 stdlib + polars + domain + trading_calendar（read-only）
"""

from __future__ import annotations

import bisect
from pathlib import Path

import polars as pl

from factorlab.data.calendar import trading_calendar
from factorlab.domain.execution import (ExecutionTiming, FillBatch,
                                        PortfolioState, PortfolioStatePhase)


def advance_to_next_trading_day(
    state: PortfolioState,
    fills: FillBatch,
    db_path: Path,
) -> PortfolioState:
    """隔夜推进：POST_EXECUTION(D) + same-day fills → PRE_EXECUTION(next open)。

    Raises:
        TypeError: state/fills/db_path 类型不匹配
        ValueError: phase/date/日历/position/capacity 违规
        NotImplementedError: NEXT_CLOSE（v1 仅 NEXT_OPEN）
    """
    if not isinstance(state, PortfolioState):
        raise TypeError(
            f"state 必须为 PortfolioState（收到 {type(state).__name__}）")
    if not isinstance(fills, FillBatch):
        raise TypeError(f"fills 必须为 FillBatch（收到 {type(fills).__name__}）")
    if not isinstance(db_path, Path):
        raise TypeError(
            f"db_path 必须为 pathlib.Path（收到 {type(db_path).__name__}——"
            f"str/None 拒绝）")
    if state.phase is not PortfolioStatePhase.POST_EXECUTION:
        raise ValueError(
            f"state.phase 必须为 POST_EXECUTION（收到 {state.phase.value}——"
            f"不能对 PRE state 调用，更不能对输出 PRE 再次调用）")
    if state.as_of_date != fills.execution_date:
        raise ValueError(
            f"state.as_of_date {state.as_of_date} != fills.execution_date "
            f"{fills.execution_date}")
    if fills.execution_timing is not ExecutionTiming.NEXT_OPEN:
        raise NotImplementedError(
            f"{fills.execution_timing.value} overnight transition 尚未实现——"
            f"M8 v1 仅 NEXT_OPEN（不借 state math 扩大支持范围）")

    # ---- calendar resolution（唯一 authority = trading_calendar）----
    cal = trading_calendar(db_path)
    cal_list = cal.to_list()
    if state.as_of_date not in set(cal_list):
        raise ValueError(
            f"state.as_of_date {state.as_of_date} 不是开放交易日（trade_cal "
            f"is_open=1）——POST state 应对应实际 execution trading day，"
            f"不自动向后找")
    idx = bisect.bisect_right(cal_list, state.as_of_date)
    if idx >= len(cal_list):
        raise ValueError(
            f"{state.as_of_date} 后无下一开放日（trailing unresolved——不保持"
            f"原日期/不 drop）")
    next_date = cal_list[idx]

    # ---- positions：quantity 不变；only same-day BUY filled 释放 ----
    pos: dict[str, list[int]] = {}
    for code, qty, sellable in state.positions.iter_rows():
        pos[code] = [qty, sellable]
    for code, side, filled in fills.frame.select(
            ["code", "side", "filled_quantity"]).iter_rows():
        if side != "buy":
            continue                     # SELL fill → release contribution 0
        if code not in pos:
            raise ValueError(
                f"BUY fill {code} 在 POST state 无 position——实际 BUY fill "
                f"后却无持仓 = state/fill pair 不一致")
        qty, sellable = pos[code]
        unsellable = qty - sellable
        if unsellable < filled:
            raise ValueError(
                f"POST state does not contain enough unsellable inventory "
                f"for same-day BUY provenance：{code} unsellable={unsellable} "
                f"< BUY filled={filled}")
        new_sellable = sellable + filled
        if new_sellable > qty:
            raise ValueError(
                f"{code} release 后 sellable {new_sellable} 超出 quantity "
                f"{qty}——provenance 不变量破坏")
        pos[code] = [qty, new_sellable]

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

    return PortfolioState(as_of_date=next_date,
                          phase=PortfolioStatePhase.PRE_EXECUTION,
                          cash=state.cash,
                          positions=frame)
