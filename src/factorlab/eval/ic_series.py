from __future__ import annotations

import polars as pl

MIN_STOCKS = 3  # 秩相关稳健性的最小有效股票数


def weekly_ic(panel: pl.DataFrame, target: str = "forward_return_5d") -> pl.DataFrame:
    """周度 RankIC：每期（周）signal 与 target 的 Spearman 秩相关序列。

    - 与 quant_core 的 RankIC 同源定义（秩相关）；polars 1.38 的
      pl.corr(method="spearman") 直接支持，无需手工 rank（rank 后
      Pearson 与之一致——秩相关即秩的 Pearson）。
    - signal/target null 行排除（复用 rust_ic 的过滤语义）。
    - 面板中每个日期都保留一行：有效股票 < MIN_STOCKS 的周 ic = null
      （秩相关不稳健；含有效股票为 0 的周）。
    - 输出 (date, ic) 按日期排序。
    - 缺列（date/code/signal/target）抛 ValueError（不依赖 polars 内部异常）。
    """
    required = {"date", "code", "signal", target}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"评估面板缺少列: {sorted(missing)}")

    valid = panel.drop_nulls(["signal", target])
    stats = valid.group_by("date").agg(
        ic=pl.corr(pl.col("signal"), pl.col(target), method="spearman"),
        n_valid=pl.len(),
    )
    return (
        panel.select("date").unique()
        .join(stats, on="date", how="left")
        .with_columns(
            pl.when(pl.col("n_valid") < MIN_STOCKS).then(None).otherwise(pl.col("ic")).alias("ic")
        )
        .select(["date", "ic"])
        .sort("date")
    )
