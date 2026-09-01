"""M8-05B：point-in-time portfolio valuation——PortfolioState + explicit marks
→ PortfolioValuation。

- marks 是 caller 提供的显式 per-share valuation mark authority（与
  PortfolioState.quantity 同一 share-unit basis；kernel 不负责 price
  sourcing / stale-price / corporate-action）
- exact coverage：one position ↔ one explicit mark（missing/extra fail）
- 资产所有权基于 quantity（sellable_quantity 不参与估值）
- NAV = cash + Σ(quantity × mark_price)——货币金额，不是 normalized index
"""

import datetime
import inspect
import math
import re

import polars as pl
import pytest

from factorlab.domain import (PortfolioMarkSnapshot, PortfolioState,
                              PortfolioStatePhase, PortfolioValuation)
from factorlab.execution import value_portfolio

E1 = datetime.date(2024, 1, 3)


# ================================================================
# AC-35..48：PortfolioMarkSnapshot domain
# ================================================================

def _marks(rows, as_of=E1):
    frame = pl.DataFrame(rows, schema=["code", "mark_price"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("mark_price").cast(pl.Float64))
    if frame.height:
        frame = frame.sort("code")
    return PortfolioMarkSnapshot(as_of_date=as_of, frame=frame)


def test_mark_schema_and_dtypes():
    m = _marks([("000001.SZ", 10.0)])
    assert m.frame.columns == ["code", "mark_price"]
    assert m.frame.schema["code"] == pl.String
    assert m.frame.schema["mark_price"] == pl.Float64
    assert m.as_of_date == E1


def test_mark_validation():
    with pytest.raises(ValueError):
        _marks([("000001", 10.0)])                 # 非 canonical
    with pytest.raises(ValueError):
        _marks([("000001.SZ", 10.0), ("000001.SZ", 11.0)])   # 重复
    # 乱序（绕过 helper 的预排序——直接构造）
    unsorted = pl.DataFrame([("600000.SH", 10.0), ("000001.SZ", 11.0)],
                            schema=["code", "mark_price"], orient="row")
    unsorted = unsorted.with_columns(pl.col("code").cast(pl.String),
                                     pl.col("mark_price").cast(pl.Float64))
    with pytest.raises(ValueError):
        PortfolioMarkSnapshot(as_of_date=E1, frame=unsorted)
    for bad in (0.0, -1.0, math.nan, math.inf, -math.inf, None):
        with pytest.raises(ValueError):
            _marks([("000001.SZ", bad)])


def test_mark_typed_empty():
    m = _marks([])
    assert m.frame.height == 0
    assert m.frame.schema["code"] == pl.String
    assert m.frame.schema["mark_price"] == pl.Float64


def test_mark_strict_date():
    with pytest.raises(ValueError):
        _marks([], as_of="2024-01-03")


# ================================================================
# AC-49..66：PortfolioValuation domain
# ================================================================

def _valuation(frame_rows, cash=0.0, phase=PortfolioStatePhase.PRE_EXECUTION):
    frame = pl.DataFrame(frame_rows, schema=["code", "quantity", "mark_price",
                                             "market_value"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("quantity").cast(pl.Int64),
                               pl.col("mark_price").cast(pl.Float64),
                               pl.col("market_value").cast(pl.Float64))
    if frame.height:
        frame = frame.sort("code")
    mv = frame["market_value"].sum() if frame.height else 0.0
    return PortfolioValuation(as_of_date=E1, phase=phase, cash=cash,
                              market_value=mv, nav=cash + mv, frame=frame)


def test_valuation_domain_fields():
    v = _valuation([("000001.SZ", 100, 10.0, 1000.0)], cash=500.0)
    assert v.as_of_date == E1
    assert v.phase is PortfolioStatePhase.PRE_EXECUTION
    assert v.cash == 500.0 and v.market_value == 1000.0 and v.nav == 1500.0


def test_valuation_frame_schema():
    v = _valuation([("000001.SZ", 100, 10.0, 1000.0)])
    assert v.frame.columns == ["code", "quantity", "mark_price", "market_value"]
    assert v.frame.schema["code"] == pl.String
    assert v.frame.schema["quantity"] == pl.Int64
    assert v.frame.schema["mark_price"] == pl.Float64
    assert v.frame.schema["market_value"] == pl.Float64


def test_valuation_validation():
    # position MV 错
    with pytest.raises(ValueError):
        _valuation([("000001.SZ", 100, 10.0, 999.0)])
    # 重复 code
    with pytest.raises(ValueError):
        _valuation([("000001.SZ", 100, 10.0, 1000.0),
                    ("000001.SZ", 50, 10.0, 500.0)])
    # 乱序（绕过 helper 预排序）
    unsorted = pl.DataFrame([("600000.SH", 100, 10.0, 1000.0),
                             ("000001.SZ", 100, 10.0, 1000.0)],
                            schema=["code", "quantity", "mark_price",
                                    "market_value"], orient="row")
    unsorted = unsorted.with_columns(pl.col("code").cast(pl.String),
                                     pl.col("quantity").cast(pl.Int64),
                                     pl.col("mark_price").cast(pl.Float64),
                                     pl.col("market_value").cast(pl.Float64))
    with pytest.raises(ValueError):
        PortfolioValuation(as_of_date=E1,
                           phase=PortfolioStatePhase.PRE_EXECUTION,
                           cash=0.0, market_value=2000.0, nav=2000.0,
                           frame=unsorted)
    # quantity 0
    with pytest.raises(ValueError):
        _valuation([("000001.SZ", 0, 10.0, 0.0)])
    # mark <= 0
    with pytest.raises(ValueError):
        _valuation([("000001.SZ", 100, 0.0, 0.0)])
    # MV <= 0
    with pytest.raises(ValueError):
        _valuation([("000001.SZ", 100, 10.0, 0.0)])


def test_valuation_tampered_total_mv_and_nav_fail():
    """total MV / NAV 与 frame 不一致 → ValueError（不自动重算/覆盖）。"""
    frame = _valuation([("000001.SZ", 100, 10.0, 1000.0),
                        ("600000.SH", 50, 20.0, 1000.0)]).frame
    # total MV 错
    with pytest.raises(ValueError, match="market_value"):
        PortfolioValuation(as_of_date=E1,
                           phase=PortfolioStatePhase.PRE_EXECUTION,
                           cash=0.0, market_value=1500.0, nav=1500.0,
                           frame=frame)
    # NAV 错
    with pytest.raises(ValueError, match="nav"):
        PortfolioValuation(as_of_date=E1,
                           phase=PortfolioStatePhase.PRE_EXECUTION,
                           cash=500.0, market_value=2000.0, nav=2400.0,
                           frame=frame)


def test_valuation_typed_empty():
    v = _valuation([], cash=100.0)
    assert v.frame.height == 0
    assert v.market_value == 0.0 and v.nav == 100.0
    assert v.frame.schema["market_value"] == pl.Float64


# ================================================================
# AC-67..88：value_portfolio runtime
# ================================================================

def _state(cash, positions, as_of=E1):
    frame = pl.DataFrame(positions, schema=["code", "quantity",
                                            "sellable_quantity"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("quantity").cast(pl.Int64),
                               pl.col("sellable_quantity").cast(pl.Int64))
    if frame.height:
        frame = frame.sort("code")
    return PortfolioState(as_of_date=as_of,
                          phase=PortfolioStatePhase.PRE_EXECUTION,
                          cash=float(cash), positions=frame)


def _value(state, marks):
    return value_portfolio(state, marks)


def test_api_exists():
    assert callable(value_portfolio)


def test_type_guards():
    with pytest.raises(TypeError, match="state"):
        value_portfolio({"c": 1}, _marks([]))
    with pytest.raises(TypeError, match="marks"):
        value_portfolio(_state(0.0, []), {"f": 1})


def test_date_alignment():
    st = _state(0.0, [], as_of=datetime.date(2024, 1, 4))
    with pytest.raises(ValueError, match="as_of_date"):
        _value(st, _marks([]))


def test_golden_two_holdings():
    st = _state(1000.0, [("000001.SZ", 100, 100), ("600000.SH", 50, 50)])
    m = _marks([("000001.SZ", 10.0), ("600000.SH", 20.0)])
    v = _value(st, m)
    assert v.market_value == 2000.0
    assert v.nav == 3000.0
    r1 = v.frame.filter(pl.col("code") == "000001.SZ").row(0)
    r2 = v.frame.filter(pl.col("code") == "600000.SH").row(0)
    assert (r1[1], r1[2], r1[3]) == (100, 10.0, 1000.0)
    assert (r2[1], r2[2], r2[3]) == (50, 20.0, 1000.0)


def test_sellable_zero_ignored():
    st = _state(0.0, [("000001.SZ", 1000, 0)])
    m = _marks([("000001.SZ", 10.0)])
    v = _value(st, m)
    assert v.market_value == 10_000.0


def test_partially_sellable_ignored():
    st = _state(0.0, [("000001.SZ", 1000, 300)])
    m = _marks([("000001.SZ", 10.0)])
    v = _value(st, m)
    assert v.market_value == 10_000.0


def test_cash_only():
    st = _state(12_345.0, [])
    v = _value(st, _marks([]))
    assert v.market_value == 0.0 and v.nav == 12_345.0
    assert v.frame.height == 0


def test_missing_mark_fails():
    st = _state(0.0, [("000001.SZ", 100, 100), ("600000.SH", 50, 50)])
    m = _marks([("000001.SZ", 10.0)])
    with pytest.raises(ValueError, match="600000|mark|coverage"):
        _value(st, m)


def test_extra_mark_fails():
    st = _state(0.0, [("000001.SZ", 100, 100)])
    m = _marks([("000001.SZ", 10.0), ("601111.SH", 5.0)])
    with pytest.raises(ValueError, match="601111|mark|coverage"):
        _value(st, m)


def test_overflow_fails():
    st = _state(0.0, [("000001.SZ", 10**18, 0)])
    m = _marks([("000001.SZ", 1e308)])
    with pytest.raises(ValueError, match="finite|overflow|非法"):
        _value(st, m)


def test_zero_nav_valid():
    st = _state(0.0, [])
    v = _value(st, _marks([]))
    assert v.nav == 0.0


def test_immutability():
    st = _state(1000.0, [("000001.SZ", 100, 100)])
    m = _marks([("000001.SZ", 10.0)])
    st_before = st.positions.clone()
    m_before = m.frame.clone()
    _value(st, m)
    assert st.positions.equals(st_before)
    assert m.frame.equals(m_before)


def test_determinism():
    st = _state(1000.0, [("000001.SZ", 100, 100), ("600000.SH", 50, 50)])
    m = _marks([("000001.SZ", 10.0), ("600000.SH", 20.0)])
    a = _value(st, m)
    b = _value(st, m)
    assert a.frame.equals(b.frame)
    assert a.cash == b.cash and a.market_value == b.market_value
    assert a.nav == b.nav


def test_no_market_dependency_source_audit():
    from factorlab.execution import valuation as mod
    src = inspect.getsource(mod)
    for forbidden in ("daily", "adj_factor", "qfq", "hfq", "duckdb",
                      "MarketOpenSnapshot", "stk_limit", "suspend_d"):
        assert not re.search(rf"^\s*(import|from)\s+[^\s]*{forbidden}", src,
                             re.M), f"valuation.py 不得引用 {forbidden}"


def test_no_price_loader_params():
    params = inspect.signature(value_portfolio).parameters
    assert list(params) == ["state", "marks"]
