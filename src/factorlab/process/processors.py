"""process 基础处理器。

全部处理器作用于 signal 列、按 date 截面计算（fillna forward 按 code 分组、date 排序）。
"""
from __future__ import annotations

import polars as pl

from factorlab.process.registry import register_processor

SIGNAL = "signal"


def _x(df: pl.DataFrame) -> pl.Expr:
    return pl.col(SIGNAL)


@register_processor
def winsorize(df: pl.DataFrame, ctx, quantile: float = 0.99) -> pl.DataFrame:
    """截面分位数去极值：quantile=0.99 → 上下各 (1-q)/2 分位数 clip。"""
    if not 0.5 <= quantile < 1.0:
        raise ValueError(f"winsorize quantile 必须在 [0.5, 1.0): {quantile}")
    q_lo, q_hi = (1 - quantile) / 2, (1 + quantile) / 2
    x = _x(df)
    return df.with_columns(x.clip(x.quantile(q_lo).over("date"), x.quantile(q_hi).over("date")).alias(SIGNAL))


@register_processor
def standardize(df: pl.DataFrame, ctx) -> pl.DataFrame:
    """截面 z-score。"""
    x = _x(df)
    return df.with_columns(((x - x.mean().over("date")) / x.std().over("date")).alias(SIGNAL))


register_processor(name="zscore")(standardize)


@register_processor
def csranknorm(df: pl.DataFrame, ctx) -> pl.DataFrame:
    """截面排名归一化到 (0, 1]。"""
    x = _x(df)
    return df.with_columns((x.rank().over("date") / (x.count().over("date") + 1)).alias(SIGNAL))


@register_processor
def robustzscore(df: pl.DataFrame, ctx) -> pl.DataFrame:
    """中位数/MAD 稳健标准化。"""
    x = _x(df)
    med = x.median().over("date")
    mad = (x - med).abs().median().over("date")
    return df.with_columns(((x - med) / (1.4826 * mad)).alias(SIGNAL))


@register_processor
def clip(df: pl.DataFrame, ctx, lower: float, upper: float) -> pl.DataFrame:
    """常数截断。"""
    return df.with_columns(_x(df).clip(lower, upper).alias(SIGNAL))


@register_processor
def fillna(df: pl.DataFrame, ctx, method: str = "value", value: float = 0.0) -> pl.DataFrame:
    """缺失处理：value（常数）或 forward（组内前向，按 code+date 排序）。"""
    x = _x(df)
    if method == "value":
        expr = x.fill_null(value)
    elif method == "forward":
        expr = x.fill_null(strategy="forward").over("code", order_by="date")
    else:
        raise ValueError(f"fillna 不支持的 method: {method}（value|forward|industry_mean）")
    return df.with_columns(expr.alias(SIGNAL))
