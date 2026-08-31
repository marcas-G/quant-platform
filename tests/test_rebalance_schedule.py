"""M7-03：Rebalance Scheduler——Signal dates → decision dates（daily/weekly/monthly）。"""

import datetime
from dataclasses import FrozenInstanceError

import polars as pl
import pytest

from factorlab.domain.frames import SignalArtifact, SignalMeta
from factorlab.domain.timing import DEFAULT_EOD_SIGNAL_TIMING
from factorlab.strategy import SelectionSpec, StrategySpec, WeightingSpec
from factorlab.strategy.schedule import RebalanceSchedule, build_rebalance_schedule

D1, D2, D3 = (datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
              datetime.date(2024, 1, 4))


def _signal(dates=None, name="alpha_x", signal_values=None):
    ds = dates or [D1, D2, D3]
    sv = signal_values if signal_values is not None else [1.0] * len(ds)
    frame = pl.DataFrame({
        "date": pl.Series(ds, dtype=pl.Date),
        "code": pl.Series(["000001.SZ"] * len(ds), dtype=pl.String),
        "signal": pl.Series(sv, dtype=pl.Float64),
    })
    return SignalArtifact(frame=frame, meta=SignalMeta(
        name=name, frequency="1d", timing=DEFAULT_EOD_SIGNAL_TIMING,
        adjustment="qfq"))


def _spec(**over):
    base = {"name": "strategy_x", "signal_name": "alpha_x", "direction": 1,
            "selection": {"method": "top_k", "k": 2},
            "weighting": {"method": "equal_weight"}}
    base.update(over)
    return StrategySpec.model_validate(base)


# ---------------- 基本 schedule ----------------

def test_daily_basic():
    s = build_rebalance_schedule(_signal(), _spec())
    assert s.decision_dates == (D1, D2, D3)
    assert s.frequency == "daily"
    assert s.source_signal_name == "alpha_x"


def test_weekly_basic():
    dates = [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
             datetime.date(2024, 1, 4), datetime.date(2024, 1, 5),
             datetime.date(2024, 1, 8), datetime.date(2024, 1, 9),
             datetime.date(2024, 1, 10), datetime.date(2024, 1, 11)]
    s = build_rebalance_schedule(_signal(dates), _spec(rebalance_frequency="weekly"))
    assert s.decision_dates == (datetime.date(2024, 1, 5), datetime.date(2024, 1, 11))


def test_monthly_basic():
    dates = [datetime.date(2024, 1, 2), datetime.date(2024, 1, 31),
             datetime.date(2024, 2, 1), datetime.date(2024, 2, 29)]
    s = build_rebalance_schedule(_signal(dates), _spec(rebalance_frequency="monthly"))
    assert s.decision_dates == (datetime.date(2024, 1, 31), datetime.date(2024, 2, 29))


def test_empty_signal():
    f = pl.DataFrame({"date": pl.Series([], dtype=pl.Date),
                      "code": pl.Series([], dtype=pl.String),
                      "signal": pl.Series([], dtype=pl.Float64)})
    s = build_rebalance_schedule(
        SignalArtifact(frame=f, meta=SignalMeta(
            name="alpha_x", frequency="1d", timing=DEFAULT_EOD_SIGNAL_TIMING,
            adjustment="qfq")), _spec())
    assert s.decision_dates == ()
    assert s.frequency == "daily"


# ---------------- input guards ----------------

def test_wrong_signal_type():
    with pytest.raises((TypeError, ValueError)):
        build_rebalance_schedule(pl.DataFrame(), _spec())


def test_wrong_spec_type():
    with pytest.raises((TypeError, ValueError)):
        build_rebalance_schedule(_signal(), {"name": "x"})


def test_signal_name_mismatch():
    with pytest.raises(ValueError, match="signal_name"):
        build_rebalance_schedule(_signal(name="alpha_b"), _spec())


# ---------------- ISO 语义 ----------------

def test_iso_year_boundary():
    """2020-12-28/12-31/2021-01-01 同属 ISO 2020-W53；2021-01-04/08 属 2021-W01。"""
    dates = [datetime.date(2020, 12, 28), datetime.date(2020, 12, 31),
             datetime.date(2021, 1, 1), datetime.date(2021, 1, 4),
             datetime.date(2021, 1, 8)]
    s = build_rebalance_schedule(_signal(dates), _spec(rebalance_frequency="weekly"))
    assert s.decision_dates == (datetime.date(2021, 1, 1), datetime.date(2021, 1, 8))


def test_missing_friday():
    """Mon-Thu 有 signal、周五不存在 → 该周选 Thu（last available）。"""
    dates = [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
             datetime.date(2024, 1, 4)]
    s = build_rebalance_schedule(_signal(dates), _spec(rebalance_frequency="weekly"))
    assert s.decision_dates == (datetime.date(2024, 1, 4),)


def test_partial_first_week():
    """sample 从周三开始 → 该 observed week 最后 signal date 仍是 decision。"""
    dates = [datetime.date(2024, 1, 3), datetime.date(2024, 1, 4),
             datetime.date(2024, 1, 5)]
    s = build_rebalance_schedule(_signal(dates), _spec(rebalance_frequency="weekly"))
    assert s.decision_dates == (datetime.date(2024, 1, 5),)


def test_partial_last_week():
    """sample 周三结束 → 周三仍是 decision（observed-domain contract）。"""
    dates = [datetime.date(2024, 1, 8), datetime.date(2024, 1, 9),
             datetime.date(2024, 1, 10)]
    s = build_rebalance_schedule(_signal(dates), _spec(rebalance_frequency="weekly"))
    assert s.decision_dates == (datetime.date(2024, 1, 10),)


