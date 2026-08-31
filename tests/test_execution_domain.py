"""M8-01：Execution Domain——PortfolioState / OrderBatch / OrderSide / Phase。"""

import datetime
from dataclasses import FrozenInstanceError

import polars as pl
import pytest

from factorlab.domain import (OrderBatch, OrderSide, PortfolioState,
                              PortfolioStatePhase)
from factorlab.domain.timing import ExecutionTiming

D1, D2 = datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)


def _state(frame=None, cash=1_000_000.0, date=D1,
           phase=PortfolioStatePhase.PRE_EXECUTION):
    return PortfolioState(
        as_of_date=date, phase=phase, cash=cash,
        positions=_positions() if frame is None else frame)


def _positions():
    return pl.DataFrame({
        "code": pl.Series(["000001.SZ", "600000.SH"], dtype=pl.String),
        "quantity": pl.Series([100, 200], dtype=pl.Int64),
        "sellable_quantity": pl.Series([100, 0], dtype=pl.Int64),
    })


def _empty_positions():
    return pl.DataFrame({"code": pl.Series([], dtype=pl.String),
                         "quantity": pl.Series([], dtype=pl.Int64),
                         "sellable_quantity": pl.Series([], dtype=pl.Int64)})


def _orders():
    return pl.DataFrame({
        "code": pl.Series(["000001.SZ", "600000.SH"], dtype=pl.String),
        "side": pl.Series(["buy", "sell"], dtype=pl.String),
        "quantity": pl.Series([100, 200], dtype=pl.Int64),
    })


def _batch(orders=None, decision=D1, execution=D2,
           timing=ExecutionTiming.NEXT_OPEN):
    return OrderBatch(decision_date=decision, execution_date=execution,
                      execution_timing=timing,
                      orders=_orders() if orders is None else orders)


# ================================================================
# PortfolioState
# ================================================================

def test_cash_only_state_valid():
    s = PortfolioState(as_of_date=D1, phase=PortfolioStatePhase.PRE_EXECUTION,
                       cash=1_000_000.0, positions=_empty_positions())
    assert s.positions.height == 0
    assert s.positions.schema["code"] == pl.String
    assert s.positions.schema["quantity"] == pl.Int64
    assert s.positions.schema["sellable_quantity"] == pl.Int64


def test_one_position_valid():
    p = pl.DataFrame({"code": pl.Series(["000001.SZ"], dtype=pl.String),
                      "quantity": pl.Series([100], dtype=pl.Int64),
                      "sellable_quantity": pl.Series([100], dtype=pl.Int64)})
    s = PortfolioState(as_of_date=D1, phase=PortfolioStatePhase.PRE_EXECUTION,
                       cash=0.0, positions=p)
    assert s.positions.height == 1


def test_multi_position_valid():
    s = _state()
    assert s.positions.height == 2


def test_position_schema_exact():
    s = _state()
    assert s.positions.columns == ["code", "quantity", "sellable_quantity"]


def test_missing_column_fails():
    with pytest.raises(ValueError):
        _state(frame=_positions().drop("quantity"))


def test_extra_column_fails():
    with pytest.raises(ValueError):
        _state(frame=_positions().with_columns(pl.lit(1.0).alias("weight")))


def test_code_wrong_dtype_fails():
    p = pl.DataFrame({"code": pl.Series([1], dtype=pl.Int64),
                      "quantity": pl.Series([100], dtype=pl.Int64),
                      "sellable_quantity": pl.Series([100], dtype=pl.Int64)})
    with pytest.raises(ValueError):
        _state(frame=p)


def test_quantity_wrong_dtype_fails():
    p = _positions().with_columns(pl.col("quantity").cast(pl.Float64))
    with pytest.raises(ValueError):
        _state(frame=p)


def test_sellable_wrong_dtype_fails():
    p = _positions().with_columns(pl.col("sellable_quantity").cast(pl.Int32))
    with pytest.raises(ValueError):
        _state(frame=p)


def test_duplicate_code_fails():
    p = _positions().vstack(_positions().head(1))
    with pytest.raises(ValueError, match="重复|unique"):
        _state(frame=p)


def test_noncanonical_code_fails():
    p = _positions().with_columns(pl.lit("000001").alias("code"))
    with pytest.raises(ValueError):
        _state(frame=p)


