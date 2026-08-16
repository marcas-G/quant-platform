from __future__ import annotations

import polars as pl


def compute_forward_returns(
    df: pl.DataFrame,
    horizons: tuple[int, ...] = (5, 20),
    close_col: str = "close",
    adj_col: str = "adj_factor",
) -> pl.DataFrame:
    """前向收益（total_return 口径）：close[t+h]×adj[t+h] / (close[t]×adj[t]) - 1，
    含分红再投资（M3b 复权架构统一收益语义：HFQ 收益 = QFQ 收益，等比缩放不影响收益率）。

    输入须含 date(pl.Date)/code/close/adj_factor（close 为 raw 价格——调用方应先于
    view_prices 计算，避免复权视图下的二次复权），且为停牌补全后的面板。
    前向收益是评估目标，允许使用未来数据，不受防未来函数约束。
    """
    for h in horizons:
        if h <= 0:
            raise ValueError(f"horizon 必须为正整数（交易日数），得到 {h}")
    missing = [c for c in (close_col, adj_col) if c not in df.columns]
    if missing:
        raise ValueError(f"compute_forward_returns 需要列 {missing}（total_return = {close_col}×{adj_col}）")
    result = df.sort(["code", "date"])
    hfq = pl.col(close_col) * pl.col(adj_col)
    for h in horizons:
        expr = (hfq.shift(-h).over("code", order_by="date") / hfq - 1).alias(f"forward_return_{h}d")
        result = result.with_columns(expr)
    return result
