"""统一研究语义层——领域数据契约。

M6-01：信号时间语义（timing）+ Signal/Label 领域对象（frames）。
M7-01：策略目标组合（portfolio）——TargetPortfolio/TargetPortfolioMeta。
M8-05B：execution accounting + point-in-time valuation（accounting）。
"""

from factorlab.domain.accounting import (ExecutionAccountingSummary,
                                         PortfolioMarkSnapshot,
                                         PortfolioValuation)
from factorlab.domain.backtest import (ArtifactManifest,
                                      BacktestResult, ExecutionArtifact,
                                      NavSeries)
from factorlab.domain.execution import (ExecutionDataQualityError,
                                       ExecutionSchedule, FillBatch,
                                       MarketOpenSnapshot, OpenFillAssessment,
                                       OpenOrderDisposition, OrderBatch,
                                       OrderSide, PortfolioState,
                                       PortfolioStatePhase, QuantityRuleKind)
from factorlab.domain.frames import LabelArtifact, SignalArtifact, SignalMeta
from factorlab.domain.portfolio import TargetPortfolio, TargetPortfolioMeta
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
    "TargetPortfolio",
    "TargetPortfolioMeta",
    "OrderSide",
    "PortfolioStatePhase",
    "PortfolioState",
    "OrderBatch",
    "ExecutionSchedule",
    "MarketOpenSnapshot",
    "QuantityRuleKind",
    "ExecutionDataQualityError",
    "OpenOrderDisposition",
    "OpenFillAssessment",
    "FillBatch",
    "ExecutionAccountingSummary",
    "PortfolioMarkSnapshot",
    "PortfolioValuation",
    "ExecutionArtifact",
    "NavSeries",
    "BacktestResult",
    "ArtifactManifest",
]