def test_partial_month():
    """sample 月中结束 → observed month 最后 signal date 是 decision（v1 deliberate）。"""
    dates = [datetime.date(2024, 1, 15), datetime.date(2024, 1, 20)]
    s = build_rebalance_schedule(_signal(dates), _spec(rebalance_frequency="monthly"))
    assert s.decision_dates == (datetime.date(2024, 1, 20),)


# ---------------- 不变性 ----------------

def test_shuffle_invariant():
    dates = [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
             datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)]
    d8 = [d for d in dates for _ in range(2)]
    f = pl.DataFrame({"date": pl.Series(d8, dtype=pl.Date),
                      "code": pl.Series(["000001.SZ", "600000.SH"] * 4, dtype=pl.String),
                      "signal": pl.Series([1.0] * 8, dtype=pl.Float64)})
    s1 = build_rebalance_schedule(SignalArtifact(frame=f, meta=SignalMeta(
        name="alpha_x", frequency="1d", timing=DEFAULT_EOD_SIGNAL_TIMING,
        adjustment="qfq")), _spec(rebalance_frequency="weekly"))
    f2 = f[pl.Series([7, 0, 5, 2, 6, 1, 4, 3])]   # shuffle rows
    s2 = build_rebalance_schedule(SignalArtifact(frame=f2, meta=SignalMeta(
        name="alpha_x", frequency="1d", timing=DEFAULT_EOD_SIGNAL_TIMING,
        adjustment="qfq")), _spec(rebalance_frequency="weekly"))
    assert s1.decision_dates == s2.decision_dates


def test_signal_value_isolation():
    """signal 数值改变 → schedule 完全不变。"""
    dates = [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
             datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)]
    s1 = build_rebalance_schedule(_signal(dates, signal_values=[1.0] * 4),
                                  _spec(rebalance_frequency="weekly"))
    s2 = build_rebalance_schedule(_signal(dates, signal_values=[99.0, -5.0, 0.5, 42.0]),
                                  _spec(rebalance_frequency="weekly"))
    assert s1.decision_dates == s2.decision_dates


def test_all_null_signal_value_isolation():
    dates = [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
             datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)]
    s1 = build_rebalance_schedule(_signal(dates, signal_values=[1.0] * 4),
                                  _spec(rebalance_frequency="monthly"))
    s2 = build_rebalance_schedule(_signal(dates, signal_values=[None] * 4),
                                  _spec(rebalance_frequency="monthly"))
    assert s1.decision_dates == s2.decision_dates


def test_safe_extra_columns_isolation():
    dates = [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
             datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)]
    f = _signal(dates).frame.with_columns(pl.lit(10.0).alias("close"),
                                          pl.lit("x").alias("foo"))
    sa = SignalArtifact(frame=f, meta=SignalMeta(
        name="alpha_x", frequency="1d", timing=DEFAULT_EOD_SIGNAL_TIMING,
        adjustment="qfq"))
    s1 = build_rebalance_schedule(_signal(dates), _spec(rebalance_frequency="daily"))
    s2 = build_rebalance_schedule(sa, _spec(rebalance_frequency="daily"))
    assert s1.decision_dates == s2.decision_dates


def test_duplicate_dates_collapse():
    """同日期多行（多股票）→ date 去重后排序（单 decision）。"""
    f = pl.DataFrame({"date": pl.Series([D1, D1, D2], dtype=pl.Date),
                      "code": pl.Series(["000001.SZ", "600000.SH", "000001.SZ"],
                                        dtype=pl.String),
                      "signal": pl.Series([1.0, 1.0, 1.0], dtype=pl.Float64)})
    sa = SignalArtifact(frame=f, meta=SignalMeta(
        name="alpha_x", frequency="1d", timing=DEFAULT_EOD_SIGNAL_TIMING,
        adjustment="qfq"))
    s = build_rebalance_schedule(sa, _spec())
    assert s.decision_dates == (D1, D2)


# ---------------- RebalanceSchedule 对象契约 ----------------

def test_output_frozen():
    s = build_rebalance_schedule(_signal(), _spec())
    with pytest.raises(FrozenInstanceError):
        s.decision_dates = (D2,)


def test_decision_dates_sorted_unique():
    s = build_rebalance_schedule(_signal(), _spec())
    assert s.decision_dates == tuple(sorted(set(s.decision_dates)))


def test_source_signal_name():
    s = build_rebalance_schedule(_signal(name="alpha_9"),
                                 _spec(signal_name="alpha_9"))
    assert s.source_signal_name == "alpha_9"


@pytest.mark.parametrize("freq", ["daily", "weekly", "monthly"])
def test_frequency_valid(freq):
    s = build_rebalance_schedule(_signal(), _spec(rebalance_frequency=freq))
    assert s.frequency == freq


def test_invalid_schedule_frequency():
    with pytest.raises(ValueError):
        RebalanceSchedule(decision_dates=(D1,), frequency="5d",
                          source_signal_name="alpha_x")


def test_manual_schedule_unsorted_fails():
    with pytest.raises(ValueError):
        RebalanceSchedule(decision_dates=(D2, D1), frequency="daily",
                          source_signal_name="alpha_x")


def test_manual_schedule_duplicate_fails():
    with pytest.raises(ValueError):
        RebalanceSchedule(decision_dates=(D1, D1), frequency="daily",
                          source_signal_name="alpha_x")


def test_manual_schedule_datetime_fails():
    with pytest.raises(ValueError):
        RebalanceSchedule(decision_dates=(datetime.datetime(2024, 1, 2),),
                          frequency="daily", source_signal_name="alpha_x")


def test_manual_schedule_empty_ok():
    s = RebalanceSchedule(decision_dates=(), frequency="monthly",
                          source_signal_name="alpha_x")
    assert s.decision_dates == ()
