from __future__ import annotations

import datetime

import polars as pl

PRICE_VIEWS = ("raw", "qfq", "hfq", "pit_qfq")
_PRICE_COLS = ("open", "high", "low", "close")


def view_prices(
    df: pl.DataFrame,
    view: str = "qfq",
    asof: datetime.date | None = None,
    adj_col: str = "adj_factor",
) -> pl.DataFrame:
    """价格视图：RAW 原样；QFQ 前复权（adj/adj[latest]）；HFQ 后复权（×adj）；
    PIT_QFQ 动态前复权（adj/adj[asof]，研究日视角防未来）。"""
    if view not in PRICE_VIEWS:
        raise ValueError(f"未知价格视图 view: {view}（支持 {PRICE_VIEWS}）")
    if view == "raw":
        return df
    if view == "pit_qfq" and asof is None:
        raise ValueError("pit_qfq 视图必须提供 asof 研究日")

    if view == "qfq":
        factor = pl.col(adj_col) / pl.col(adj_col).last().over("code")
    elif view == "hfq":
        factor = pl.col(adj_col)
    else:  # pit_qfq
        base = (
            df.filter(pl.col("date") <= asof)
            .sort("date")
            .group_by("code")
            .agg(pl.col(adj_col).last().alias("_asof_adj"))
        )
        df = df.join(base, on="code", how="left")
        factor = pl.col(adj_col) / pl.col("_asof_adj")
        scaled = [pl.col(c) * factor for c in _PRICE_COLS if c in df.columns]
        return df.with_columns(scaled).drop("_asof_adj")

    scaled = [pl.col(c) * factor for c in _PRICE_COLS if c in df.columns]
    return df.with_columns(scaled)


def total_return(close: pl.Expr, adj: pl.Expr) -> pl.Expr:
    """含分红再投资的真实收益：close[t]×adj[t] / (close[t-1]×adj[t-1]) - 1（组内按日期）。"""
    hfq = close * adj
    return hfq / hfq.shift(1) - 1
