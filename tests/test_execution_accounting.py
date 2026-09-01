"""M8-05B：execution accounting——PRE state + FillBatch + POST state →
ExecutionAccountingSummary。

只聚合 FillBatch（唯一成本/cash authority），不做任何重算：
cash bridge = PRE cash + Σ effective_cash_delta == POST cash（严格）。
"""

import datetime
import inspect
import re

import polars as pl
import pytest

from factorlab.domain import (ExecutionAccountingSummary, FillBatch,
                              PortfolioState, PortfolioStatePhase)
from factorlab.domain.timing import ExecutionTiming
from factorlab.execution import summarize_execution_accounting

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


def _fill_row(code, side, gross, comm, stamp, transfer, delta, qty=None):
    qty = qty if qty is not None else max(1, int(gross))
    total = comm + stamp + transfer
    price = gross / qty          # gross == price × qty（exact for int gross）
    return (code, side, qty, qty, price, price, gross, comm, stamp, transfer,
            total, delta)


def _buy(code, gross, comm=0.0, stamp=0.0, transfer=0.0):
    return _fill_row(code, "buy", gross, comm, stamp, transfer,
                     -(gross + comm + stamp + transfer))


def _sell(code, gross, comm=0.0, stamp=0.0, transfer=0.0):
    return _fill_row(code, "sell", gross, comm, stamp, transfer,
                     gross - comm - stamp - transfer)


def _summary(pre, fills, post):
    return summarize_execution_accounting(pre, fills, post)


def _pre(cash=100_000.0):
    return _state(cash, [])


def _post(cash, positions=(), as_of=E1):
    return _state(cash, list(positions), as_of=as_of,
                  phase=PortfolioStatePhase.POST_EXECUTION)


# ================================================================
# AC-01..12：API / guards
# ================================================================

def test_summary_exists_and_frozen():
    import dataclasses
    assert dataclasses.is_dataclass(ExecutionAccountingSummary)
    with pytest.raises(Exception):
        s = ExecutionAccountingSummary(execution_date=E1, cash_before=1.0,
                                       buy_gross_notional=0.0,
                                       sell_gross_notional=0.0, commission=0.0,
                                       stamp_tax=0.0, transfer_fee=0.0,
                                       total_fees=0.0, net_cash_delta=0.0,
                                       cash_after=1.0)
        s.cash_after = 2.0


def test_api_exists():
    assert callable(summarize_execution_accounting)


def test_type_guards():
    with pytest.raises(TypeError, match="pre_state"):
        summarize_execution_accounting({"c": 1}, _fills([]), _post(0.0))
    with pytest.raises(TypeError, match="fills"):
        summarize_execution_accounting(_pre(), {"f": 1}, _post(0.0))
    with pytest.raises(TypeError, match="post_state"):
        summarize_execution_accounting(_pre(), _fills([]), {"c": 1})


def test_pre_phase_required():
    pre = _state(100.0, [], phase=PortfolioStatePhase.POST_EXECUTION)
    with pytest.raises(ValueError, match="PRE_EXECUTION"):
        _summary(pre, _fills([]), _post(100.0))


def test_post_phase_required():
    post = _state(100.0, [], phase=PortfolioStatePhase.PRE_EXECUTION)
    with pytest.raises(ValueError, match="POST_EXECUTION"):
        _summary(_pre(), _fills([]), post)


def test_date_alignment():
    with pytest.raises(ValueError, match="as_of_date|execution_date"):
        _summary(_state(100.0, [], as_of=datetime.date(2024, 1, 4)),
                 _fills([]), _post(100.0))
    with pytest.raises(ValueError, match="as_of_date|execution_date"):
        _summary(_pre(), _fills([], exec_date=datetime.date(2024, 1, 4)),
                 _post(100.0))
    with pytest.raises(ValueError, match="as_of_date|execution_date"):
        _summary(_pre(), _fills([]),
                 _post(100.0, as_of=datetime.date(2024, 1, 4)))


def test_next_close_not_implemented():
    f = _fills([], timing=ExecutionTiming.NEXT_CLOSE)
    with pytest.raises(NotImplementedError):
        _summary(_pre(), f, _post(100.0))


# ================================================================
# AC-13..27：cash bridge / empty / aggregation
# ================================================================

def test_empty_fills():
    s = _summary(_pre(100_000.0), _fills([]), _post(100_000.0))
    assert s.cash_before == 100_000.0 and s.cash_after == 100_000.0
    assert s.net_cash_delta == 0.0
    assert s.buy_gross_notional == 0.0 and s.sell_gross_notional == 0.0
    assert s.commission == 0.0 and s.stamp_tax == 0.0
    assert s.transfer_fee == 0.0 and s.total_fees == 0.0


def test_cash_bridge_strict():
    f = _fills([_buy("600000.SH", 1000.0), _sell("000001.SZ", 500.0)])
    pre = _pre(100_000.0)
    post = _post(100_000.0 + (-1000.0) + 500.0)
    s = _summary(pre, f, post)
    assert s.net_cash_delta == -500.0
    assert s.cash_before == 100_000.0 and s.cash_after == 99_500.0


