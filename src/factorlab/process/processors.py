"""process 基础处理器。

注意：本文件当前实现 winsorize/standardize 两个处理器（Task 5 需要真实语义使
`test_run_chain_applies_sequentially` 通过）；csranknorm/robustzscore/clip/fillna
在 Task 6 补齐（届时整体替换本文件）。
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
