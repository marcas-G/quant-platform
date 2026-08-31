"""M8-02：Public market-open snapshot API（data loader → domain validation）。"""

from __future__ import annotations

import datetime
from pathlib import Path

from factorlab.data.calendar import trading_calendar
from factorlab.data.execution import load_market_open_frame
from factorlab.domain.execution import MarketOpenSnapshot


def load_market_open_snapshot(
    db_path: Path,
    *,
    execution_date: datetime.date,
    codes: list[str],
) -> MarketOpenSnapshot:
    """加载 execution_date + canonical codes 的市场开盘证据（domain 验证后）。

    execution_date 必须为开放交易日（trade_cal is_open=1——open-date
    validation）；数据可用性由 load_market_open_frame 的 coverage gates
    独立保证（calendar truth ≠ data availability）。
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path 必须为 Path（收到 {type(db_path).__name__}）")
    if not isinstance(execution_date, datetime.date) \
            or isinstance(execution_date, datetime.datetime):
        raise ValueError(f"execution_date 必须为 datetime.date（收到 {execution_date!r}）")
    cal = trading_calendar(db_path)
    if execution_date not in set(cal.to_list()):
        raise ValueError(
            f"execution_date {execution_date} 不是开放交易日（trade_cal "
            f"is_open=1）——open-date validation fail")
    frame = load_market_open_frame(db_path, execution_date=execution_date,
                                   codes=codes)
    return MarketOpenSnapshot(execution_date=execution_date, frame=frame)