def test_alias_code_fails():
    p = _positions().with_columns(pl.lit("T600018.SH").alias("code"))
    with pytest.raises(ValueError):
        _state(frame=p)


def test_quantity_zero_fails():
    p = _positions().with_columns(pl.lit(0).alias("quantity"))
    with pytest.raises(ValueError):
        _state(frame=p)


def test_quantity_negative_fails():
    p = _positions().with_columns(pl.lit(-100).alias("quantity"))
    with pytest.raises(ValueError):
        _state(frame=p)


def test_sellable_zero_valid():
    p = _positions().with_columns(pl.lit(0, dtype=pl.Int64).alias("sellable_quantity"))
    s = _state(frame=p)
    assert s.positions.height == 2


def test_sellable_negative_fails():
    p = _positions().with_columns(pl.lit(-1).alias("sellable_quantity"))
    with pytest.raises(ValueError):
        _state(frame=p)


def test_sellable_exceeds_quantity_fails():
    p = _positions().with_columns(pl.lit(9999).alias("sellable_quantity"))
    with pytest.raises(ValueError):
        _state(frame=p)


def test_cash_zero_valid():
    s = PortfolioState(as_of_date=D1, phase=PortfolioStatePhase.PRE_EXECUTION,
                       cash=0.0, positions=_positions())
    assert s.cash == 0.0


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), -float("inf"), True])
def test_cash_invalid(bad):
    with pytest.raises(ValueError):
        _state(cash=bad)


def test_as_of_datetime_fails():
    with pytest.raises(ValueError):
        _state(date=datetime.datetime(2024, 1, 2))


def test_as_of_string_fails():
    with pytest.raises(ValueError):
        _state(date="2024-01-02")


def test_unsorted_positions_fails():
    p = _positions().sort("code", descending=True)
    with pytest.raises(ValueError, match="排序"):
        _state(frame=p)


def test_frozen_state():
    s = _state()
    with pytest.raises(FrozenInstanceError):
        s.cash = 0.0


def test_pre_execution_valid():
    assert _state(phase=PortfolioStatePhase.PRE_EXECUTION).phase == \
        PortfolioStatePhase.PRE_EXECUTION


def test_post_execution_valid():
    assert _state(phase=PortfolioStatePhase.POST_EXECUTION).phase == \
        PortfolioStatePhase.POST_EXECUTION


def test_invalid_phase_type_fails():
    with pytest.raises(ValueError):
        _state(phase="pre_execution")


def test_no_zero_quantity_rows_in_sparse():
    """positions 是 sparse——0 quantity 行不存在（validator 拒绝，不清理）。"""
    p = _positions().with_columns(pl.lit(0).alias("quantity"))
    with pytest.raises(ValueError):
        _state(frame=p)


# ================================================================
# OrderBatch
# ================================================================

def test_valid_buy():
    o = pl.DataFrame({"code": pl.Series(["000001.SZ"], dtype=pl.String),
                      "side": pl.Series(["buy"], dtype=pl.String),
                      "quantity": pl.Series([100], dtype=pl.Int64)})
    b = _batch(orders=o)
    assert b.orders.height == 1
    assert b.orders["side"][0] == "buy"


def test_valid_sell():
    o = pl.DataFrame({"code": pl.Series(["000001.SZ"], dtype=pl.String),
                      "side": pl.Series(["sell"], dtype=pl.String),
                      "quantity": pl.Series([100], dtype=pl.Int64)})
    assert _batch(orders=o).orders["side"][0] == "sell"


def test_multi_order_valid():
    b = _batch()
    assert b.orders.height == 2


def test_empty_batch_valid():
    o = pl.DataFrame({"code": pl.Series([], dtype=pl.String),
                      "side": pl.Series([], dtype=pl.String),
                      "quantity": pl.Series([], dtype=pl.Int64)})
    b = _batch(orders=o)
    assert b.orders.height == 0
    assert b.orders.schema["code"] == pl.String
    assert b.orders.schema["side"] == pl.String
    assert b.orders.schema["quantity"] == pl.Int64


def test_exact_schema():
    b = _batch()
    assert b.orders.columns == ["code", "side", "quantity"]


def test_decision_date_strict():
    with pytest.raises(ValueError):
        _batch(decision=datetime.datetime(2024, 1, 2))


def test_execution_date_strict():
    with pytest.raises(ValueError):
        _batch(execution=datetime.datetime(2024, 1, 3))


