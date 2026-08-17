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


def _load_signal(results_dir: pathlib.Path, name: str,
                 dates: list | None = None) -> pl.DataFrame:
    """读因子 panel 的 date/code/signal（dates 非 None 时 lazy 先过滤——省内存）。"""
    p = pathlib.Path(results_dir) / name / "panel.parquet"
    if not p.exists():
        raise FileNotFoundError(f"因子 {name} 无结果（results/{name}/panel.parquet）")
    lf = pl.scan_parquet(p)
    if dates is not None:
        lf = lf.filter(pl.col("date").is_in(dates))
    return (lf.select(["date", "code", "signal"]).rename({"signal": name}).collect())


def _sample_dates(df: pl.DataFrame, n: int, seed: int) -> list:
    """随机抽 n 个交易日（确定性 seed）。"""
    import random
    rng = random.Random(seed)
    dates = df["date"].unique().to_list()
    return rng.sample(dates, min(n, len(dates)))


def _join_panels(names: list[str], results_dir: pathlib.Path,
                 sample_weeks: int | None = None, seed: int = 42) -> pl.DataFrame:
    """按 date+code 合并多因子 signal → 宽表。

    - sample_weeks 非 None：先抽 sample_weeks 个交易周再合并（concat+pivot 单次
      操作——多因子链式 join 在 Windows 上偶发段错误，pivot 规避）。
    - None：全量 join + 每周降采样护栏（`factor_correlation` 路径）。
    """
    if sample_weeks:
        # 抽样周：先轻量读第一因子 date 列 → 抽周 → 各因子 lazy 过滤读
        probe = pl.scan_parquet(pathlib.Path(results_dir) / names[0] / "panel.parquet")
        dates = _sample_dates(probe.select("date").collect(), sample_weeks, seed)
        long = pl.concat(
            [_load_signal(results_dir, name, dates=dates)
             .rename({name: "value"}).with_columns(pl.lit(name).alias("factor"))
             for name in names],
            how="vertical_relaxed")
        joined = long.pivot(index=["date", "code"], columns="factor",
                            values="value", aggregate_function="first")
        # 列序固定为 names（pivot 列序可能乱）
        return joined.select(["date", "code", *names])
    signals = [_load_signal(results_dir, name) for name in names]
    joined = signals[0]
    for d in signals[1:]:
        joined = joined.join(d, on=["date", "code"], how="inner")
    if joined.height > MAX_JOINED_ROWS:
        # 每周最多 WEEKLY_SAMPLE_STOCKS 只（均匀抽样）——内存护栏
        joined = (joined
                  .with_columns(pl.int_range(0, pl.len()).over("date").alias("_r"))
                  .filter(pl.col("_r") < WEEKLY_SAMPLE_STOCKS)
                  .drop("_r"))
    return joined


def factor_correlation(names: list[str], results_dir: str | pathlib.Path,
                       sample_weeks: int | None = None, seed: int = 42,
                       ) -> pl.DataFrame:
    """两两相关矩阵：周度横截面秩相关均值 + 全局 Pearson。

    返回列：factor_a / factor_b / rank_corr / pearson（上三角对，每对一行）。
    任一因子无 results → FileNotFoundError；因子数 < 2 → ValueError。
    sample_weeks 非 None：抽样交易周（Web 全库热力图等大量因子场景的省内存路径）。
    """
    if len(names) < 2:
        raise ValueError("至少需要 2 个因子")
    joined = _join_panels(names, pathlib.Path(results_dir),
                          sample_weeks=sample_weeks, seed=seed)
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
                # Pearson：逐对 NaN 过滤（signal 含缺失）
                mask = ~(np.isnan(xi) | np.isnan(xj))
                if mask.sum() > 30:
                    pr = np.corrcoef(xi[mask], xj[mask])[0, 1]
                    if not np.isnan(pr):
                        pearson[i, j] += pr
                        pearson[j, i] += pr
                # 秩相关：rank 后 Pearson 等价 Spearman（NaN 排末位，近似）
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


def factor_svd(names: list[str] | None, results_dir: str | pathlib.Path,
               sample_weeks: int = 15, seed: int = 42,
               n_components: int = 6) -> dict:
    """因子库 SVD 分解：奇异值谱 + 主成分载荷。

    - 抽样 sample_weeks 个交易周构建信号矩阵（全量 join 在因子多时内存不稳，
      抽样后规模可控且结构分析足够）。
    - 返回 dict：singular_values（前 n_components）、cum_explained（累计占比）、
      loadings（每因子 {name, PC1..PCn} 载荷）。
    """
    if names is None:
        names = sorted(p.parent.name for p in
                       pathlib.Path(results_dir).glob("*/panel.parquet"))
    if len(names) < 2:
        raise ValueError("至少需要 2 个因子")
    joined = _join_panels(names, pathlib.Path(results_dir),
                          sample_weeks=sample_weeks or None, seed=seed)
    if joined.height < 30:
        raise ValueError("抽样后样本不足 30 行")
    mat = joined.select(names).to_numpy().astype(np.float64)
    # NaN 按列均值填充（缺失因子在部分周无值）
    col_means = np.nanmean(mat, axis=0)
    mat = np.where(np.isnan(mat), col_means[None, :], mat)
    C = np.corrcoef(mat, rowvar=False)
    np.fill_diagonal(C, 1.0)
    U, S, _ = np.linalg.svd(C)
    total = S.sum()
    cum = (np.cumsum(S) / total).tolist()
    k = min(n_components, len(names))
    loadings = []
    for i, name in enumerate(names):
        row = {"name": name}
        for c in range(k):
            row[f"PC{c + 1}"] = round(float(U[i, c]), 4)
        loadings.append(row)
    return {
        "singular_values": [round(float(s), 3) for s in S[:k]],
        "cum_explained": [round(float(v), 4) for v in cum[:k]],
        "loadings": loadings,
    }