def test_cash_corruption_fails():
    """pre=10000 delta=-1000 post=9500 → 期望 9000 → ValueError。"""
    f = _fills([_buy("600000.SH", 1000.0)])
    with pytest.raises(ValueError, match="cash-consistent|cash"):
        _summary(_pre(10_000.0), f, _post(9_500.0))


def test_buy_only_aggregation():
    f = _fills([_buy("600000.SH", 1000.0, comm=5.0, transfer=0.2),
                _buy("601111.SH", 2000.0)])
    post_cash = 10_000.0 + f.frame["effective_cash_delta"].sum()
    s = _summary(_pre(10_000.0), f, _post(post_cash))
    assert s.buy_gross_notional == 3000.0
    assert s.sell_gross_notional == 0.0
    assert s.commission == 5.0 and s.transfer_fee == 0.2
    assert s.total_fees == 5.0 + 0.2


def test_sell_only_aggregation():
    f = _fills([_sell("000001.SZ", 1000.0, comm=5.0, stamp=1.0,
                      transfer=0.2)])
    s = _summary(_pre(0.0), f, _post(1000.0 - 6.2))
    assert s.sell_gross_notional == 1000.0
    assert s.buy_gross_notional == 0.0
    assert s.commission == 5.0 and s.stamp_tax == 1.0
    assert s.transfer_fee == 0.2 and s.total_fees == 6.2
    assert s.net_cash_delta == 993.8


def test_mixed_aggregation():
    f = _fills([_sell("000001.SZ", 1000.0, comm=5.0, stamp=1.0, transfer=0.2),
                _buy("600000.SH", 2000.0, comm=6.0, transfer=0.4)])
    pre = _pre(10_000.0)
    net = 993.8 - 2006.4
    post = _post(10_000.0 + net)
    s = _summary(pre, f, post)
    assert s.buy_gross_notional == 2000.0
    assert s.sell_gross_notional == 1000.0
    assert s.commission == 11.0 and s.stamp_tax == 1.0
    assert s.transfer_fee == 0.2 + 0.4
    assert s.total_fees == 11.0 + 1.0 + (0.2 + 0.4)
    assert s.net_cash_delta == net
    assert s.cash_after == 10_000.0 + net


def test_execution_date_field():
    s = _summary(_pre(), _fills([]), _post(100_000.0))
    assert s.execution_date == E1


def test_summary_monetary_validators():
    """现金/费用/gross 非法 → ValueError。"""
    with pytest.raises(ValueError):
        ExecutionAccountingSummary(execution_date=E1, cash_before=-1.0,
                                   buy_gross_notional=0.0,
                                   sell_gross_notional=0.0, commission=0.0,
                                   stamp_tax=0.0, transfer_fee=0.0,
                                   total_fees=0.0, net_cash_delta=0.0,
                                   cash_after=0.0)
    with pytest.raises(ValueError):
        ExecutionAccountingSummary(execution_date=E1, cash_before=1.0,
                                   buy_gross_notional=-5.0,
                                   sell_gross_notional=0.0, commission=0.0,
                                   stamp_tax=0.0, transfer_fee=0.0,
                                   total_fees=0.0, net_cash_delta=0.0,
                                   cash_after=0.0)
    with pytest.raises(ValueError):
        ExecutionAccountingSummary(execution_date=E1, cash_before=1.0,
                                   buy_gross_notional=0.0,
                                   sell_gross_notional=0.0, commission=0.0,
                                   stamp_tax=0.0, transfer_fee=0.0,
                                   total_fees=5.0, net_cash_delta=0.0,
                                   cash_after=0.0)   # total != comm+stamp+transfer


# ================================================================
# AC-28..34：无重算 / immutability / determinism
# ================================================================

def test_no_cost_recompute_source_audit():
    from factorlab.execution import accounting as mod
    src = inspect.getsource(mod)
    for forbidden in ("compute_execution_cost", "ExecutionCostSpec",
                      "duckdb", "MarketOpenSnapshot", "OrderBatch"):
        assert not re.search(rf"^\s*(import|from)\s+[^\s]*{forbidden}", src,
                             re.M), f"accounting.py 不得引用 {forbidden}"


def test_no_spec_input():
    params = inspect.signature(summarize_execution_accounting).parameters
    assert list(params) == ["pre_state", "fills", "post_state"]


def test_immutability():
    f = _fills([_sell("000001.SZ", 1000.0, comm=5.0, stamp=1.0)])
    pre = _pre(10_000.0)
    post = _post(10_000.0 + 994.0)
    pre_before = pre.positions.clone()
    f_before = f.frame.clone()
    _summary(pre, f, post)
    assert pre.positions.equals(pre_before)
    assert f.frame.equals(f_before)
    assert post.cash == 10_994.0


def test_determinism():
    f = _fills([_sell("000001.SZ", 1000.0, comm=5.0),
                _buy("600000.SH", 2000.0, comm=6.0)])
    pre = _pre(10_000.0)
    post = _post(10_000.0 + 995.0 - 2006.0)
    a = _summary(pre, f, post)
    b = _summary(pre, f, post)
    assert a == b
