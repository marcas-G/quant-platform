from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from factorlab.config import settings


def trading_calendar(db_path: Path, date_start: str | None = None, date_end: str | None = None) -> pl.Series:
    """交易日历：daily 表 distinct date（范围内，升序），返回 pl.Date Series。"""
    with duckdb.connect(str(db_path), read_only=True) as con:
        con.execute(f"SET memory_limit='{settings.default_max_memory}'")
        con.execute("SET threads=2")
        where, params = [], []
        if date_start is not None:
            where.append("date >= ?")
            params.append(date_start)
        if date_end is not None:
            where.append("date <= ?")
            params.append(date_end)
        sql = "SELECT DISTINCT date FROM daily" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY date"
        dates = [r[0] for r in con.execute(sql, params).fetchall()]
    return pl.Series("date", dates, dtype=pl.Date)


def fill_suspensions(df: pl.DataFrame, calendar: pl.Series) -> pl.DataFrame:
    """按交易日历补全停牌行：日历 × 代码全连接，缺失数值列 null。

    输出按日期升序、组内代码顺序未承诺（调用方应自行排序）；输入重复 (date, code) 行会保留并放大输出行数。
    """
    codes = pl.DataFrame({"code": df["code"].unique()})
    grid = pl.DataFrame({"date": calendar}).join(codes, how="cross")
    return grid.join(df, on=["date", "code"], how="left")
