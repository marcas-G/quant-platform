"""M7-02：construct_target_portfolio——SignalArtifact → Top-K Equal-Weight TargetPortfolio。

Strategy Runtime 边界：**只接受 SignalArtifact**（LabelArtifact/DataFrame/
FactorResult/panel 全部拒绝——无 DataFrame shortcut）。

流程（M7-02 daily v1）：

    SignalArtifact(date, code, signal)
        │
        ├── Rebalance Scheduler（daily/weekly/monthly——日期选择唯一权威）
        ├── validate signal_name / frequency / canonical code / non-finite
        ├── per-date null drop（仅 scheduled dates）
        ├── direction sort（±1）
        ├── code_asc exact tie break
        ├── top_k / insufficient（use_available / all_cash）
        └── equal_weight（gross_exposure / M）
        ▼
    TargetPortfolio

decision_dates 来自 build_rebalance_schedule（M7-03）——daily = 全部 signal
dates；weekly/monthly = ISO week / calendar month 最后 available date。
非 decision date 无决策（≠ all-cash）。
"""

from __future__ import annotations

import datetime

import polars as pl

from factorlab.domain.codes import is_canonical_stock_code
from factorlab.domain.frames import SignalArtifact
from factorlab.domain.portfolio import TargetPortfolio, TargetPortfolioMeta
from factorlab.strategy.schedule import build_rebalance_schedule
from factorlab.strategy.spec import StrategySpec

_EMPTY_SCHEMA = {"decision_date": pl.Date, "code": pl.String,
                 "target_weight": pl.Float64}


def _require_signal_artifact(signal) -> SignalArtifact:
    """Strategy Runtime type guard：只接受 SignalArtifact（fail fast 于正式
    type guard，不是 AttributeError 偶然崩）。"""
    if not isinstance(signal, SignalArtifact):
        raise TypeError(
            f"Strategy Runtime 只接受 SignalArtifact（收到 "
            f"{type(signal).__name__}）——LabelArtifact/DataFrame/FactorResult/"
            f"panel 均拒绝，请显式取 factor_result.signal_artifact")
    return signal


def _require_strategy_spec(spec) -> StrategySpec:
    if not isinstance(spec, StrategySpec):
        raise TypeError(
            f"spec 必须为 StrategySpec（收到 {type(spec).__name__}）——"
            f"dict/FactorSpec 不自动转换，配置解析属于更外层入口")
    return spec


def construct_target_portfolio(
    signal: SignalArtifact,
    spec: StrategySpec,
) -> TargetPortfolio:
    """把已完成的 SignalArtifact 转化为每日 Top-K 等权 TargetPortfolio。

    - 输入只读 date/code/signal 三列（safe extra columns 不影响结果）
    - 每日期独立选择（无跨日期 carry/排名）
    - null → drop；NaN/±Inf → fail fast（non-finite 无策略语义）
    - exact tie（signal 数值相同）→ code ASC（输入行序不影响）
    - equal_weight = gross_exposure / selected_count（无 residual correction）
    - 输出 sparse positions（0 weight 不创建 row；all-cash 日 0 rows 但
      decision_date 存在）；按 (decision_date, code) 稳定排序
    - 不改动输入 SignalArtifact（pure）
    """
    _require_signal_artifact(signal)
    _require_strategy_spec(spec)
    if signal.meta.name != spec.signal_name:
        raise ValueError(
            f"signal_name 不匹配：SignalArtifact.meta.name={signal.meta.name!r} "
            f"vs StrategySpec.signal_name={spec.signal_name!r}")
    if signal.meta.frequency != "1d":
        raise ValueError(
            f"Strategy Runtime frequency contract：SignalMeta.frequency 必须为 '1d'"
            f"（收到 {signal.meta.frequency!r}）——rebalance_frequency=daily 兼容")
    df = signal.frame
    if df.height:
        # ---- 输入边界全量校验（非法 code / non-finite 即使不入选也 fail）----
        bad_code = df.filter(~pl.col("code").map_elements(
            is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False))
        if bad_code.height:
            raise ValueError(
                f"SignalArtifact 含非 canonical code: "
                f"{bad_code['code'].unique().to_list()}——输入边界全量检查，"
                f"即使永不入选也 fail")
        nonfinite = df.filter(pl.col("signal").is_not_null()
                              & ~pl.col("signal").is_finite())
        if nonfinite.height:
            raise ValueError(
                f"SignalArtifact 含 non-finite signal（NaN/±Inf 无策略语义，"
                f"非 null_policy 范畴）: {nonfinite.height} 行")

    # M7-03：日期选择唯一权威 = Rebalance Scheduler（不再自己决定 schedule）
    schedule = build_rebalance_schedule(signal, spec)
    decision_dates = schedule.decision_dates
    meta = TargetPortfolioMeta(
        strategy_name=spec.name,
        source_signal_name=signal.meta.name,
        source_timing=signal.meta.timing,
        gross_exposure=spec.gross_exposure,
        frequency=signal.meta.frequency,
        rebalance_frequency=spec.rebalance_frequency,
    )
    if df.height == 0:
        return TargetPortfolio(
            frame=pl.DataFrame(schema=_EMPTY_SCHEMA),
            decision_dates=decision_dates,
            meta=meta,
        )

    k = spec.selection.k
    gross = spec.gross_exposure
    use_available = spec.selection.on_insufficient == "use_available"
    desc = spec.direction == 1

    work = (df.select(["date", "code", "signal"])
              .filter(pl.col("signal").is_not_null()))
    parts: list[pl.DataFrame] = []
    for d in decision_dates:
        day = work.filter(pl.col("date") == d)
        n = day.height
        if n == 0 or (n < k and not use_available):
            continue   # all-cash：0 rows（decision_date 仍在 decision_dates）
        m = min(n, k)
        ranked = day.sort(by=["signal", "code"], descending=[desc, False])
        sel = ranked.head(m)
        parts.append(pl.DataFrame({
            "decision_date": pl.Series([d] * m, dtype=pl.Date),
            "code": sel["code"].to_list(),
            "target_weight": pl.Series([gross / m] * m, dtype=pl.Float64),
        }))
    frame = (pl.concat(parts).sort(["decision_date", "code"])
             if parts else pl.DataFrame(schema=_EMPTY_SCHEMA))
    return TargetPortfolio(frame=frame, decision_dates=decision_dates, meta=meta)
