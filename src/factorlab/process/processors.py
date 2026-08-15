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
    """截面 z-score；零方差截面输出 null（NaN 不是 null，fillna 无法处理）。"""
    x = _x(df)
    std = x.std().over("date")
    return df.with_columns(pl.when(std > 0).then((x - x.mean().over("date")) / std).otherwise(None).alias(SIGNAL))


register_processor(name="zscore")(standardize)


@register_processor
def csranknorm(df: pl.DataFrame, ctx) -> pl.DataFrame:
    """截面排名归一化到 (0, 1)。"""
    x = _x(df)
    return df.with_columns((x.rank().over("date") / (x.count().over("date") + 1)).alias(SIGNAL))


@register_processor
def robustzscore(df: pl.DataFrame, ctx) -> pl.DataFrame:
    """中位数/MAD 稳健标准化；MAD=0 的截面输出 null。"""
    x = _x(df)
    med = x.median().over("date")
    mad = (x - med).abs().median().over("date")
    scaled = (x - med) / (1.4826 * mad)
    return df.with_columns(pl.when((1.4826 * mad) > 0).then(scaled).otherwise(None).alias(SIGNAL))


@register_processor
def clip(df: pl.DataFrame, ctx, lower: float, upper: float) -> pl.DataFrame:
    """常数截断。"""
    return df.with_columns(_x(df).clip(lower, upper).alias(SIGNAL))


@register_processor
def fillna(df: pl.DataFrame, ctx, method: str = "value", value: float = 0.0) -> pl.DataFrame:
    """缺失处理：value（常数）、forward（组内前向，按 code+date 排序）或
    industry_mean（静态行业组内均值，组键 date+industry）。"""
    x = _x(df)
    if method == "value":
        expr = x.fill_null(value)
    elif method == "forward":
        expr = x.fill_null(strategy="forward").over("code", order_by="date")
    elif method == "industry_mean":
        if ctx is None or ctx.db is None:
            raise ValueError("fillna(method=industry_mean) 需要 ProcessCtx(db) 上下文")
        industry = ctx.db.execute(
            "SELECT symbol, industry FROM stock_basic_tushare WHERE industry IS NOT NULL AND industry != ''"
        ).pl()
        enriched = df.join(industry.rename({"symbol": "code"}), on="code", how="left")
        return enriched.with_columns(
            x.fill_null(x.mean().over(["date", "industry"])).alias(SIGNAL)
        ).drop("industry")
    else:
        raise ValueError(f"fillna 不支持的 method: {method}（value|forward|industry_mean）")
    return df.with_columns(expr.alias(SIGNAL))


@register_processor
def neutralize(df: pl.DataFrame, ctx, by: str = "market") -> pl.DataFrame:
    """截面中心化：market 全截面 demean；industry 按静态行业组内 demean；
    size 按 daily_basic.total_mv 分组 demean。industry/size 需要 ProcessCtx(db)。"""
    x = _x(df)
    if by == "market":
        return df.with_columns((x - x.mean().over("date")).alias(SIGNAL))
    if ctx is None or ctx.db is None:
        raise ValueError("neutralize(by=industry/size) 需要 ctx（ProcessCtx 的 db 连接）")
    if by == "industry":
        industry = ctx.db.execute(
            "SELECT symbol, industry FROM stock_basic_tushare WHERE industry IS NOT NULL AND industry != ''"
        ).pl()
        enriched = df.join(industry.rename({"symbol": "code"}), on="code", how="left")
        missing = enriched["industry"].null_count()
        if missing:
            raise ValueError(f"{missing} 只股票缺少行业信息，无法 neutralize(by=industry)")
        return enriched.with_columns((x - x.mean().over(["date", "industry"])).alias(SIGNAL)).drop("industry")
    if by == "size":
        mv = ctx.db.execute("SELECT trade_date, ts_code, total_mv FROM daily_basic").pl().with_columns(
            # trade_date 'YYYYMMDD' → 面板 date 同格式（ISO 字符串），ts_code → symbol（去后缀）
            pl.col("trade_date").str.strptime(pl.Date, "%Y%m%d").cast(pl.String).alias("date"),
            pl.col("ts_code").str.split(".").list.first().alias("code"),
        ).select(["date", "code", "total_mv"])
        enriched = df.join(mv, on=["date", "code"], how="left")
        missing = enriched["total_mv"].null_count()
        if missing:
            raise ValueError(f"{missing} 行缺少 daily_basic.total_mv，无法 neutralize(by=size)")
        # 每日期内按 total_mv 排名十分位分桶（组键 date+_mv_decile），
        # 避免按原始连续市值分组导致组内 1 行 → demean 恒 0 的退化
        decile = (
            pl.col("total_mv").rank("ordinal").over("date") * 10
            // (pl.col("total_mv").count().over("date") + 1)
        ).clip(0, 9)
        enriched = enriched.with_columns(decile.alias("_mv_decile"))
        return enriched.with_columns(
            (x - x.mean().over(["date", "_mv_decile"])).alias(SIGNAL)
        ).drop("total_mv", "_mv_decile")
    raise ValueError(f"neutralize 不支持的 by: {by}（market|industry|size）")
