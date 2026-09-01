"""M8-04B：conservative open fillability kernel——OrderBatch → OpenFillAssessment。

只回答 market eligibility：
    FILLABLE（fillable_price = raw open）
    或 BLOCKED_SUSPENSION / BLOCKED_LIMIT_UP / BLOCKED_LIMIT_DOWN（price null）

判定顺序严格（不可更改）：
    1. suspension（is_suspended_at_open=True → BLOCKED_SUSPENSION——
       决定性 market evidence，不需要 daily/limit 即可 blocked）
    2. daily evidence（非 suspended + has_daily=False → ExecutionDataQualityError
       ——missing executable open price evidence；DATA UNKNOWN ≠ TRADE REJECTED）
    3. limit evidence（非 suspended + has_limit=False →
       ExecutionDataQualityError——缺失 ≠ 无限制）
    4. open-vs-limit consistency（open > up / open < down → DataQualityError，
       raw Float64 比较，无 tolerance）
    5. adverse-limit queue（BUY @ open==up → BLOCKED_LIMIT_UP；SELL @
       open==dn → BLOCKED_LIMIT_DOWN——conservative v1 assumption，不是历史
       queue 重建；无逐笔/queue-position evidence 平台不重建 queue fill）
    6. FILLABLE @ open（interior、BUY @ dn、SELL @ up）

边界：
- 不接收 PortfolioState（cash/sellable 属 M8-04C）；不接收 DB（evidence 全部
  经 MarketOpenSnapshot 传入）；不接收 quantity rules（M8-01B/03 已关闭）
- 不做 actual fill / partial / probabilistic fill / fee / portfolio mutation
- 空 OrderBatch → typed empty assessment（仍校验 date/timing alignment）
"""

from __future__ import annotations

import polars as pl

from factorlab.domain.execution import (ExecutionDataQualityError,
                                        ExecutionTiming, MarketOpenSnapshot,
                                        OpenFillAssessment, OpenOrderDisposition,
                                        OrderBatch)


def assess_open_fillability(
    orders: OrderBatch,
    snapshot: MarketOpenSnapshot,
) -> OpenFillAssessment:
    """评估 OrderBatch 中每条订单在 NEXT_OPEN 市场状态下的 fillability。

    Raises:
        TypeError: orders/snapshot 类型不匹配
        ValueError: execution_date 不对齐 / order code 不在 snapshot
        NotImplementedError: NEXT_CLOSE（v1 仅 NEXT_OPEN）
        ExecutionDataQualityError: 缺/坏 execution evidence（fail fast）
    """
    if not isinstance(orders, OrderBatch):
        raise TypeError(
            f"orders 必须为 OrderBatch（收到 {type(orders).__name__}）")
    if not isinstance(snapshot, MarketOpenSnapshot):
        raise TypeError(
            f"snapshot 必须为 MarketOpenSnapshot（收到 {type(snapshot).__name__}）")
    if orders.execution_date != snapshot.execution_date:
        raise ValueError(
            f"orders.execution_date {orders.execution_date} != "
            f"snapshot.execution_date {snapshot.execution_date}")
    if orders.execution_timing is not ExecutionTiming.NEXT_OPEN:
        raise NotImplementedError(
            f"{orders.execution_timing.value} market fillability 尚未实现——"
            f"M8-04B v1 仅支持 NEXT_OPEN")

    # snapshot maps（frame 已稳定排序 → 迭代确定性）
    snap_map: dict[str, tuple[float, float, float, bool, bool, bool]] = {}
    for code, open_, _pc, up, dn, has_daily, has_limit, _rec, open_susp \
            in snapshot.frame.iter_rows():
        snap_map[code] = (open_, up, dn, has_daily, has_limit, open_susp)

    rows: list[tuple[str, str, int, str, float | None]] = []
    for code, side, quantity in orders.orders.iter_rows():
        if code not in snap_map:
            raise ValueError(
                f"order code {code} 不在 snapshot 中——cross-object coverage "
                f"bug（M8-03 snapshot scope = current ∪ target，OrderBatch 应 "
                f"为其子集）")
        open_, up, dn, has_daily, has_limit, open_susp = snap_map[code]

        # 1. suspension（决定性 market evidence，优先于一切）
        if open_susp:
            rows.append((code, side, quantity,
                         OpenOrderDisposition.BLOCKED_SUSPENSION.value, None))
            continue
        # 2. daily evidence
        if not has_daily:
            raise ExecutionDataQualityError(
                f"{code} missing executable open price evidence "
                f"(has_daily=False)——DATA UNKNOWN ≠ TRADE REJECTED，"
                f"不模拟 no-fill")
        # 3. limit evidence
        if not has_limit:
            raise ExecutionDataQualityError(
                f"{code} missing limit evidence (has_limit=False)——缺失 ≠ "
                f"无涨跌幅限制（M8-04A：92,147 daily rows 无 stk_limit join），"
                f"fail fast")
        # 4. open-vs-limit consistency（raw 比较，无 tolerance）
        if open_ > up or open_ < dn:
            raise ExecutionDataQualityError(
                f"{code} open={open_} 在合法 limits [down={dn}, up={up}] 之外"
                f"（raw Float64 比较，无 tolerance）——M8-04A outside-limit "
                f"evidence，fail fast")
        # 5. adverse-limit queue（conservative assumption）
        if side == "buy":
            if open_ == up:
                disp = OpenOrderDisposition.BLOCKED_LIMIT_UP
                rows.append((code, side, quantity, disp.value, None))
                continue
        else:
            if open_ == dn:
                disp = OpenOrderDisposition.BLOCKED_LIMIT_DOWN
                rows.append((code, side, quantity, disp.value, None))
                continue
        # 6. FILLABLE @ raw open（interior / BUY@dn / SELL@up）
        rows.append((code, side, quantity, OpenOrderDisposition.FILLABLE.value,
                     open_))

    frame = pl.DataFrame(rows, schema=["code", "side", "quantity", "disposition",
                                       "fillable_price"], orient="row")
    if frame.height:
        frame = frame.with_columns(
            pl.col("code").cast(pl.String),
            pl.col("side").cast(pl.String),
            pl.col("quantity").cast(pl.Int64),
            pl.col("disposition").cast(pl.String),
            pl.col("fillable_price").cast(pl.Float64))
        frame = frame.sort("code")
    else:
        frame = pl.DataFrame(
            {"code": pl.Series([], dtype=pl.String),
             "side": pl.Series([], dtype=pl.String),
             "quantity": pl.Series([], dtype=pl.Int64),
             "disposition": pl.Series([], dtype=pl.String),
             "fillable_price": pl.Series([], dtype=pl.Float64)})
    return OpenFillAssessment(decision_date=orders.decision_date,
                              execution_date=orders.execution_date,
                              execution_timing=orders.execution_timing,
                              frame=frame)
