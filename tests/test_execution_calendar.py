"""M8-02：ExecutionSchedule + resolve_execution_schedule（calendar resolver）。"""

import datetime
from dataclasses import FrozenInstanceError
from pathlib import Path

import duckdb
import polars as pl
import pytest

from factorlab.domain import (ExecutionSchedule, TargetPortfolio,
                              TargetPortfolioMeta)
from factorlab.domain.timing import (DEFAULT_EOD_SIGNAL_TIMING,
                                     ExecutionTiming, SignalTiming,
                                     InformationCutoff, SignalAvailability)
from factorlab.execution import resolve_execution_schedule

D0 = datetime.date(2024, 1, 5)    # Fri open
D1 = datetime.date(2024, 1, 6)    # Sat
D2 = datetime.date(2024, 1, 7)    # Sun
D3 = datetime.date(2024, 1, 8)    # Mon open
D4 = datetime.date(2024, 1, 9)    # Tue open
D5 = datetime.date(2024, 1, 10)   # Wed open
NEXT_MON = datetime.date(2024, 1, 15)


def _cal_db(tmp_path, open_dates):
    db = duckdb.connect(tmp_path / "c.duckdb")
    db.execute("CREATE TABLE trade_cal (cal_date VARCHAR, is_open INT)")
    for d in open_dates:
        db.execute("INSERT INTO trade_cal VALUES (?, 1)", (d.strftime("%Y%m%d"),))
    db.execute("CREATE TABLE daily (trade_date VARCHAR, ts_code VARCHAR, open DOUBLE, pre_close DOUBLE)")
    db.execute("CREATE TABLE stk_limit (trade_date VARCHAR, ts_code VARCHAR, up_limit DOUBLE, down_limit DOUBLE)")
    db.execute("CREATE TABLE suspend_d (trade_date VARCHAR, ts_code VARCHAR)")
    return db


def _cal(tmp_path, open_dates):
    db = _cal_db(tmp_path, open_dates)
    db.close()
    return tmp_path / "c.duckdb"


def _target(tmp_path, dates=(D0,), timing=DEFAULT_EOD_SIGNAL_TIMING,
            gross=1.0, positions_rows=None):
    meta = TargetPortfolioMeta(strategy_name="s", source_signal_name="alpha",
                               source_timing=timing, gross_exposure=gross)
    frame = (pl.DataFrame({"decision_date": pl.Series([d for d in dates for _ in range(2)],
                                                      dtype=pl.Date),
                           "code": pl.Series(["000001.SZ", "600000.SH"] * len(dates),
                                             dtype=pl.String),
                           "target_weight": pl.Series([0.5, 0.5] * len(dates),
                                                      dtype=pl.Float64)})
             if positions_rows is None else positions_rows)
    return TargetPortfolio(frame=frame, decision_dates=tuple(dates), meta=meta)


# ---------------- 基本解析 ----------------

def test_basic_next_open(tmp_path):
    cal = _cal(tmp_path, [D0, D3, D4])   # D1(周六)/D2(周日) 非 open
    s = resolve_execution_schedule(_target(tmp_path), cal)
    assert s.frame.height == 1
    assert s.frame["decision_date"][0] == D0
    assert s.frame["execution_date"][0] == D3
    assert s.frame["execution_timing"][0] == "next_open"


def test_weekend_skip(tmp_path):
    cal = _cal(tmp_path, [D0, D3, D4])   # D1(周六)/D2(周日) 非 open
    s = resolve_execution_schedule(_target(tmp_path, dates=[D0]), cal)
    assert s.frame["execution_date"][0] == D3


def test_multi_day_holiday(tmp_path):
    h0, h4 = datetime.date(2024, 2, 5), datetime.date(2024, 2, 9)
    cal = _cal(tmp_path, [h0, h4])   # 2/6-2/8 闭市
    s = resolve_execution_schedule(_target(tmp_path, dates=[h0]), cal)
    assert s.frame["execution_date"][0] == h4


def test_next_close_date_same_next_trading_day(tmp_path):
    cal = _cal(tmp_path, [D0, D3, D4])
    timing = SignalTiming(information_cutoff=InformationCutoff.CLOSE,
                          available_at=SignalAvailability.AFTER_CLOSE,
                          default_earliest_execution=ExecutionTiming.NEXT_CLOSE)
    s = resolve_execution_schedule(_target(tmp_path, timing=timing), cal)
    assert s.frame["execution_date"][0] == D3
    assert s.frame["execution_timing"][0] == "next_close"


