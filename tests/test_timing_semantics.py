"""M6-01：Domain Contracts——信号时间语义（information/signal/execution time）。"""

from dataclasses import FrozenInstanceError

import pytest

from factorlab.domain.timing import (DEFAULT_EOD_SIGNAL_TIMING, ExecutionTiming,
                                     InformationCutoff, SignalAvailability,
                                     SignalTiming)


# ---------------------------------------------------------------- 默认 EOD 约定

def test_default_eod_timing():
    assert DEFAULT_EOD_SIGNAL_TIMING.information_cutoff == InformationCutoff.CLOSE
    assert DEFAULT_EOD_SIGNAL_TIMING.available_at == SignalAvailability.AFTER_CLOSE
    assert DEFAULT_EOD_SIGNAL_TIMING.default_earliest_execution == ExecutionTiming.NEXT_OPEN


def test_signal_timing_construct():
    t = SignalTiming(
        information_cutoff=InformationCutoff.CLOSE,
        available_at=SignalAvailability.AFTER_CLOSE,
        default_earliest_execution=ExecutionTiming.NEXT_OPEN,
    )
    assert t.information_cutoff is InformationCutoff.CLOSE


def test_signal_timing_repr_documents_semantics():
    """repr 应体现：t 日完整 OHLCV → t 收盘后可得 → 最早 t+1 open 执行。"""
    r = repr(DEFAULT_EOD_SIGNAL_TIMING)
    assert "CLOSE" in r and "AFTER_CLOSE" in r and "NEXT_OPEN" in r


def test_enum_membership():
    assert InformationCutoff.CLOSE.value == "close"
    assert SignalAvailability.AFTER_CLOSE.value == "after_close"
    assert ExecutionTiming.NEXT_OPEN.value == "next_open"


# ---------------------------------------------------------------- 不可变

def test_timing_immutable():
    with pytest.raises(FrozenInstanceError):
        DEFAULT_EOD_SIGNAL_TIMING.information_cutoff = InformationCutoff.OPEN
    with pytest.raises(FrozenInstanceError):
        DEFAULT_EOD_SIGNAL_TIMING.available_at = SignalAvailability.AT_OPEN


def test_enum_not_reassignable_semantics():
    """Enum 成员不可再赋值（类级不可变）。"""
    with pytest.raises(AttributeError):
        InformationCutoff.CLOSE = InformationCutoff.OPEN  # type: ignore[misc]
