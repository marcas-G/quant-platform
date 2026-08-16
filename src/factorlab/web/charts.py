from __future__ import annotations

import plotly.graph_objects as go
import polars as pl


def ic_curve_figure(ic_series: pl.DataFrame) -> str:
    """周度 RankIC 折线图（含 0 参考线）→ plotly figure JSON 字符串。"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ic_series["date"].to_list(), y=ic_series["ic"].to_list(),
                             mode="lines", name="RankIC"))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(title="周度 RankIC", height=320, margin=dict(l=40, r=20, t=40, b=30))
    return fig.to_json()


def decile_bar_figure(groups: list[dict]) -> str:
    """十分位平均收益柱状图 → plotly figure JSON 字符串。"""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[g.get("group") for g in groups], y=[g.get("mean_ret") for g in groups],
        name="十分位平均收益"))
    fig.update_layout(title="十分位收益", height=320, margin=dict(l=40, r=20, t=40, b=30))
    return fig.to_json()


def layered_net_value_figure(net_values: dict[str, list[float]], dates: list[str]) -> str:
    """分层回测净值曲线（D1-D10 + long-short）→ plotly figure JSON 字符串。

    dates 为空时 x 缺省，plotly 按 y 长度生成 0..N-1 横轴。
    """
    fig = go.Figure()
    for label, values in net_values.items():
        fig.add_trace(go.Scatter(x=dates, y=values, mode="lines", name=label))
    fig.update_layout(title="分层回测净值", height=420, margin=dict(l=40, r=20, t=40, b=30))
    return fig.to_json()
