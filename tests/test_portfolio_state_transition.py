"""M8-04D：same-day POST_EXECUTION PortfolioState transition——apply_fill_batch。

PRE_EXECUTION state + FillBatch → 新 immutable POST_EXECUTION state。
只消费 state + fills（不重算成交/成本/funding）；T+1 核心：当天 BUY 增加
quantity 但 sellable_quantity 不增加；SELL 同时减少两者。
"""

import datetime
import inspect
import re

import polars as pl
import pytest

from factorlab.domain import (FillBatch, PortfolioState, PortfolioStatePhase)
from factorlab.domain.timing import ExecutionTiming
from factorlab.execution import apply_fill_batch

D1 = datetime.date(2024, 1, 2)
E1 = datetime.date(2024, 1, 3)


def _state(cash, positions, as_of=E1, phase=PortfolioStatePhase.PRE_EXECUTION):
    frame = pl.DataFrame(positions, schema=["code", "quantity",
                                            "sellable_quantity"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("quantity").cast(pl.Int64),
                               pl.col("sellable_quantity").cast(pl.Int64))
    if frame.height:
        frame = frame.sort("code")
    return PortfolioState(as_of_date=as_of, phase=phase, cash=float(cash),
                          positions=frame)


def _fills(rows, exec_date=E1, timing=ExecutionTiming.NEXT_OPEN):
    frame = pl.DataFrame(rows, schema=["code", "side", "order_quantity",
                                       "filled_quantity", "reference_price",
                                       "execution_price", "gross_notional",
                                       "commission", "stamp_tax",
                                       "transfer_fee", "total_fees",
                                       "effective_cash_delta"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("side").cast(pl.String),
                               pl.col("order_quantity").cast(pl.Int64),
                               pl.col("filled_quantity").cast(pl.Int64),
                               pl.col("reference_price").cast(pl.Float64),
                               pl.col("execution_price").cast(pl.Float64),
                               pl.col("gross_notional").cast(pl.Float64),
                               pl.col("commission").cast(pl.Float64),
                               pl.col("stamp_tax").cast(pl.Float64),
                               pl.col("transfer_fee").cast(pl.Float64),
                               pl.col("total_fees").cast(pl.Float64),
                               pl.col("effective_cash_delta").cast(pl.Float64))
    if frame.height:
        frame = frame.sort("code")
    return FillBatch(decision_date=D1, execution_date=exec_date,
                     execution_timing=timing, frame=frame)


def _buy(code, filled):
    """helper：zero-cost BUY fill row（delta = -10×filled，域自洽）。"""
    gross = 10.0 * filled
    return (code, "buy", filled, filled, 10.0, 10.0, gross, 0.0, 0.0, 0.0,
            0.0, -gross)


def _sell(code, filled):
    """helper：zero-cost SELL fill row（delta = +10×filled）。"""
    gross = 10.0 * filled
    return (code, "sell", filled, filled, 10.0, 10.0, gross, 0.0, 0.0, 0.0,
            0.0, gross)


def _apply(state, fills):
    return apply_fill_batch(state, fills)


# ================================================================
# AC-01..13：API / guards / cash
# ================================================================

def test_api_exists():
    assert callable(apply_fill_batch)


def test_type_guards():
    with pytest.raises(TypeError, match="state"):
        apply_fill_batch({"cash": 0}, _fills([]))
    with pytest.raises(TypeError, match="fills"):
        apply_fill_batch(_state(0.0, []), {"frame": None})
    with pytest.raises(TypeError):
        apply_fill_batch(None, None)


def test_pre_execution_required():
    st = _state(0.0, [], phase=PortfolioStatePhase.POST_EXECUTION)
    with pytest.raises(ValueError, match="PRE_EXECUTION"):
        _apply(st, _fills([]))


def test_date_alignment():
    st = _state(0.0, [], as_of=datetime.date(2024, 1, 4))
    with pytest.raises(ValueError, match="as_of_date|execution_date"):
        _apply(st, _fills([]))


def test_next_close_not_implemented():
    st = _state(0.0, [])
    f = _fills([], timing=ExecutionTiming.NEXT_CLOSE)
    with pytest.raises(NotImplementedError, match="NEXT_CLOSE"):
        _apply(st, f)


def test_output_metadata():
    post = _apply(_state(100.0, []), _fills([]))
    assert post.as_of_date == E1
    assert post.phase is PortfolioStatePhase.POST_EXECUTION


def test_cash_empty_fills_preserved():
    post = _apply(_state(100_000.0, []), _fills([]))
    assert post.cash == 100_000.0


def test_cash_transition():
    f = _fills([_sell("000001.SZ", 400),
                _buy("600000.SH", 200)])
    post = _apply(_state(10_000.0, [("000001.SZ", 1000, 1000)]), f)
    assert post.cash == 10_000.0 + 4000.0 - 2000.0


def test_cash_negative_fails():
    """domain-valid FillBatch 但相对 state 现金不一致 → ValueError（不依赖
    输出 constructor 偶然报错）。"""
    f = _fills([_buy("600000.SH", 1000)])
    with pytest.raises(ValueError, match="cash-consistent|cash"):
        _apply(_state(100.0, []), f)


def test_no_cash_tolerance_clamp():
    """cash 差 1 ulp 导致 post < 0 也必须 fail（严格 >= 0，无 tolerance）。"""
    f = _fills([_buy("600000.SH", 1)])     # delta = -10.0
    st = _state(10.0 - 1e-15, [])          # 10 - 1ulp → post = -8.88e-16
    with pytest.raises(ValueError):
        _apply(st, f)


# ================================================================
# AC-14..38：positions transition
# ================================================================

def test_new_buy_position():
    f = _fills([_buy("000001.SZ", 1000)])
    post = _apply(_state(100_000.0, []), f)
    assert post.cash == 90_000.0
    r = post.positions.filter(pl.col("code") == "000001.SZ").row(0)
    assert r[1] == 1000 and r[2] == 0       # quantity=1000, sellable=0


def test_buy_existing_holding():
    f = _fills([_buy("000001.SZ", 500)])
    post = _apply(_state(100_000.0, [("000001.SZ", 1000, 1000)]), f)
    r = post.positions.filter(pl.col("code") == "000001.SZ").row(0)
    assert r[1] == 1500 and r[2] == 1000    # T+1：sellable 不变


def test_buy_existing_partially_unsellable():
    f = _fills([_buy("000001.SZ", 200)])
    post = _apply(_state(100_000.0, [("000001.SZ", 1000, 600)]), f)
    r = post.positions.filter(pl.col("code") == "000001.SZ").row(0)
    assert r[1] == 1200 and r[2] == 600


def test_partial_sell():
    f = _fills([_sell("000001.SZ", 500)])
    post = _apply(_state(0.0, [("000001.SZ", 1000, 600)]), f)
    r = post.positions.filter(pl.col("code") == "000001.SZ").row(0)
    assert r[1] == 500 and r[2] == 100      # 两者同减


def test_sell_all_sellable_keep_position():
    f = _fills([_sell("000001.SZ", 600)])
    post = _apply(_state(0.0, [("000001.SZ", 1000, 600)]), f)
    r = post.positions.filter(pl.col("code") == "000001.SZ").row(0)
    assert r[1] == 400 and r[2] == 0


def test_full_liquidation_removes_row():
    f = _fills([_sell("000001.SZ", 1000)])
    post = _apply(_state(0.0, [("000001.SZ", 1000, 1000)]), f)
    assert post.positions.height == 0
    assert post.positions.schema["code"] == pl.String
    assert post.positions.schema["quantity"] == pl.Int64
    assert post.positions.schema["sellable_quantity"] == pl.Int64


def test_multiple_fills():
    f = _fills([_sell("000001.SZ", 400),
                _buy("600000.SH", 200),
                _buy("601111.SH", 300)])
    st = _state(10_000.0, [("000001.SZ", 1000, 1000),
                           ("600000.SH", 500, 500)])
    post = _apply(st, f)
    assert post.cash == 9_000.0
    assert post.positions["code"].to_list() == ["000001.SZ", "600000.SH",
                                                "601111.SH"]
    r1 = post.positions.filter(pl.col("code") == "000001.SZ").row(0)
    r2 = post.positions.filter(pl.col("code") == "600000.SH").row(0)
    r3 = post.positions.filter(pl.col("code") == "601111.SH").row(0)
    assert (r1[1], r1[2]) == (600, 600)
    assert (r2[1], r2[2]) == (700, 500)
    assert (r3[1], r3[2]) == (300, 0)


def test_unfilled_codes_unchanged():
    f = _fills([_buy("600000.SH", 200)])
    st = _state(2_000.0, [("601111.SH", 999, 500), ("600000.SH", 1, 1)])
    post = _apply(st, f)
    r = post.positions.filter(pl.col("code") == "601111.SH").row(0)
    assert (r[1], r[2]) == (999, 500)


def test_output_sorted_asc():
    f = _fills([_buy("688001.SH", 100),
                _buy("000001.SZ", 100)])
    post = _apply(_state(2_000.0, []), f)
    assert post.positions["code"].to_list() == ["000001.SZ", "688001.SH"]


def test_immutability():
    st = _state(10_000.0, [("000001.SZ", 1000, 600)])
    f = _fills([_sell("000001.SZ", 500),
                _buy("600000.SH", 200)])
    pos_before = st.positions.clone()
    f_before = f.frame.clone()
    _apply(st, f)
    assert st.positions.equals(pos_before)
    assert f.frame.equals(f_before)
    assert st.phase is PortfolioStatePhase.PRE_EXECUTION
    assert st.cash == 10_000.0


def test_determinism():
    st = _state(10_000.0, [("000001.SZ", 1000, 1000)])
    f = _fills([_sell("000001.SZ", 400),
                _buy("600000.SH", 200)])
    a = _apply(st, f)
    b = _apply(st, f)
    assert a.cash == b.cash
    assert a.positions.equals(b.positions)


# ================================================================
# AC-40..46：invalid
# ================================================================

def test_sell_missing_position_fails():
    f = _fills([_sell("000001.SZ", 100)])
    with pytest.raises(ValueError, match="position|持仓"):
        _apply(_state(0.0, []), f)


def test_sell_exceeds_quantity_fails():
    f = _fills([_sell("000001.SZ", 1500)])
    with pytest.raises(ValueError, match="quantity|holding"):
        _apply(_state(0.0, [("000001.SZ", 1000, 1000)]), f)


def test_sell_exceeds_sellable_fails():
    f = _fills([_sell("000001.SZ", 800)])
    with pytest.raises(ValueError, match="sellable"):
        _apply(_state(0.0, [("000001.SZ", 1000, 600)]), f)


def test_buy_int64_overflow_fails():
    f = _fills([_buy("000001.SZ", 100)])
    st = _state(1_000.0, [("000001.SZ", 2**63 - 50, 0)])
    with pytest.raises(ValueError, match="Int64|overflow|溢出"):
        _apply(st, f)


def test_apply_to_post_state_fails():
    st = _state(0.0, [], phase=PortfolioStatePhase.POST_EXECUTION)
    with pytest.raises(ValueError):
        _apply(st, _fills([]))


# ================================================================
# AC-47..63：无重算 / 无越权
# ================================================================

def test_no_recompute_source_audit():
    """state.py 不得 import 成本/fillability/market/rules/DB 等。"""
    from factorlab.execution import state as mod
    src = inspect.getsource(mod)
    for forbidden in ("compute_execution_cost", "ExecutionCostSpec",
                      "ExecutionCostBreakdown", "MarketOpenSnapshot",
                      "OpenFillAssessment", "SecurityQuantityRules",
                      "OrderBatch", "duckdb", "db_path", "trade_cal",
                      "TargetPortfolio", "StrategySpec", "SignalArtifact"):
        assert not re.search(rf"^\s*(import|from)\s+[^\s]*{forbidden}", src,
                             re.M), f"state.py 不得引用 {forbidden}"


def test_no_recompute_in_signature():
    params = inspect.signature(apply_fill_batch).parameters
    assert list(params) == ["state", "fills"]


def test_no_cash_settlement_buckets():
    post = _apply(_state(100.0, []), _fills([]))
    assert not hasattr(post, "settled_cash")
    assert not hasattr(post, "unsettled_cash")


def test_no_cost_basis_fields():
    f = _fills([_buy("000001.SZ", 100)])
    post = _apply(_state(1000.0, []), f)
    assert post.positions.columns == ["code", "quantity", "sellable_quantity"]
