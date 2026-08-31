"""M8-02：Execution Calendar Resolver——TargetPortfolio decision_dates →
ExecutionSchedule。

- calendar truth 唯一来源：现有 factorlab.data.calendar.trading_calendar
  （trade_cal is_open=1；不重写第二套 calendar SQL）
- timing 权威来源：target.meta.source_timing.default_earliest_execution
  （NEXT_OPEN / NEXT_CLOSE——日期解析相同，均为严格 > decision 的下一
  开放日；NEXT_CLOSE market snapshot/fill 模型未实现）
- decision date 必须是开放交易日（fail）；无下一开放日 → fail whole
  （不 drop trailing）；空 target → 空 typed schedule
- 只做日期解析——不看 daily 数据（calendar truth ≠ data availability）
"""

from __future__ import annotations

import bisect
from pathlib import Path

import polars as pl

from factorlab.data.calendar import trading_calendar
from factorlab.domain.execution import ExecutionSchedule
from factorlab.domain.portfolio import TargetPortfolio


def resolve_execution_schedule(
    target: TargetPortfolio,
    db_path: Path,
) -> ExecutionSchedule:
    """把 TargetPortfolio.decision_dates 解析为 execution dates（一次 calendar
    加载 + bisect，不 per-decision 开 DB）。"""
    if not isinstance(target, TargetPortfolio):
        raise TypeError(
            f"target 必须为 TargetPortfolio（收到 {type(target).__name__}）"
            f"——decision_dates/timing 权威来源在 TargetPortfolio 中")
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path 必须为 Path（收到 {type(db_path).__name__}）")
    timing = target.meta.source_timing.default_earliest_execution
    if not target.decision_dates:
        return ExecutionSchedule(frame=pl.DataFrame(
            {"decision_date": pl.Series([], dtype=pl.Date),
             "execution_date": pl.Series([], dtype=pl.Date),
             "execution_timing": pl.Series([], dtype=pl.String)}))
    calendar = trading_calendar(db_path)
    cal_list = calendar.to_list()
    cal_set = set(cal_list)
    rows = []
    for d in target.decision_dates:
        if d not in cal_set:
            raise ValueError(
                f"decision date {d} 不是开放交易日（trade_cal is_open=1）"
                f"——上游 Signal/Schedule 已坏，不自动取下一日")
        idx = bisect.bisect_right(cal_list, d)
        if idx >= len(cal_list):
            raise ValueError(
                f"decision date {d} 后无下一开放日（trailing unresolved——"
                f"不 drop）")
        rows.append((d, cal_list[idx], timing.value))
    frame = pl.DataFrame(rows, schema=["decision_date", "execution_date",
                                       "execution_timing"], orient="row")
    frame = frame.with_columns(pl.col("decision_date").cast(pl.Date),
                               pl.col("execution_date").cast(pl.Date),
                               pl.col("execution_timing").cast(pl.String))
    return ExecutionSchedule(frame=frame.sort(["decision_date"]))
