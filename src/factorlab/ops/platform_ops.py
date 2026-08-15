from __future__ import annotations

import polars as pl

from factorlab.ops.registry import factor_op


def returns(close: pl.Expr) -> pl.Expr:
    """单期收益率：close / prev_close - 1。"""
    return close / close.shift(1) - 1


def vwap(high: pl.Expr, low: pl.Expr, close: pl.Expr, volume: pl.Expr) -> pl.Expr:
    """成交量加权均价（累计式）。"""
    typical = (high + low + close) / 3
    return (typical * volume).cum_sum() / volume.cum_sum()


def adv20(volume: pl.Expr) -> pl.Expr:
    """20 日均成交额/量。"""
    return volume.rolling_mean(window_size=20)


def group_rank(key: pl.Expr, x: pl.Expr) -> pl.Expr:
    """组内排名：x 按 key 分组后取 rank。"""
    return x.rank().over(key)


def group_mean(key: pl.Expr, x: pl.Expr) -> pl.Expr:
    """组内均值：x 按 key 分组后取 mean。"""
    return x.mean().over(key)


def register_platform_ops() -> None:
    """幂等注册平台薄封装算子，供分区校验与 op list 使用。"""
    factor_op("returns", kind="ts", version="0.1.0")(returns)
    factor_op("vwap", kind="ts", version="0.1.0")(vwap)
    factor_op("adv20", kind="ts", version="0.1.0")(adv20)
    factor_op("group_rank", kind="gp", version="0.1.0")(group_rank)
    factor_op("group_mean", kind="gp", version="0.1.0")(group_mean)
