from __future__ import annotations

import plotly.graph_objects as go
import polars as pl

# dataviz palette（验证过的默认色板——categorical/sequential/diverging/chrome）
_LIGHT_SURFACE = "#fcfcfb"
_PAGE_PLANE = "#f9f9f7"
_PRIMARY_INK = "#0b0b0b"
_SECONDARY_INK = "#52514e"
_MUTED = "#898781"
_GRIDLINE = "#e1e0d9"
_BASELINE = "#c3c2b7"

_SERIES_BLUE = "#2a78d6"    # categorical slot 1
_SERIES_ORANGE = "#eb6834"  # categorical slot 2
_SERIES_RED = "#e34948"     # categorical slot 8
_MID_GRAY = "#898781"       # diverging 中点/弱化序列

_FONT = dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif",
             size=13, color=_PRIMARY_INK)


def _base_layout(title: str, height: int) -> dict:
    """统一图表布局：surface/字体/弱化网格/图例。"""
    return dict(
        title=dict(text=title, font=dict(size=15, color=_PRIMARY_INK)),
        height=height,
        paper_bgcolor=_LIGHT_SURFACE,
        plot_bgcolor=_LIGHT_SURFACE,
        font=_FONT,
        margin=dict(l=48, r=16, t=48, b=36),
        xaxis=dict(gridcolor=_GRIDLINE, linecolor=_BASELINE, zeroline=False,
                   tickfont=dict(color=_SECONDARY_INK)),
        yaxis=dict(gridcolor=_GRIDLINE, linecolor=_BASELINE, zeroline=True,
                   zerolinecolor=_BASELINE, tickfont=dict(color=_SECONDARY_INK)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=12, color=_SECONDARY_INK)),
        hoverlabel=dict(bgcolor=_PAGE_PLANE, bordercolor=_BASELINE,
                        font=dict(color=_PRIMARY_INK)),
    )


def ic_curve_figure(ic_series: pl.DataFrame) -> str:
    """周度 RankIC 折线图（含 0 参考线）→ plotly figure JSON 字符串。"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ic_series["date"].to_list(), y=ic_series["ic"].to_list(),
        mode="lines", name="RankIC",
        line=dict(color=_SERIES_BLUE, width=2),
        hovertemplate="%{x}<br>IC=%{y:.4f}<extra></extra>"))
    fig.add_hline(y=0, line_dash="dash", line_color=_MUTED, line_width=1)
    fig.update_layout(**_base_layout("周度 RankIC", 300))
    return fig.to_json()


def decile_bar_figure(groups: list[dict]) -> str:
    """十分位平均收益柱状图（正 blue / 负 red，diverging）→ plotly figure JSON 字符串。"""
    fig = go.Figure()
    groups_sorted = sorted(groups, key=lambda g: g.get("group", 0))
    labels = [str(g.get("group")) for g in groups_sorted]
    values = [g.get("mean_ret") for g in groups_sorted]
    colors = [_SERIES_BLUE if v is not None and v >= 0 else _SERIES_RED for v in values]
    fig.add_trace(go.Bar(
        x=labels, y=values,
        marker=dict(color=colors),
        name="十分位平均收益",
        hovertemplate="档 %{x}<br>mean_ret=%{y:.4%}<extra></extra>"))
    fig.update_layout(**_base_layout("十分位平均收益", 300))
    return fig.to_json()


# 分层档位颜色：categorical 8 色相轮转（相邻档全不同色）+ D9/D10 深色变体
_LAYERED_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                   "#e87ba4", "#008300", "#4a3aa7", "#e34948",
                   "#184f95", "#c8531f"]


def layered_net_value_figure(net_values: dict[str, list[float]], dates: list[str]) -> str:
    """分层回测净值曲线 → plotly figure JSON 字符串。

    每档不同颜色（sequential blue 渐变，D1 深 → Dn 浅），long_short 橙色突出；
    全部实线。图例完整（颜色不单独承载身份）。
    """
    fig = go.Figure()
    for label, values in net_values.items():
        if label == "long_short":
            color, width = _PRIMARY_INK, 3.0  # 黑色粗线最突出
        else:
            idx = int(label[1:]) - 1  # D1 → 0
            color = _LAYERED_COLORS[idx % len(_LAYERED_COLORS)]
            width = 2.0
        fig.add_trace(go.Scatter(
            x=dates, y=values, mode="lines", name=label,
            line=dict(color=color, width=width),
            hovertemplate="%{x}<br>%{fullData.name}=%{y:.4f}<extra></extra>"))
    fig.update_layout(**_base_layout("分层回测净值", 380))
    return fig.to_json()


def correlation_heatmap_figure(names: list[str], matrix: list[list[float]]) -> str:
    """因子相关热力图（diverging：正蓝负红，0 白）→ plotly figure JSON。"""
    fig = go.Figure(go.Heatmap(
        z=matrix, x=names, y=names,
        zmin=-1, zmax=1, colorscale=[
            [0.0, "#e34948"], [0.5, "#fcfcfb"], [1.0, "#2a78d6"]],
        colorbar=dict(title="corr", tickfont=dict(color=_SECONDARY_INK)),
        hovertemplate="%{x} × %{y}<br>corr=%{z:.3f}<extra></extra>"))
    fig.update_layout(_base_layout("因子相关性", 340))
    return fig.to_json()
