"""因子相关性：读 results panel 的 signal，输出两两相关矩阵。

主指标为**周度横截面秩相关均值**（与 IC 同口径：每周对横截面做 Spearman，
跨周平均）；辅助为全局 Pearson（混合时间）。供 `factorlab corr` 与 Web
详情页"相关因子"复用。
"""
from __future__ import annotations

import pathlib

import numpy as np
import polars as pl

MAX_JOINED_ROWS = 20_000_000  # 内存护栏：join 后超限则每周降采样
WEEKLY_SAMPLE_STOCKS = 5000


def _load_signal(results_dir: pathlib.Path, name: str) -> pl.DataFrame:
    """读因子 panel 的 date/code/signal。"""
    p = pathlib.Path(results_dir) / name / "panel.parquet"
    if not p.exists():
        raise FileNotFoundError(f"因子 {name} 无结果（results/{name}/panel.parquet）")
    return pl.read_parquet(p).select(["date", "code", "signal"]).rename({"signal": name})


def _join_panels(names: list[str], results_dir: pathlib.Path) -> pl.DataFrame:
    joined = _load_signal(results_dir, names[0])
    for name in names[1:]:
        joined = joined.join(_load_signal(results_dir, name), on=["date", "code"], how="inner")
    if joined.height > MAX_JOINED_ROWS:
        # 每周最多 WEEKLY_SAMPLE_STOCKS 只（均匀抽样）——内存护栏
        joined = (joined
                  .with_columns(pl.int_range(0, pl.len()).over("date").alias("_r"))
                  .filter(pl.col("_r") < WEEKLY_SAMPLE_STOCKS)
                  .drop("_r"))
    return joined


def factor_correlation(names: list[str], results_dir: str | pathlib.Path,
                       ) -> pl.DataFrame:
    """两两相关矩阵：周度横截面秩相关均值 + 全局 Pearson。

    返回列：factor_a / factor_b / rank_corr / pearson（上三角对，每对一行）。
    任一因子无 results → FileNotFoundError；因子数 < 2 → ValueError。
    """
    if len(names) < 2:
        raise ValueError("至少需要 2 个因子")
    joined = _join_panels(names, pathlib.Path(results_dir))
    n = len(names)
    rank_sum = np.zeros((n, n))
    pearson = np.zeros((n, n))
    weeks = 0
    for d in joined["date"].unique().to_list():
        sub = joined.filter(pl.col("date") == d)
        if sub.height < 30:
            continue
        mat = sub.select(names).to_numpy()
        for i in range(n):
            for j in range(i + 1, n):
                xi, xj = mat[:, i], mat[:, j]
                pr = np.corrcoef(xi, xj)[0, 1]
                if not np.isnan(pr):
                    pearson[i, j] += pr
                    pearson[j, i] += pr
                # 秩相关：rank 后 Pearson 等价 Spearman
                ri = np.argsort(np.argsort(xi)).astype(float)
                rj = np.argsort(np.argsort(xj)).astype(float)
                rr = np.corrcoef(ri, rj)[0, 1]
                if not np.isnan(rr):
                    rank_sum[i, j] += rr
                    rank_sum[j, i] += rr
        weeks += 1
    denom = max(weeks, 1)
    rows = []
    for i in range(n):
        for j in range(i + 1, n):
            rows.append({
                "factor_a": names[i], "factor_b": names[j],
                "rank_corr": rank_sum[i, j] / denom,
                "pearson": pearson[i, j] / denom,
            })
    return pl.DataFrame(rows)
