from __future__ import annotations

import polars as pl

WEEKS_PER_YEAR = 52


def _group_assign(panel: pl.DataFrame, n_groups: int, direction: int) -> pl.DataFrame:
    """每期按 signal 分档：direction=1 时 D1=signal 最高档；direction=-1 时反转。

    rank 用 "ordinal"：同值 tie 各得不同 rank（连续因子值 tie 罕见，可接受）；
    分档边界由 (rank-1)*n_groups//n 自然处理（n 不整除时末档更小）。
    """
    # 降序 rank：signal 最高 → rank 1（方向感知的"最佳"排序）
    df = panel.with_columns(
        pl.col("signal").rank("ordinal", descending=direction == 1).over("date").alias("_rank"),
        pl.col("signal").count().over("date").alias("_n"),
    )
    # 档号：rank 1..n 分 n_groups 档 → (rank-1) * n_groups // n
    return df.with_columns(
        ((pl.col("_rank") - 1) * n_groups // pl.col("_n")).alias("_group")
    )


def _summary_metrics(net_values: pl.Series, returns: pl.Series) -> dict:
    """净值序列摘要：年化收益/波动/夏普/最大回撤/胜率。"""
    if len(returns) == 0:
        return {}
    annual_return = float(returns.mean() * WEEKS_PER_YEAR)
    std = returns.std()
    # 单期 std=None（样本标准差无定义）→ 波动记 0（sharpe 同理退化）
    annual_vol = float(std * (WEEKS_PER_YEAR ** 0.5)) if std is not None else 0.0
    sharpe = annual_return / annual_vol if annual_vol and annual_vol > 0 else 0.0
    peak = net_values.cum_max()
    drawdown = (net_values - peak) / peak
    dd_min = drawdown.min()
    # long_short 净值恒 ≤0 时 peak=0 → 回撤为 -inf/NaN（差值序列非净值，语义退化）
    # → 记 0.0（NaN 自比较排除，polars 全 NaN min 返回 NaN 而非 None）
    max_drawdown = float(dd_min) if dd_min is not None and dd_min == dd_min else 0.0
    win_rate = float((returns > 0).mean()) if len(returns) else 0.0
    return {
        "annual_return": round(annual_return, 6),
        "annual_vol": round(annual_vol, 6),
        "sharpe": round(sharpe, 6),
        "max_drawdown": round(max_drawdown, 6),
        "win_rate": round(win_rate, 6),
    }


def layered_backtest(
    panel: pl.DataFrame,
    direction: int,
    n_groups: int = 10,
    cost: float = 0.0,
) -> dict:
    """分层回测：每期按 signal 分档，各档 forward 等权平均累积净值；long-short = D1 - D10。

    输入周频面板（date/code/signal/forward_return_5d）。cost 参数预留（当前不建模调仓成本）。

    语义：
    - direction=1 时 D1 = signal 最高档，direction=-1 时 D1 = signal 最低档（rank 方向控制）。
    - 档收益 = 当周该档 forward_return_5d 等权平均（忽略 null）；档空期 fill_null(0)，
      净值保持前值。净值 = (1+ret) 连乘。long_short 为 D1-D10 差值序列。
    - signal/forward_return_5d 为 null 的行不参与分档与收益（周内部分行 null 的周仍
      计入期数）；某周**全部**行无效（头部窗口未满/尾部无未来收益）则该周不计入期数
      ——与 quant_core 周频评估 n_weeks 口径一致（`bt["periods"] == evaluation["n_weeks"]`）。
    - 空面板或过滤后无有效行（signal 全 null）返回空结构，不崩溃。
    """
    df = panel.filter(
        pl.col("signal").is_not_null() & pl.col("forward_return_5d").is_not_null()
    )
    if df.height == 0:
        return {"n_groups": n_groups, "periods": 0, "net_values": {}, "summary": {}, "dates": []}

    df = _group_assign(df, n_groups, direction)
    # 每期每档收益（forward 等权平均，忽略 null）
    group_ret = df.group_by(["date", "_group"]).agg(
        pl.col("forward_return_5d").mean().alias("_ret")
    ).sort(["date", "_group"])

    dates = sorted(df["date"].unique().to_list())
    net_values: dict[str, list[float]] = {}
    returns_by_group: dict[str, list[float]] = {}
    for g in range(n_groups):
        gdf = group_ret.filter(pl.col("_group") == g)
        rets = gdf.join(pl.DataFrame({"date": dates}), on="date", how="right")["_ret"]
        rets = rets.fill_null(0.0)  # 档空期视为 0 收益（净值保持）
        nv = (1.0 + rets).cum_prod().to_list()
        label = f"D{g + 1}"
        net_values[label] = [round(v, 8) for v in nv]
        returns_by_group[label] = [float(r) for r in rets.to_list()]

    # long-short：D1 - D10 净值差
    d1, d10 = net_values["D1"], net_values[f"D{n_groups}"]
    net_values["long_short"] = [round(a - b, 8) for a, b in zip(d1, d10)]
    ls_returns = [round(a - b, 8) for a, b in zip(
        returns_by_group["D1"], returns_by_group[f"D{n_groups}"])]

    summary: dict[str, dict] = {}
    for label in list(net_values):
        nv = pl.Series(net_values[label])
        if label == "long_short":
            rets = pl.Series(ls_returns)
        else:
            rets = pl.Series(returns_by_group[label])
        summary[label] = _summary_metrics(nv, rets)

    empty_groups = [
        label for label in (f"D{i}" for i in range(1, n_groups + 1))
        if all(v == 1.0 for v in net_values[label])
    ]
    return {
        "n_groups": n_groups,
        "periods": len(dates),
        "net_values": net_values,
        "summary": summary,
        "dates": [str(d) for d in dates],
        "empty_groups": empty_groups,
    }