def test_multiple_decisions(tmp_path):
    cal = _cal(tmp_path, [D0, D3, D4, D5])
    s = resolve_execution_schedule(_target(tmp_path, dates=[D0, D3, D4]), cal)
    assert s.frame["decision_date"].to_list() == [D0, D3, D4]
    assert s.frame["execution_date"].to_list() == [D3, D4, D5]


# ---------------- input guards ----------------

def test_target_type_guard(tmp_path):
    cal = _cal(tmp_path, [D0, D3])
    with pytest.raises((TypeError, ValueError)):
        resolve_execution_schedule({"decision_dates": [D0]}, cal)


def test_db_path_type_guard(tmp_path):
    cal = _cal(tmp_path, [D0, D3])
    with pytest.raises((TypeError, ValueError)):
        resolve_execution_schedule(_target(tmp_path), "not_a_path")


# ---------------- 边界 ----------------

def test_empty_target(tmp_path):
    cal = _cal(tmp_path, [D0, D3])
    meta = TargetPortfolioMeta(strategy_name="s", source_signal_name="alpha",
                               source_timing=DEFAULT_EOD_SIGNAL_TIMING,
                               gross_exposure=1.0)
    t = TargetPortfolio(frame=pl.DataFrame({"decision_date": pl.Series([], dtype=pl.Date),
                                            "code": pl.Series([], dtype=pl.String),
                                            "target_weight": pl.Series([], dtype=pl.Float64)}),
                        decision_dates=(), meta=meta)
    s = resolve_execution_schedule(t, cal)
    assert s.frame.height == 0
    assert s.frame.schema["decision_date"] == pl.Date
    assert s.frame.schema["execution_date"] == pl.Date
    assert s.frame.schema["execution_timing"] == pl.String


def test_all_cash_date_retained(tmp_path):
    """all-cash decision date（0 positions）仍产生 execution schedule。"""
    cal = _cal(tmp_path, [D0, D3, D4])
    f = pl.DataFrame({"decision_date": pl.Series([D0, D0, D3], dtype=pl.Date),
                      "code": pl.Series(["000001.SZ", "600000.SH", "000001.SZ"],
                                        dtype=pl.String),
                      "target_weight": pl.Series([0.5, 0.5, 1.0], dtype=pl.Float64)})
    t = TargetPortfolio(frame=f, decision_dates=(D0, D3), meta=TargetPortfolioMeta(
        strategy_name="s", source_signal_name="alpha",
        source_timing=DEFAULT_EOD_SIGNAL_TIMING, gross_exposure=1.0))
    s = resolve_execution_schedule(t, cal)
    assert s.frame["decision_date"].to_list() == [D0, D3]
    assert s.frame["execution_date"].to_list() == [D3, D4]


def test_weekly_target_only_fridays(tmp_path):
    """weekly target：只有 decision_dates（Fridays）进入 execution schedule。"""
    fri1, fri2 = datetime.date(2024, 1, 5), datetime.date(2024, 1, 12)
    mon, next_mon = datetime.date(2024, 1, 8), datetime.date(2024, 1, 15)
    cal = _cal(tmp_path, [fri1, mon, fri2, next_mon])
    s = resolve_execution_schedule(_target(tmp_path, dates=[fri1, fri2]), cal)
    assert s.frame["decision_date"].to_list() == [fri1, fri2]
    assert s.frame["execution_date"].to_list() == [mon, next_mon]


def test_non_open_decision_fails(tmp_path):
    """decision date 非开放交易日 → fail（不自动取 Monday）。"""
    cal = _cal(tmp_path, [D0, D3, D4])
    sat = datetime.date(2024, 1, 6)   # 不在 trade_cal open
    with pytest.raises(ValueError, match="开放交易日|open"):
        resolve_execution_schedule(_target(tmp_path, dates=[sat]), cal)


def test_no_next_open_fails(tmp_path):
    """decision 后无下一开放日 → fail whole（不 drop trailing）。"""
    cal = _cal(tmp_path, [D0])
    with pytest.raises(ValueError, match="无下一开放日|trailing"):
        resolve_execution_schedule(_target(tmp_path, dates=[D0]), cal)


