from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Callable

import polars as pl

PRICE_VIEWS = ("raw", "qfq", "hfq", "pit_qfq")
_PRICE_COLS = ("open", "high", "low", "close")

FactorFn = Callable[[pl.DataFrame], pl.DataFrame]


@dataclass
class AuditReport:
    check: str
    passed: bool
    details: dict


def _require_columns(df: pl.DataFrame, columns: tuple[str, ...], name: str) -> None:
    """校验 factor_fn 输出面板的必需列（date/code/signal）。"""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: factor_fn 输出缺少列 {missing}（需要 {list(columns)}）")


def _align(left: pl.DataFrame, right: pl.DataFrame) -> pl.DataFrame:
    return left.join(right, on=["date", "code"], how="inner", suffix="_audit")


def lookahead_check(factor_fn: FactorFn, df: pl.DataFrame, asof: datetime.date) -> AuditReport:
    """未来信息泄漏检测：asof 截断数据重算因子 vs 全量重算，截断后受影响的行即泄漏。
    null 视为有效值：截断侧变 null（用了截断点之后的未来数据）同样计为受影响；
    两侧同为 null（如窗口首行）不算受影响。"""
    full = factor_fn(df)
    truncated = factor_fn(df.filter(pl.col("date") <= asof))
    _require_columns(full, ("date", "code", "signal"), "lookahead_check")
    _require_columns(truncated, ("date", "code", "signal"), "lookahead_check")
    aligned = _align(full.filter(pl.col("date") <= asof), truncated)
    l_null = aligned["signal"].is_null()
    r_null = aligned["signal_audit"].is_null()
    diff = (aligned["signal"].fill_null(0.0) - aligned["signal_audit"].fill_null(0.0)).abs()
    changed = (diff > 1e-9) & ~(l_null & r_null)
    affected = int((changed | (l_null ^ r_null)).sum())
    return AuditReport(
        check="lookahead",
        passed=affected == 0,
        details={"affected_rows": affected, "asof": str(asof)},
    )


def scale_invariance_check(factor_fn: FactorFn, df: pl.DataFrame) -> AuditReport:
    """价格尺度不变性：RAW 与 QFQ 视图下因子应一致（收益率类天然不变）。"""
    raw = factor_fn(view_prices(df, "raw"))
    qfq = factor_fn(view_prices(df, "qfq"))
    _require_columns(raw, ("date", "code", "signal"), "scale_invariance_check")
    _require_columns(qfq, ("date", "code", "signal"), "scale_invariance_check")
    aligned = _align(raw, qfq)
    diff = (aligned["signal"] - aligned["signal_audit"]).abs()
    m = diff.max()
    max_diff = float(m) if m is not None else 0.0
    return AuditReport(
        check="scale_invariance",
        passed=max_diff < 1e-6,
        details={"max_abs_diff": round(max_diff, 8), "compared_rows": aligned.height},
    )


def adjustment_sensitivity_check(
    factor_fn: FactorFn,
    df: pl.DataFrame,
    views: tuple[str, ...] = ("raw", "qfq", "hfq"),
) -> AuditReport:
    """复权口径切换敏感性：各视图因子值的最大绝对变化。"""
    frames = [factor_fn(view_prices(df, v)) for v in views]
    for v, frame in zip(views, frames, strict=False):
        _require_columns(frame, ("date", "code", "signal"), "adjustment_sensitivity_check")
    merged = frames[0].rename({"signal": "signal_raw"})
    for v, frame in zip(views[1:], frames[1:], strict=False):
        merged = merged.join(frame.rename({"signal": f"signal_{v}"}), on=["date", "code"], how="inner")
    max_abs = 0.0
    if len(views) > 1:
        exprs = [(pl.col(f"signal_{v}") - pl.col("signal_raw")).abs().max() for v in views[1:]]
        m = merged.select(pl.max_horizontal(*exprs).alias("_max_abs"))["_max_abs"][0]
        max_abs = float(m) if m is not None else 0.0
    return AuditReport(
        check="adjustment_sensitivity",
        passed=max_abs < 1e-6,
        details={"max_abs_diff": round(max_abs, 8), "views": list(views)},
    )


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

    if view in ("qfq", "pit_qfq"):
        # latest 语义基于日期而非行序：先按 code+date 排序保证 .last() 取日期最新
        df = df.sort(["code", "date"])

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
