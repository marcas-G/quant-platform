"""M7-03：Rebalance Scheduler——Signal dates → decision dates。

把 "SignalArtifact 中哪些日期形成新 TargetPortfolio" 从 constructor 拆出：

    SignalArtifact
        │
        ▼
    Rebalance Scheduler（daily / weekly / monthly）
        │
        ▼
    RebalanceSchedule（decision_dates）
        │
        ▼
    PortfolioConstructor

- **observed-signal-domain schedule**：只基于 SignalArtifact 提供的 available
  signal dates（不读取 exchange calendar/DB）；partial first/last period 包含
  （v1 deliberate contract）
- schedule 只由日期域 + StrategySpec.rebalance_frequency 决定——signal 数值/
  code/close/label 一律不影响
- **NO DECISION vs ALL CASH**：date ∉ decision_dates = NO DECISION；
  date ∈ decision_dates + 0 positions = EXPLICIT ALL CASH
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from factorlab.domain.frames import SignalArtifact
from factorlab.strategy.spec import StrategySpec

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SCHEDULE_FREQUENCIES = ("daily", "weekly", "monthly")


@dataclass(frozen=True)
class RebalanceSchedule:
    """策略调仓计划：哪些 signal date 真正形成新的目标组合。

    - decision_dates：strict increasing unique tuple[datetime.date,...]
      （不自动 sort/dedup；() 合法）
    - frequency：daily / weekly / monthly
    - source_signal_name：schedule 来源 SignalArtifact 的 meta.name
    轻量 immutable——不持有 signal frame/codes/pointer。
    """

    decision_dates: tuple[datetime.date, ...]
    frequency: str
    source_signal_name: str

    def __post_init__(self) -> None:
        if self.frequency not in _SCHEDULE_FREQUENCIES:
            raise ValueError(
                f"frequency 仅支持 {_SCHEDULE_FREQUENCIES}（收到 {self.frequency!r}）")
        if not _NAME_RE.match(self.source_signal_name):
            raise ValueError(
                f"source_signal_name 必须匹配 ^[A-Za-z_][A-Za-z0-9_]{{0,63}}$"
                f"（收到 {self.source_signal_name!r}）")
        if not isinstance(self.decision_dates, tuple):
            raise ValueError(f"decision_dates 必须为 tuple（收到 "
                             f"{type(self.decision_dates).__name__}）")
        for i, d in enumerate(self.decision_dates):
            if not isinstance(d, datetime.date) or isinstance(d, datetime.datetime):
                raise ValueError(f"decision_dates 元素必须为 datetime.date（收到 {d!r}）")
            if i and d <= self.decision_dates[i - 1]:
                raise ValueError(
                    f"decision_dates 必须严格递增唯一（{self.decision_dates[i - 1]} -> {d}）"
                    f"——不自动 sort/dedup")


def _require_signal_artifact(signal) -> SignalArtifact:
    if not isinstance(signal, SignalArtifact):
        raise TypeError(
            f"Scheduler 只接受 SignalArtifact（收到 {type(signal).__name__}）——"
            f"LabelArtifact/DataFrame/dict 均拒绝")
    return signal


def _require_strategy_spec(spec) -> StrategySpec:
    if not isinstance(spec, StrategySpec):
        raise TypeError(
            f"spec 必须为 StrategySpec（收到 {type(spec).__name__}）——"
            f"dict 不自动转换")
    return spec


def build_rebalance_schedule(
    signal: SignalArtifact,
    spec: StrategySpec,
) -> RebalanceSchedule:
    """由 SignalArtifact 日期域 + StrategySpec.rebalance_frequency 生成 schedule。

    - daily：每个 available signal date 都是 decision date
    - weekly：每个 ISO calendar week（ISO year + ISO week）最后 available date
    - monthly：每个 calendar (year, month) 最后 available date
    - 只读取 signal.frame.date（signal 值/code 不影响）；空 signal → ()
    """
    _require_signal_artifact(signal)
    _require_strategy_spec(spec)
    if signal.meta.name != spec.signal_name:
        raise ValueError(
            f"signal_name 不匹配：SignalArtifact.meta.name={signal.meta.name!r} "
            f"vs StrategySpec.signal_name={spec.signal_name!r}")
    dates = sorted(set(signal.frame["date"].to_list()))
    freq = spec.rebalance_frequency
    if not dates:
        decision_dates: tuple[datetime.date, ...] = ()
    elif freq == "daily":
        decision_dates = tuple(dates)
    elif freq == "weekly":
        # ISO week：isocalendar() 返回 (ISO year, ISO week, weekday)——跨年正确
        # （如 2020-12-31 与 2021-01-01 同属 ISO 2020-W53）
        seen: dict[tuple[int, int], datetime.date] = {}
        for d in dates:
            key = d.isocalendar()[:2]
            seen[key] = d   # dates 升序 → 最后写入即该周最后 available date
        decision_dates = tuple(seen[k] for k in sorted(seen))
    else:  # monthly
        seen = {}
        for d in dates:
            key = (d.year, d.month)
            seen[key] = d
        decision_dates = tuple(seen[k] for k in sorted(seen))
    return RebalanceSchedule(
        decision_dates=decision_dates,
        frequency=freq,
        source_signal_name=signal.meta.name,
    )
