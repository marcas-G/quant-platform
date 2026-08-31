"""M7-01：TargetPortfolio / TargetPortfolioMeta 领域契约。"""

import datetime
from dataclasses import FrozenInstanceError

import polars as pl
import pytest

from factorlab.domain import TargetPortfolio, TargetPortfolioMeta
from factorlab.domain.timing import (DEFAULT_EOD_SIGNAL_TIMING, ExecutionTiming,
                                     InformationCutoff, SignalAvailability,
                                     SignalTiming)

D1, D2, D3 = (datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
              datetime.date(2024, 1, 4))


def _meta(gross: float = 1.0, **over):
    base = {"strategy_name": "momentum_top30", "source_signal_name": "m6_f2_ts_cs",
            "source_timing": DEFAULT_EOD_SIGNAL_TIMING, "gross_exposure": gross}
    base.update(over)
    return TargetPortfolioMeta(**base)


def _frame(rows=None, **over):
    base = {"decision_date": pl.Series([D1, D1, D2, D2], dtype=pl.Date),
            "code": pl.Series(["000001.SZ", "600000.SH", "000001.SZ", "600000.SH"],
                              dtype=pl.String),
            "target_weight": pl.Series([0.5, 0.5, 0.5, 0.5], dtype=pl.Float64)}
    base.update(over)
    if rows is not None:
        base = {k: v[:rows] if isinstance(v, pl.Series) else v for k, v in base.items()}
    return pl.DataFrame(base)


def _tp(frame=None, dates=None, gross=1.0, **meta_over):
    return TargetPortfolio(
        frame=_frame() if frame is None else frame,
        decision_dates=dates or (D1, D2),
        meta=_meta(gross, **meta_over),
    )


# ---------------- 正常路径 ----------------

def test_valid_one_date():
    f = pl.DataFrame({"decision_date": pl.Series([D1], dtype=pl.Date),
                      "code": pl.Series(["000001.SZ"], dtype=pl.String),
                      "target_weight": pl.Series([1.0], dtype=pl.Float64)})
    tp = TargetPortfolio(frame=f, decision_dates=(D1,), meta=_meta())
    assert tp.frame.height == 1


def test_valid_multi_date():
    tp = _tp()
    assert tp.frame.height == 4


def test_golden_all_cash_middle_date():
    """2024-01-02 positions、01-03 0 rows（显式 all-cash）、01-04 positions。"""
    f = pl.DataFrame({"decision_date": pl.Series([D1, D1, D3, D3], dtype=pl.Date),
                      "code": pl.Series(["000001.SZ", "600000.SH"] * 2, dtype=pl.String),
                      "target_weight": pl.Series([0.5, 0.5, 0.5, 0.5], dtype=pl.Float64)})
    tp = TargetPortfolio(frame=f, decision_dates=(D1, D2, D3), meta=_meta())
    assert tp.frame.filter(pl.col("decision_date") == D2).height == 0   # all-cash


def test_completely_empty():
    tp = TargetPortfolio(frame=pl.DataFrame(
        {"decision_date": pl.Series([], dtype=pl.Date),
         "code": pl.Series([], dtype=pl.String),
         "target_weight": pl.Series([], dtype=pl.Float64)}),
        decision_dates=(), meta=_meta())
    assert tp.frame.height == 0
    assert tp.frame.schema["decision_date"] == pl.Date
    assert tp.frame.schema["code"] == pl.String
    assert tp.frame.schema["target_weight"] == pl.Float64


def test_valid_partial_gross_0_8():
    f = pl.DataFrame({"decision_date": pl.Series([D1, D1], dtype=pl.Date),
                      "code": pl.Series(["000001.SZ", "600000.SH"], dtype=pl.String),
                      "target_weight": pl.Series([0.4, 0.4], dtype=pl.Float64)})
    tp = TargetPortfolio(frame=f, decision_dates=(D1,), meta=_meta(gross=0.8))
    assert tp.frame.height == 2


def test_signal_timing_exact_preservation():
    """SignalTiming 原样复用（枚举身份保持，不新建）。"""
    tp = _tp()
    st = tp.meta.source_timing
    assert st is DEFAULT_EOD_SIGNAL_TIMING
    assert st.information_cutoff is InformationCutoff.CLOSE
    assert st.available_at is SignalAvailability.AFTER_CLOSE
    assert st.default_earliest_execution is ExecutionTiming.NEXT_OPEN


# ---------------- schema / dtype ----------------

def test_missing_column_fails():
    f = _frame().drop("target_weight")
    with pytest.raises(ValueError):
        _tp(frame=f)


def test_extra_column_fails():
    with pytest.raises(ValueError):
        _tp(frame=_frame().with_columns(pl.lit(1.0).alias("signal")))


