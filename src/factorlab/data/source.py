from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from factorlab.config import settings

BASE_COLS = ("open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg")


def load_daily(
    db_path: Path,
    codes: list[str],
    date_start: str | None = None,
    date_end: str | None = None,
    cols: list[str] | None = None,
    float32: bool = settings.use_float32,
) -> pl.LazyFrame:
    """DuckDB 只读加载 daily 面板：SQL-first 过滤 → float32 cast → LazyFrame。"""
    if not codes:
        raise ValueError("universe 为空，无法加载数据")
    cols = cols or list(BASE_COLS)

    con = duckdb.connect(str(db_path), read_only=True)
    con.execute(f"SET memory_limit='{settings.default_max_memory}'")
    con.execute("SET threads=2")

    where = ["code IN (SELECT unnest(?))"]
    params: list = [codes]
    if date_start is not None:
        where.append("date >= ?")
        params.append(date_start)
    if date_end is not None:
        where.append("date <= ?")
        params.append(date_end)

    query = (
        f"SELECT date, code, {', '.join(cols)} FROM daily"
        f" WHERE {' AND '.join(where)} ORDER BY code, date"
    )
    df = con.execute(query, params).pl()
    con.close()
    df = df.with_columns(pl.col("date").str.strptime(pl.Date, "%Y-%m-%d"))
    if float32:
        df = df.with_columns([pl.col(c).cast(pl.Float32) for c in cols])
    return df.lazy()
