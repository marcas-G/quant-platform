"""M6-01：信号时间语义——information / signal / execution time 契约。

统一平台时间四元组的领域契约。M6 当前约定（日频 EOD 信号）：

    information_cutoff = CLOSE        # t 日完整 OHLCV 收盘后才完整
    available_at       = AFTER_CLOSE  # 信号 t 日收盘后可计算/可得
    default_earliest_execution = NEXT_OPEN   # 最早 t+1 open 执行

本模块只定义语义对象，不实现 calendar/execution timestamp 计算。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InformationCutoff(Enum):
    """信号所依赖信息的截止时点（t 日何时数据才完整）。"""

    CLOSE = "close"
    OPEN = "open"


class SignalAvailability(Enum):
    """信号计算完成、可用于决策的时点。"""

    AFTER_CLOSE = "after_close"
    AT_OPEN = "at_open"


class ExecutionTiming(Enum):
    """默认最早可执行时点。"""

    NEXT_OPEN = "next_open"
    NEXT_CLOSE = "next_close"


@dataclass(frozen=True)
class SignalTiming:
    """日频信号时间语义：信息截止 → 可得 → 最早执行。

    EOD 信号使用 t 日收盘数据，在 t 日收盘后才可获得，
    默认最早只能在 t+1 open 执行。
    """

    information_cutoff: InformationCutoff
    available_at: SignalAvailability
    default_earliest_execution: ExecutionTiming


DEFAULT_EOD_SIGNAL_TIMING = SignalTiming(
    information_cutoff=InformationCutoff.CLOSE,
    available_at=SignalAvailability.AFTER_CLOSE,
    default_earliest_execution=ExecutionTiming.NEXT_OPEN,
)
