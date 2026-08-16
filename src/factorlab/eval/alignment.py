from __future__ import annotations

import polars as pl


def align_weekly(df: pl.DataFrame) -> pl.DataFrame:
    """对齐到 ISO 周最后一个交易日（周内 date 最大值；ISO 周跨年日期同周合并）。"""
    result = df.sort(["code", "date"]).with_columns(
        pl.col("date").dt.iso_year().alias("_iso_year"),
        pl.col("date").dt.week().alias("_week"),
    )
    # 分两步 with_columns：同一批内新建的别名对 .over 的 by 列不可见（polars 1.38）
    result = result.with_columns(
        pl.col("date").max().over(["code", "_iso_year", "_week"]).alias("_week_end"),
    )
    return (
        result.filter(pl.col("date") == pl.col("_week_end"))
        .drop(["_iso_year", "_week", "_week_end"])
        .sort(["code", "date"])
    )
