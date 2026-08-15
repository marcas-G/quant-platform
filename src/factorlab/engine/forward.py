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
    """按 code 对齐到周频：保留每（code, 日历年, ISO 周）组内最后一个交易日的行。

    跨年 ISO 周在年边界拆分：如 ISO 2020-W53 覆盖 2020-12-28 至 2021-01-03，
    其中 2020-12-31 与 2021-01-01 分属不同日历年，各自保留为独立周组，
    避免不同年份的观测被合并到同一周。
    """
    result = df.sort(["code", "date"]).with_columns(
        pl.col("date").dt.year().alias("_year"),
        pl.col("date").dt.week().alias("_week"),
    )
    # 分两步 with_columns：同一批内新建的别名对 .over 的 by 列不可见（polars 1.38）
    result = result.with_columns(
        pl.col("date").max().over(["code", "_year", "_week"]).alias("_week_end"),
    )
    return (
        result.filter(pl.col("date") == pl.col("_week_end"))
        .drop(["_year", "_week", "_week_end"])
        .sort(["code", "date"])
    )
