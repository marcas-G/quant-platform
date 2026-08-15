from __future__ import annotations

import polars as pl


def compute_forward_returns(
    df: pl.DataFrame,
    horizons: tuple[int, ...] = (5, 20),
    close_col: str = "close",
) -> pl.DataFrame:
    """前向收益 forward_return_h = close[t+h] / close[t] - 1（h 个交易日后，组内按日期排序）。

    输入须含 date(pl.Date)/code/close，且为停牌补全后的面板（Task 4 输出）。
    前向收益是评估目标，允许使用未来数据，不受防未来函数约束。
    """
    for h in horizons:
        if h <= 0:
            raise ValueError(f"horizon 必须为正整数（交易日数），得到 {h}")
    result = df.sort(["code", "date"])
    for h in horizons:
        close = pl.col(close_col)
        expr = (close.shift(-h).over("code", order_by="date") / close - 1).alias(f"forward_return_{h}d")
        result = result.with_columns(expr)
    return result


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
