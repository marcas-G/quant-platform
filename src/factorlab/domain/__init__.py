"""M6-01：统一研究语义层——领域数据契约。

当前提供：信号时间语义（timing）+ Signal/Label 领域对象（frames）。
尚未接线到现有因子计算链路（M6-01 只定义契约，不改运行流程）。
"""

from factorlab.domain.frames import LabelArtifact, SignalArtifact, SignalMeta
from factorlab.domain.timing import (
    DEFAULT_EOD_SIGNAL_TIMING,
    ExecutionTiming,
    InformationCutoff,
    SignalAvailability,
    SignalTiming,
)

__all__ = [
    "SignalArtifact",
    "LabelArtifact",
    "SignalMeta",
    "SignalTiming",
    "InformationCutoff",
    "SignalAvailability",
    "ExecutionTiming",
    "DEFAULT_EOD_SIGNAL_TIMING",
]