def test_decision_date_wrong_dtype():
    f = pl.DataFrame({"decision_date": pl.Series(["2024-01-02"], dtype=pl.String),
                      "code": pl.Series(["000001.SZ"], dtype=pl.String),
                      "target_weight": pl.Series([1.0], dtype=pl.Float64)})
    with pytest.raises(ValueError):
        _tp(frame=f)


def test_code_wrong_dtype():
    f = pl.DataFrame({"decision_date": pl.Series([D1], dtype=pl.Date),
                      "code": pl.Series([1], dtype=pl.Int64),
                      "target_weight": pl.Series([1.0], dtype=pl.Float64)})
    with pytest.raises(ValueError):
        _tp(frame=f)


def test_weight_float32_fails():
    f = _frame().with_columns(pl.col("target_weight").cast(pl.Float32))
    with pytest.raises(ValueError):
        _tp(frame=f)


def test_future_return_extra_column_fails():
    with pytest.raises(ValueError):
        _tp(frame=_frame().with_columns(pl.lit(0.01).alias("forward_return_5d")))


def test_label_extra_column_fails():
    with pytest.raises(ValueError):
        _tp(frame=_frame().with_columns(pl.lit(1.0).alias("label")))


# ---------------- key / code / weight ----------------

def test_duplicate_key_fails():
    f = _frame().with_columns(pl.col("decision_date").alias("decision_date")).vstack(_frame())
    with pytest.raises(ValueError, match="重复|unique"):
        _tp(frame=f)


def test_noncanonical_code_fails():
    f = _frame().with_columns(pl.lit("000001").alias("code"))
    with pytest.raises(ValueError):
        _tp(frame=f)


def test_alias_code_fails():
    f = _frame().with_columns(pl.lit("T600018.SH").alias("code"))
    with pytest.raises(ValueError):
        _tp(frame=f)


def test_cash_pseudo_code_fails():
    f = _frame().with_columns(pl.lit("CASH").alias("code"))
    with pytest.raises(ValueError):
        _tp(frame=f)


@pytest.mark.parametrize("bad_w", [0.0, -0.1, float("nan"), float("inf")])
def test_weight_invalid(bad_w):
    f = _frame().with_columns(pl.lit(bad_w).alias("target_weight"))
    with pytest.raises(ValueError):
        _tp(frame=f)


# ---------------- decision_dates ----------------

def test_unknown_frame_date_fails():
    f = _frame().with_columns(pl.lit(datetime.date(2024, 2, 1)).alias("decision_date"))
    with pytest.raises(ValueError):
        _tp(frame=f, dates=(D1, D2))


def test_decision_dates_duplicate_fails():
    with pytest.raises(ValueError):
        _tp(dates=(D1, D1))


def test_decision_dates_unsorted_fails():
    with pytest.raises(ValueError):
        _tp(dates=(D2, D1))


def test_datetime_datetime_fails():
    with pytest.raises(ValueError):
        _tp(dates=(datetime.datetime(2024, 1, 2), D2))


# ---------------- gross invariant / ordering ----------------

def test_gross_sum_mismatch_fails():
    """0.4+0.4=0.8 ≠ gross=1.0——fail fast，不 renormalize。"""
    f = _frame().with_columns(pl.lit(0.4).alias("target_weight"))
    with pytest.raises(ValueError, match="gross"):
        _tp(frame=f)


def test_frame_unsorted_fails():
    f = _frame().sort(["decision_date", "code"], descending=[True, False])
    with pytest.raises(ValueError, match="排序"):
        _tp(frame=f)


# ---------------- frozen ----------------

def test_frozen_meta():
    m = _meta()
    with pytest.raises(FrozenInstanceError):
        m.strategy_name = "x"


def test_frozen_portfolio():
    tp = _tp()
    with pytest.raises(FrozenInstanceError):
        tp.decision_dates = (D3,)


# ---------------- meta validation ----------------

def test_meta_invalid_frequency():
    with pytest.raises(ValueError):
        _meta(frequency="5d")


def test_meta_empty_strategy_name():
    with pytest.raises(ValueError):
        _meta(strategy_name="")


def test_meta_invalid_gross():
    with pytest.raises(ValueError):
        _meta(gross=1.5)


# ================================================================
# M7-03：TargetPortfolioMeta.rebalance_frequency
# ================================================================

@pytest.mark.parametrize("freq", ["daily", "weekly", "monthly"])
def test_meta_rebalance_frequency_valid(freq):
    m = _meta(rebalance_frequency=freq)
    assert m.rebalance_frequency == freq


@pytest.mark.parametrize("bad", ["5d", "quarterly", "biweekly"])
def test_meta_rebalance_frequency_invalid(bad):
    with pytest.raises(ValueError):
        _meta(rebalance_frequency=bad)


def test_meta_default_rebalance_daily():
    assert _meta().rebalance_frequency == "daily"
