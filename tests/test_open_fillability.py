"""M8-04B：conservative open fillability kernel——OrderBatch → OpenFillAssessment。

只回答 market eligibility（FILLABLE / BLOCKED_*）；不回答实际成交/现金/数量。
数据异常（missing/invalid execution evidence）→ ExecutionDataQualityError，
整个 event fail fast（DATA UNKNOWN ≠ TRADE REJECTED）。
"""

import datetime
import math

import polars as pl
import pytest

from factorlab.domain import (ExecutionDataQualityError, ExecutionSchedule,
                              MarketOpenSnapshot, OpenFillAssessment,
                              OpenOrderDisposition, OrderBatch, OrderSide,
                              PortfolioStatePhase)
from factorlab.domain.timing import ExecutionTiming
from factorlab.execution import assess_open_fillability

D1 = datetime.date(2024, 1, 2)
E1 = datetime.date(2024, 1, 3)

FILLABLE = OpenOrderDisposition.FILLABLE
BLOCK_S = OpenOrderDisposition.BLOCKED_SUSPENSION
BLOCK_U = OpenOrderDisposition.BLOCKED_LIMIT_UP
BLOCK_D = OpenOrderDisposition.BLOCKED_LIMIT_DOWN


# ---------------- fixture builders ----------------

def _orders(rows, decision=D1, exec_date=E1, timing=ExecutionTiming.NEXT_OPEN):
    frame = pl.DataFrame(rows, schema=["code", "side", "quantity"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("side").cast(pl.String),
                               pl.col("quantity").cast(pl.Int64))
    if frame.height:
        frame = frame.sort("code")
    return OrderBatch(decision_date=decision, execution_date=exec_date,
                      execution_timing=timing, orders=frame)


def _snap(rows, exec_date=E1):
    """rows: (code, open, pre_close, up, dn, has_daily, has_limit,
    has_suspend, is_suspended_at_open)。"""
    frame = pl.DataFrame(rows, schema=["code", "open", "pre_close", "up_limit",
                                       "down_limit", "has_daily", "has_limit",
                                       "has_suspend_record",
                                       "is_suspended_at_open"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("open").cast(pl.Float64),
                               pl.col("pre_close").cast(pl.Float64),
                               pl.col("up_limit").cast(pl.Float64),
                               pl.col("down_limit").cast(pl.Float64),
                               pl.col("has_daily").cast(pl.Boolean),
                               pl.col("has_limit").cast(pl.Boolean),
                               pl.col("has_suspend_record").cast(pl.Boolean),
                               pl.col("is_suspended_at_open").cast(pl.Boolean))
    frame = frame.sort("code")
    return MarketOpenSnapshot(execution_date=exec_date, frame=frame)


def _normal_row(code="000001.SZ", open_=10.0, up=11.0, dn=9.0, suspend=False):
    return (code, open_, open_ - 0.2, up, dn, True, True, suspend, suspend)


def _assess(orders=None, snapshot=None):
    o = orders if orders is not None else _orders([("000001.SZ", "buy", 1000)])
    s = snapshot if snapshot is not None else _snap([_normal_row()])
    return assess_open_fillability(o, s)


def _disp(assessment, code):
    f = assessment.frame.filter(pl.col("code") == code)
    if f.height == 0:
        return None
    return f["disposition"][0], f["fillable_price"][0]


# ================================================================
# AC-01/02：ExecutionDataQualityError
# ================================================================

def test_data_quality_error_exists():
    assert issubclass(ExecutionDataQualityError, ValueError)


# ================================================================
# AC-06/07：OpenOrderDisposition
# ================================================================

def test_disposition_exactly_four_values():
    assert set(OpenOrderDisposition) == {FILLABLE, BLOCK_S, BLOCK_U, BLOCK_D}
    assert FILLABLE.value == "fillable"
    assert BLOCK_S.value == "blocked_suspension"
    assert BLOCK_U.value == "blocked_limit_up"
    assert BLOCK_D.value == "blocked_limit_down"


def test_invalid_disposition_value_fails():
    for bad in ("filled", "blocked", "unknown", "suspend", "limit", "partial"):
        with pytest.raises(ValueError):
            OpenOrderDisposition(bad)


# ================================================================
# AC-08..18：OpenFillAssessment domain
# ================================================================

def _mk_assessment(rows, decision=D1, exec_date=E1):
    frame = pl.DataFrame(rows, schema=["code", "side", "quantity", "disposition",
                                       "fillable_price"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("side").cast(pl.String),
                               pl.col("quantity").cast(pl.Int64),
                               pl.col("disposition").cast(pl.String),
                               pl.col("fillable_price").cast(pl.Float64))
    return OpenFillAssessment(decision_date=decision, execution_date=exec_date,
                              execution_timing=ExecutionTiming.NEXT_OPEN,
                              frame=frame)


def test_assessment_exact_schema():
    a = _mk_assessment([("000001.SZ", "buy", 1000, "fillable", 10.0)])
    assert a.frame.columns == ["code", "side", "quantity", "disposition",
                               "fillable_price"]
    assert a.frame.schema["code"] == pl.String
    assert a.frame.schema["side"] == pl.String
    assert a.frame.schema["quantity"] == pl.Int64
    assert a.frame.schema["disposition"] == pl.String
    assert a.frame.schema["fillable_price"] == pl.Float64


def test_assessment_wrong_column_order_fails():
    bad = pl.DataFrame({"code": ["000001.SZ"], "side": ["buy"], "quantity": [1],
                        "fillable_price": [10.0], "disposition": ["fillable"]})
    with pytest.raises(ValueError):
        OpenFillAssessment(decision_date=D1, execution_date=E1,
                           execution_timing=ExecutionTiming.NEXT_OPEN, frame=bad)


def test_assessment_missing_column_fails():
    frame = _mk_assessment([("000001.SZ", "buy", 1000, "fillable", 10.0)]
                           ).frame.drop("disposition")
    with pytest.raises(ValueError):
        OpenFillAssessment(decision_date=D1, execution_date=E1,
                           execution_timing=ExecutionTiming.NEXT_OPEN, frame=frame)


def test_assessment_extra_column_fails():
    frame = _mk_assessment([("000001.SZ", "buy", 1000, "fillable", 10.0)]
                           ).frame.with_columns(pl.lit(1.0).alias("filled_qty"))
    with pytest.raises(ValueError):
        OpenFillAssessment(decision_date=D1, execution_date=E1,
                           execution_timing=ExecutionTiming.NEXT_OPEN, frame=frame)


@pytest.mark.parametrize("col,dtype", [("quantity", pl.Float64),
                                       ("disposition", pl.Int64),
                                       ("fillable_price", pl.Int64)])
def test_assessment_wrong_dtype_fails(col, dtype):
    frame = _mk_assessment([("000001.SZ", "buy", 1000, "fillable", 10.0)]).frame
    frame = frame.with_columns(pl.Series([0]).cast(dtype).alias(col))
    with pytest.raises(ValueError):
        OpenFillAssessment(decision_date=D1, execution_date=E1,
                           execution_timing=ExecutionTiming.NEXT_OPEN, frame=frame)


@pytest.mark.parametrize("bad", ["blocked", "unknown", "filled", "suspend",
                                 "limit", "buy", "sell", "null"])
def test_assessment_invalid_disposition_fails(bad):
    with pytest.raises(ValueError, match="disposition"):
        _mk_assessment([("000001.SZ", "buy", 1000, bad, 10.0)])


def test_assessment_all_four_dispositions_valid():
    for disp in ("fillable", "blocked_suspension", "blocked_limit_up",
                 "blocked_limit_down"):
        price = 10.0 if disp == "fillable" else None
        a = _mk_assessment([("000001.SZ", "buy", 1000, disp, price)])
        assert a.frame.height == 1


def test_fillable_requires_valid_price():
    _mk_assessment([("000001.SZ", "buy", 1000, "fillable", 10.0)])
    for bad in (None, 0.0, -1.0, math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="fillable_price"):
            _mk_assessment([("000001.SZ", "buy", 1000, "fillable", bad)])


def test_blocked_requires_null_price():
    for disp in ("blocked_suspension", "blocked_limit_up", "blocked_limit_down"):
        _mk_assessment([("000001.SZ", "buy", 1000, disp, None)])
        with pytest.raises(ValueError, match="fillable_price"):
            _mk_assessment([("000001.SZ", "buy", 1000, disp, 10.0)])


def test_assessment_quantity_must_be_positive():
    with pytest.raises(ValueError):
        _mk_assessment([("000001.SZ", "buy", 0, "fillable", 10.0)])
    with pytest.raises(ValueError):
        _mk_assessment([("000001.SZ", "buy", -5, "fillable", 10.0)])


@pytest.mark.parametrize("bad_side", ["BUY", "SELL", "long", "short", None])
def test_assessment_side_restricted(bad_side):
    with pytest.raises(ValueError):
        _mk_assessment([("000001.SZ", bad_side, 1000, "fillable", 10.0)])


def test_assessment_code_canonical_unique_sorted():
    with pytest.raises(ValueError):
        _mk_assessment([("000001", "buy", 1000, "fillable", 10.0)])
    with pytest.raises(ValueError):
        _mk_assessment([("000001.SZ", "buy", 1000, "fillable", 10.0),
                        ("000001.SZ", "sell", 500, "fillable", 10.0)])
    with pytest.raises(ValueError):
        _mk_assessment([("600000.SH", "buy", 1000, "fillable", 10.0),
                        ("000001.SZ", "buy", 1000, "fillable", 10.0)])


def test_assessment_meta_date_types():
    a = _mk_assessment([("000001.SZ", "buy", 1000, "fillable", 10.0)])
    assert a.decision_date == D1 and a.execution_date == E1
    assert a.execution_timing is ExecutionTiming.NEXT_OPEN


def test_assessment_empty_frame_valid():
    frame = pl.DataFrame({"code": pl.Series([], dtype=pl.String),
                          "side": pl.Series([], dtype=pl.String),
                          "quantity": pl.Series([], dtype=pl.Int64),
                          "disposition": pl.Series([], dtype=pl.String),
                          "fillable_price": pl.Series([], dtype=pl.Float64)})
    a = OpenFillAssessment(decision_date=D1, execution_date=E1,
                           execution_timing=ExecutionTiming.NEXT_OPEN, frame=frame)
    assert a.frame.height == 0


# ================================================================
# AC-18..27：API / type guards / cross-object
# ================================================================

def test_api_exists():
    assert callable(assess_open_fillability)


def test_type_guards():
    with pytest.raises(TypeError, match="orders"):
        assess_open_fillability({"frame": None}, _snap([_normal_row()]))
    with pytest.raises(TypeError, match="snapshot"):
        assess_open_fillability(_orders([("000001.SZ", "buy", 100)]), None)


def test_no_portfolio_state_parameter():
    import inspect
    assert "state" not in inspect.signature(assess_open_fillability).parameters
    assert "db" not in inspect.signature(assess_open_fillability).parameters
    assert "rules" not in inspect.signature(assess_open_fillability).parameters


def test_execution_date_alignment():
    with pytest.raises(ValueError, match="execution_date"):
        _assess(snapshot=_snap([_normal_row()], exec_date=datetime.date(2024, 1, 4)))


def test_next_open_supported():
    a = _assess()
    assert a.execution_timing is ExecutionTiming.NEXT_OPEN


def test_next_close_not_implemented():
    o = _orders([("000001.SZ", "buy", 100)], timing=ExecutionTiming.NEXT_CLOSE)
    with pytest.raises(NotImplementedError, match="next_close|NEXT_CLOSE"):
        _assess(orders=o)


def test_order_codes_subset_snapshot():
    o = _orders([("000001.SZ", "buy", 100), ("600000.SH", "sell", 200)])
    s = _snap([_normal_row("000001.SZ"), _normal_row("600000.SH"),
               _normal_row("601111.SH")])
    a = assess_open_fillability(o, s)
    assert a.frame.height == 2


def test_missing_order_code_fails():
    o = _orders([("000001.SZ", "buy", 100), ("601111.SH", "buy", 200)])
    s = _snap([_normal_row("000001.SZ")])
    with pytest.raises(ValueError, match="601111|snapshot|coverage"):
        assess_open_fillability(o, s)


def test_extra_snapshot_codes_ignored():
    o = _orders([("000001.SZ", "buy", 100)])
    s = _snap([_normal_row("000001.SZ"), _normal_row("601111.SH")])
    a = assess_open_fillability(o, s)
    assert a.frame.height == 1
    assert _disp(a, "000001.SZ") == ("fillable", 10.0)


def test_empty_order_batch():
    o = _orders([])
    s = _snap([_normal_row()])
    a = assess_open_fillability(o, s)
    assert a.frame.height == 0
    assert a.decision_date == D1 and a.execution_date == E1
    assert a.execution_timing is ExecutionTiming.NEXT_OPEN


def test_empty_batch_still_checks_alignment():
    o = _orders([])
    s = _snap([_normal_row()], exec_date=datetime.date(2024, 1, 4))
    with pytest.raises(ValueError, match="execution_date"):
        assess_open_fillability(o, s)


# ================================================================
# AC-28..45：核心判定
# ================================================================

def test_normal_buy_fillable():
    a = _assess(_orders([("000001.SZ", "buy", 1000)]))
    assert _disp(a, "000001.SZ") == ("fillable", 10.0)


def test_normal_sell_fillable():
    a = _assess(_orders([("000001.SZ", "sell", 1000)]))
    assert _disp(a, "000001.SZ") == ("fillable", 10.0)


def test_buy_at_upper_blocked():
    s = _snap([_normal_row(open_=11.0, up=11.0)])
    a = _assess(_orders([("000001.SZ", "buy", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("blocked_limit_up", None)


def test_sell_at_lower_blocked():
    s = _snap([_normal_row(open_=9.0, dn=9.0)])
    a = _assess(_orders([("000001.SZ", "sell", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("blocked_limit_down", None)


def test_sell_at_upper_fillable():
    s = _snap([_normal_row(open_=11.0, up=11.0)])
    a = _assess(_orders([("000001.SZ", "sell", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("fillable", 11.0)


def test_buy_at_lower_fillable():
    s = _snap([_normal_row(open_=9.0, dn=9.0)])
    a = _assess(_orders([("000001.SZ", "buy", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("fillable", 9.0)


def test_interior_buy_and_sell():
    for side in ("buy", "sell"):
        a = _assess(_orders([("000001.SZ", side, 1000)]))
        assert _disp(a, "000001.SZ") == ("fillable", 10.0)


def test_limits_equal_side_specific():
    """down == up == open：BUY→blocked_up、SELL→blocked_down（不新增第五类）。"""
    s = _snap([_normal_row(open_=10.0, up=10.0, dn=10.0)])
    a = _assess(_orders([("000001.SZ", "buy", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("blocked_limit_up", None)
    a = _assess(_orders([("000001.SZ", "sell", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("blocked_limit_down", None)


def test_suspended_buy_blocked():
    s = _snap([_normal_row(suspend=True)])
    a = _assess(_orders([("000001.SZ", "buy", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("blocked_suspension", None)


def test_suspended_sell_blocked():
    s = _snap([_normal_row(suspend=True)])
    a = _assess(_orders([("000001.SZ", "sell", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("blocked_suspension", None)


def test_suspended_no_daily_no_limit_allowed():
    """suspended + has_daily=False + has_limit=False → blocked（不触发缺证据）。"""
    s = _snap([("000001.SZ", None, None, None, None, False, False, True, True)])
    a = _assess(_orders([("000001.SZ", "buy", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("blocked_suspension", None)


def test_suspension_beats_limit():
    s = _snap([_normal_row(open_=11.0, up=11.0, suspend=True)])
    a = _assess(_orders([("000001.SZ", "buy", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("blocked_suspension", None)


def test_non_suspended_missing_daily_data_quality_error():
    s = _snap([("000001.SZ", None, None, 11.0, 9.0, False, True, False, False)])
    with pytest.raises(ExecutionDataQualityError, match="open price|daily"):
        _assess(snapshot=s)


def test_non_suspended_missing_limit_data_quality_error():
    s = _snap([("000001.SZ", 10.0, 9.8, None, None, True, False, False, False)])
    with pytest.raises(ExecutionDataQualityError, match="limit"):
        _assess(snapshot=s)


def test_open_above_upper_data_quality_error():
    s = _snap([_normal_row(open_=11.01, up=11.0)])
    with pytest.raises(ExecutionDataQualityError, match="outside|up_limit|limit"):
        _assess(snapshot=s)


def test_open_below_lower_data_quality_error():
    s = _snap([_normal_row(open_=8.99, dn=9.0)])
    with pytest.raises(ExecutionDataQualityError, match="outside|down_limit|limit"):
        _assess(snapshot=s)


def test_no_tolerance_nextafter_regression():
    """open = nextafter(up, +inf) → 仍 DataQualityError（raw 比较，不 isclose）。"""
    up = 11.0
    just_above = math.nextafter(up, math.inf)
    s = _snap([_normal_row(open_=just_above, up=up)])
    with pytest.raises(ExecutionDataQualityError):
        _assess(snapshot=s)
    # 另一端
    dn = 9.0
    just_below = math.nextafter(dn, -math.inf)
    s = _snap([_normal_row(open_=just_below, dn=dn)])
    with pytest.raises(ExecutionDataQualityError):
        _assess(snapshot=s)


def test_exact_equality_is_limit_not_error():
    s = _snap([_normal_row(open_=11.0, up=11.0)])
    a = _assess(_orders([("000001.SZ", "buy", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ")[0] == "blocked_limit_up"


def test_fillable_price_equals_raw_open():
    s = _snap([_normal_row(open_=10.5, up=11.0, dn=9.0)])
    a = _assess(_orders([("000001.SZ", "buy", 1000)]), snapshot=s)
    assert _disp(a, "000001.SZ") == ("fillable", 10.5)


# ================================================================
# AC-46..57：输出契约
# ================================================================

def test_order_identity_preserved():
    o = _orders([("000001.SZ", "buy", 1000), ("600000.SH", "sell", 200),
                 ("688001.SH", "buy", 300)])
    s = _snap([_normal_row("000001.SZ"), _normal_row("600000.SH", open_=9.0, dn=9.0),
               _normal_row("688001.SH", suspend=True)])
    a = assess_open_fillability(o, s)
    assert a.frame.select(["code", "side", "quantity"]).equals(o.orders)
    assert a.frame.height == o.orders.height == 3
    assert a.frame["code"].to_list() == ["000001.SZ", "600000.SH", "688001.SH"]


def test_assessment_sorted_code_asc():
    o = _orders([("688001.SH", "buy", 300), ("000001.SZ", "buy", 1000)])
    s = _snap([_normal_row("000001.SZ"), _normal_row("688001.SH")])
    a = _assess(orders=o, snapshot=s)
    assert a.frame["code"].to_list() == ["000001.SZ", "688001.SH"]


def test_assessment_does_not_mutate_inputs():
    o = _orders([("000001.SZ", "buy", 1000)])
    s = _snap([_normal_row()])
    o_before = o.orders.clone()
    s_before = s.frame.clone()
    assess_open_fillability(o, s)
    assert o.orders.equals(o_before)
    assert s.frame.equals(s_before)


def test_data_quality_error_caught_by_value_error():
    s = _snap([("000001.SZ", None, None, 11.0, 9.0, False, True, False, False)])
    with pytest.raises(ValueError):
        _assess(snapshot=s)


def test_structural_error_is_not_data_quality_error():
    """wrong columns → ValueError 且非 DataQualityError。"""
    bad = pl.DataFrame({"x": [1]})
    with pytest.raises(ValueError) as ei:
        MarketOpenSnapshot(execution_date=E1, frame=bad)
    assert not isinstance(ei.value, ExecutionDataQualityError)