def test_execution_greater_than_decision():
    assert _batch().execution_date > _batch().decision_date


def test_same_date_fails():
    with pytest.raises(ValueError):
        _batch(decision=D1, execution=D1)


def test_earlier_execution_fails():
    with pytest.raises(ValueError):
        _batch(decision=D2, execution=D1)


def test_next_open_valid():
    assert _batch(timing=ExecutionTiming.NEXT_OPEN).execution_timing == \
        ExecutionTiming.NEXT_OPEN


def test_next_close_valid():
    assert _batch(timing=ExecutionTiming.NEXT_CLOSE).execution_timing == \
        ExecutionTiming.NEXT_CLOSE


def test_wrong_timing_type_fails():
    with pytest.raises(ValueError):
        _batch(timing="next_open")


def test_missing_column_fails():
    with pytest.raises(ValueError):
        _batch(orders=_orders().drop("side"))


def test_extra_target_weight_fails():
    with pytest.raises(ValueError):
        _batch(orders=_orders().with_columns(pl.lit(0.5).alias("target_weight")))


def test_extra_fill_price_fails():
    with pytest.raises(ValueError):
        _batch(orders=_orders().with_columns(pl.lit(10.0).alias("fill_price")))


def test_code_wrong_dtype_fails():
    o = pl.DataFrame({"code": pl.Series([1], dtype=pl.Int64),
                      "side": pl.Series(["buy"], dtype=pl.String),
                      "quantity": pl.Series([100], dtype=pl.Int64)})
    with pytest.raises(ValueError):
        _batch(orders=o)


def test_side_wrong_dtype_fails():
    o = _orders().with_columns(pl.col("side").cast(pl.Categorical))
    with pytest.raises(ValueError):
        _batch(orders=o)


def test_quantity_wrong_dtype_fails():
    o = _orders().with_columns(pl.col("quantity").cast(pl.Float64))
    with pytest.raises(ValueError):
        _batch(orders=o)


def test_noncanonical_code_fails():
    o = _orders().with_columns(pl.lit("CASH").alias("code"))
    with pytest.raises(ValueError):
        _batch(orders=o)


def test_duplicate_code_fails():
    o = _orders().vstack(_orders().head(1))
    with pytest.raises(ValueError, match="重复|unique"):
        _batch(orders=o)


def test_buy_uppercase_fails():
    o = pl.DataFrame({"code": pl.Series(["000001.SZ"], dtype=pl.String),
                      "side": pl.Series(["BUY"], dtype=pl.String),
                      "quantity": pl.Series([100], dtype=pl.Int64)})
    with pytest.raises(ValueError):
        _batch(orders=o)


@pytest.mark.parametrize("bad_side", ["long", "short", "cover", None, ""])
def test_invalid_side_fails(bad_side):
    o = pl.DataFrame({"code": pl.Series(["000001.SZ"], dtype=pl.String),
                      "side": pl.Series([bad_side], dtype=pl.String),
                      "quantity": pl.Series([100], dtype=pl.Int64)})
    with pytest.raises(ValueError):
        _batch(orders=o)


def test_quantity_zero_fails():
    o = _orders().with_columns(pl.lit(0).alias("quantity"))
    with pytest.raises(ValueError):
        _batch(orders=o)


def test_quantity_negative_fails():
    o = _orders().with_columns(pl.lit(-100).alias("quantity"))
    with pytest.raises(ValueError):
        _batch(orders=o)


def test_unsorted_orders_fails():
    o = _orders().sort("code", descending=True)
    with pytest.raises(ValueError, match="排序"):
        _batch(orders=o)


def test_frozen_batch():
    b = _batch()
    with pytest.raises(FrozenInstanceError):
        b.execution_date = D2


def test_buy_sell_same_code_duplicate_fails():
    o = pl.DataFrame({"code": pl.Series(["000001.SZ", "000001.SZ"], dtype=pl.String),
                      "side": pl.Series(["buy", "sell"], dtype=pl.String),
                      "quantity": pl.Series([100, 100], dtype=pl.Int64)})
    with pytest.raises(ValueError, match="重复|unique"):
        _batch(orders=o)


def test_no_price_cost_fields():
    b = _batch()
    cols = b.orders.columns
    assert "fill_price" not in cols and "commission" not in cols
    assert "limit_price" not in cols and "expected_price" not in cols