# ---------------- output contract ----------------

def test_output_schema_exact(tmp_path):
    cal = _cal(tmp_path, [D0, D3])
    s = resolve_execution_schedule(_target(tmp_path), cal)
    assert s.frame.columns == ["decision_date", "execution_date", "execution_timing"]
    assert s.frame.schema["decision_date"] == pl.Date
    assert s.frame.schema["execution_date"] == pl.Date
    assert s.frame.schema["execution_timing"] == pl.String


def test_decision_unique(tmp_path):
    cal = _cal(tmp_path, [D0, D3])
    s = resolve_execution_schedule(_target(tmp_path, dates=[D0]), cal)
    assert s.frame.height == 1   # 每 decision 恰一个 execution event


def test_execution_greater_than_decision_all_rows(tmp_path):
    cal = _cal(tmp_path, [D0, D3, D4, D5])
    s = resolve_execution_schedule(_target(tmp_path, dates=[D0, D3, D4]), cal)
    assert (s.frame["execution_date"] > s.frame["decision_date"]).all()


def test_stable_order(tmp_path):
    cal = _cal(tmp_path, [D0, D3, D4, D5])
    s = resolve_execution_schedule(_target(tmp_path, dates=[D0, D3, D4]), cal)
    assert s.frame.equals(s.frame.sort(["decision_date"]))


def test_frozen(tmp_path):
    cal = _cal(tmp_path, [D0, D3])
    s = resolve_execution_schedule(_target(tmp_path), cal)
    with pytest.raises(FrozenInstanceError):
        s.frame = pl.DataFrame()


def test_timing_values_exact(tmp_path):
    cal = _cal(tmp_path, [D0, D3])
    s = resolve_execution_schedule(_target(tmp_path), cal)
    assert s.frame["execution_timing"][0] == "next_open"
    assert ExecutionTiming(s.frame["execution_timing"][0]) == ExecutionTiming.NEXT_OPEN


def test_independent_of_position_rows(tmp_path):
    """schedule 只由 decision_dates 决定——positions 内容不影响。"""
    cal = _cal(tmp_path, [D0, D3])
    t1 = _target(tmp_path, dates=[D0])
    f2 = pl.DataFrame({"decision_date": pl.Series([D0], dtype=pl.Date),
                       "code": pl.Series(["000001.SZ"], dtype=pl.String),
                       "target_weight": pl.Series([1.0], dtype=pl.Float64)})
    t2 = TargetPortfolio(frame=f2, decision_dates=(D0,), meta=t1.meta)
    assert resolve_execution_schedule(t1, cal).frame.equals(
        resolve_execution_schedule(t2, cal).frame)


# ================================================================
# M8-02 集成：TargetPortfolio → ExecutionSchedule → MarketOpenSnapshot
# ================================================================

def test_integration_schedule_to_snapshot(tmp_path):
    """§95：真实 TargetPortfolio → schedule → snapshot（同 execution_date、
    canonical codes、raw open evidence）。"""
    from factorlab.data.execution import load_market_open_frame
    from factorlab.execution import load_market_open_snapshot
    import duckdb as _ddb

    db = _cal_db(tmp_path, [D0, D3])
    db.execute("INSERT INTO daily VALUES (?,?,?,?)",
               (D3.strftime("%Y%m%d"), "000001.SZ", 10.5, 10.0))
    db.execute("INSERT INTO stk_limit VALUES (?,?,?,?)",
               (D3.strftime("%Y%m%d"), "000001.SZ", 11.5, 9.5))
    db.close()
    cal = tmp_path / "c.duckdb"
    s = resolve_execution_schedule(_target(tmp_path, dates=[D0]), cal)
    assert s.frame["execution_date"][0] == D3
    snap = load_market_open_snapshot(cal, execution_date=D3,
                                     codes=["000001.SZ"])
    assert snap.execution_date == D3
    assert snap.frame["has_daily"][0] and snap.frame["open"][0] == 10.5
    assert snap.frame["has_limit"][0] and snap.frame["up_limit"][0] == 11.5
    assert snap.frame["has_suspend_record"][0] is False
