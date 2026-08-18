from __future__ import annotations

import datetime
from pathlib import Path

import duckdb
import polars as pl

from factorlab.config import settings


def trading_calendar(db_path: Path, date_start: str | None = None, date_end: str | None = None) -> pl.Series:
    """交易日历：平台库 trade_cal 的 is_open=1 日期（cal_date 'YYYYMMDD' → pl.Date），升序去重。

    日期范围参数支持 ISO 'YYYY-MM-DD' 与 'YYYYMMDD' 双格式（内部统一转 YYYYMMDD 查询）；
    trade_cal 按交易所分行（SSE/SZSE 同日重复），DISTINCT 去重。
    """
    with duckdb.connect(str(db_path), read_only=True) as con:
        con.execute(f"SET memory_limit='{settings.default_max_memory}'")
        con.execute("SET threads=2")
        where, params = [], []
        if date_start is not None:
            where.append("cal_date >= ?")
            params.append(date_start.replace("-", ""))
        if date_end is not None:
            where.append("cal_date <= ?")
            params.append(date_end.replace("-", ""))
        sql = "SELECT DISTINCT cal_date FROM trade_cal WHERE is_open = 1" \
            + (f" AND {' AND '.join(where)}" if where else "") + " ORDER BY cal_date"
        dates = [r[0] for r in con.execute(sql, params).fetchall()]
    return pl.Series(
        "date",
        [datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])) for d in dates],
        dtype=pl.Date,
    )


def fill_suspensions(df: pl.DataFrame, calendar: pl.Series) -> pl.DataFrame:
    """按交易日历补全停牌行：日历 × 代码全连接，缺失数值列 null。

    输出按日期升序、组内代码顺序未承诺（调用方应自行排序）；输入重复 (date, code) 行会保留并放大输出行数。
    """
    codes = pl.DataFrame({"code": df["code"].unique()})
    grid = pl.DataFrame({"date": calendar}).join(codes, how="cross")
    return grid.join(df, on=["date", "code"], how="left")


def chunk_calendar(
    cal: pl.Series,
    chunk_days: int,
    warmup_days: int = 0,
) -> list[tuple[datetime.date, datetime.date, datetime.date]]:
    """日历切块：(load_start, chunk_start, chunk_end) 三元组（日期含两端，升序）。

    chunk_days：每块交易日数（>=1）；warmup_days：块首向前多取的预热天数
    （TS 窗口历史，>=0；首块越界自动截断）。load 段 = chunk 段 + warmup 段，
    相邻块 load 段重叠 warmup_days 天（每块独立重取，无块间依赖）。
    cal 需升序去重。空日历 → []。
    """
    if chunk_days < 1:
        raise ValueError(f"chunk_days 必须 >= 1（收到 {chunk_days}）")
    if warmup_days < 0:
        raise ValueError(f"warmup_days 必须 >= 0（收到 {warmup_days}）")
    dates = cal.to_list()
    n = len(dates)
    if n == 0:
        return []
    chunks = []
    for start in range(0, n, chunk_days):
        end = min(start + chunk_days, n) - 1
        load_start = max(start - warmup_days, 0)
        chunks.append((dates[load_start], dates[start], dates[end]))
    return chunks
