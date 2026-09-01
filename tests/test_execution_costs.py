"""M8-05A：Execution Cost Model Contracts——ExecutionCostSpec + compute_execution_cost。

v1 = zero-cost default / security-agnostic / time-invariant / continuous Float64
货币算术（无分位 rounding——券商费用取整规则尚未建模）。
"""

import math

import pytest
from pydantic import ValidationError

from factorlab.domain import OrderSide
from factorlab.execution import (ExecutionCostBreakdown, ExecutionCostSpec,
                                 ExecutionSpec, compute_execution_cost)

BUY = OrderSide.BUY
SELL = OrderSide.SELL


def _cost(**over):
    base = {"commission_rate": 0.0, "minimum_commission": 0.0,
            "stamp_tax_sell_rate": 0.0, "transfer_fee_rate": 0.0,
            "slippage_bps": 0.0}
    base.update(over)
    return ExecutionCostSpec.model_validate(base)


def _exec(*, side=BUY, price=10.0, qty=100, **over):
    return compute_execution_cost(side=side, reference_price=price,
                                  quantity=qty, spec=_cost(**over))


# ================================================================
# AC-01..12：ExecutionCostSpec validation
# ================================================================

def test_default_zero_cost():
    s = ExecutionCostSpec.model_validate({})
    assert s.commission_rate == 0.0
    assert s.minimum_commission == 0.0
    assert s.stamp_tax_sell_rate == 0.0
    assert s.transfer_fee_rate == 0.0
    assert s.slippage_bps == 0.0


def test_frozen():
    s = _cost()
    with pytest.raises(Exception):
        s.commission_rate = 0.1


def test_extra_forbid():
    with pytest.raises(ValidationError):
        ExecutionCostSpec.model_validate({"commission_rate": 0.1, "foo": 1})


@pytest.mark.parametrize("field", ["commission_rate", "stamp_tax_sell_rate",
                                   "transfer_fee_rate"])
@pytest.mark.parametrize("bad", [True, False, "0.0003", None, -0.1, math.nan,
                                 math.inf, -math.inf, 1.0, 1.2])
def test_proportional_rate_rejections(field, bad):
    with pytest.raises(ValidationError):
        _cost(**{field: bad})


@pytest.mark.parametrize("field", ["minimum_commission", "slippage_bps"])
@pytest.mark.parametrize("bad", [True, False, "5", None, -1.0, math.nan,
                                 math.inf, -math.inf])
def test_nonnegative_field_rejections(field, bad):
    with pytest.raises(ValidationError):
        _cost(**{field: bad})


def test_rate_boundaries():
    _cost(commission_rate=0.0)
    _cost(commission_rate=0.999999)
    _cost(stamp_tax_sell_rate=0.5)
    _cost(transfer_fee_rate=1e-9)
    _cost(minimum_commission=0.0)
    _cost(minimum_commission=1e9)
    _cost(slippage_bps=0.0)
    _cost(slippage_bps=1e6)     # bps 无上限


# ================================================================
# AC-13..20：ExecutionSpec integration
# ================================================================

def test_execution_spec_contains_cost_model():
    s = ExecutionSpec.model_validate({})
    assert isinstance(s.cost_model, ExecutionCostSpec)
    assert s.cost_model.commission_rate == 0.0


def test_old_initial_cash_only_valid():
    s = ExecutionSpec.model_validate({"initial_cash": 500_000.0})
    assert s.initial_cash == 500_000.0
    assert s.cost_model.commission_rate == 0.0


def test_root_level_cost_fields_rejected():
    for key in ("commission_rate", "commission", "slippage", "slippage_bps",
                "stamp_tax", "stamp_tax_sell_rate", "transfer_fee_rate",
                "minimum_commission"):
        with pytest.raises(ValidationError):
            ExecutionSpec.model_validate({key: 0.001})


def test_lot_size_remains_rejected():
    with pytest.raises(ValidationError):
        ExecutionSpec.model_validate({"lot_size": 100})


def test_nested_cost_model_valid():
    s = ExecutionSpec.model_validate(
        {"initial_cash": 1_000_000.0,
         "cost_model": {"commission_rate": 0.001, "minimum_commission": 5.0}})
    assert s.cost_model.commission_rate == 0.001
    assert s.cost_model.minimum_commission == 5.0


def test_execution_spec_equality():
    assert ExecutionSpec.model_validate({}) == ExecutionSpec.model_validate({})


def test_model_dump_contains_cost_model():
    d = ExecutionSpec.model_validate({}).model_dump()
    assert "cost_model" in d
    assert d["cost_model"]["commission_rate"] == 0.0


def test_no_mutable_default_sharing():
    a = ExecutionSpec.model_validate({})
    b = ExecutionSpec.model_validate({})
    assert a.cost_model is not b.cost_model
    assert a.cost_model == b.cost_model


# ================================================================
# AC-21..27：compute_execution_cost guards
# ================================================================

def test_breakdown_frozen():
    b = _exec()
    with pytest.raises(Exception):
        b.total_fees = 5.0


@pytest.mark.parametrize("bad_side", ["buy", "sell", "BUY", None, 1])
def test_side_requires_enum(bad_side):
    with pytest.raises(TypeError):
        compute_execution_cost(side=bad_side, reference_price=10.0,
                               quantity=100, spec=_cost())


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, True, "10",
                                 None])
def test_reference_price_guards(bad):
    with pytest.raises((TypeError, ValueError)):
        compute_execution_cost(side=BUY, reference_price=bad, quantity=100,
                               spec=_cost())


@pytest.mark.parametrize("bad", [0, -1, True, False, 100.0, "100", None])
def test_quantity_strict_int(bad):
    with pytest.raises((TypeError, ValueError)):
        compute_execution_cost(side=BUY, reference_price=10.0, quantity=bad,
                               spec=_cost())


def test_spec_instance_required():
    with pytest.raises(TypeError):
        compute_execution_cost(side=BUY, reference_price=10.0, quantity=100,
                               spec={"commission_rate": 0.0})


def test_float_overflow_notional_fails():
    with pytest.raises(ValueError):
        compute_execution_cost(side=BUY, reference_price=1e308, quantity=100,
                               spec=_cost())


# ================================================================
# AC-28..45：算法与语义
# ================================================================

def test_slippage_applied_before_notional():
    """BUY 10 bps：execution_price=10×1.001 → gross=price×100（fees 基于
    slipped gross——continuous Float64，不用十进制字面量断言）。"""
    b = _exec(side=BUY, price=10.0, qty=100, commission_rate=0.001,
              slippage_bps=10)
    assert b.execution_price == 10.0 * 1.001
    assert b.gross_notional == 10.0 * 1.001 * 100
    assert b.commission == b.gross_notional * 0.001


def test_buy_slippage_increases_price():
    assert _exec(side=BUY, price=10.0, slippage_bps=10).execution_price \
        == 10.0 * 1.001


def test_sell_slippage_decreases_price():
    assert _exec(side=SELL, price=10.0, slippage_bps=10).execution_price == 9.99


def test_zero_slippage_price_unchanged():
    assert _exec(side=BUY, price=10.0).execution_price == 10.0
    assert _exec(side=SELL, price=10.0).execution_price == 10.0


def test_pathological_sell_slippage_fails():
    """10000 bps → execution_price = 0 → ValueError（不 clipping）。"""
    with pytest.raises(ValueError):
        compute_execution_cost(side=SELL, reference_price=10.0, quantity=100,
                               spec=_cost(slippage_bps=10000))


def test_buy_extreme_slippage_allowed():
    b = compute_execution_cost(side=BUY, reference_price=10.0, quantity=1,
                               spec=_cost(slippage_bps=50000))
    assert b.execution_price == 60.0


def test_gross_is_execution_price_times_quantity():
    b = _exec(side=BUY, price=12.5, qty=400)
    assert b.gross_notional == 5000.0


def test_commission_proportional():
    b = _exec(side=BUY, price=100.0, qty=1000, commission_rate=0.001)
    assert b.commission == 100.0


def test_zero_rate_ignores_minimum():
    b = _exec(side=BUY, price=10.0, qty=100, commission_rate=0.0,
              minimum_commission=5.0)
    assert b.commission == 0.0


def test_minimum_commission_enforced():
    b = _exec(side=BUY, price=10.0, qty=100, commission_rate=0.001,
              minimum_commission=5.0)
    assert b.commission == 5.0


def test_minimum_exact_tie():
    b = _exec(side=BUY, price=10.0, qty=1000, commission_rate=0.001,
              minimum_commission=10.0)
    assert b.commission == 10.0


def test_stamp_buy_zero():
    b = _exec(side=BUY, price=10.0, qty=1000, stamp_tax_sell_rate=0.001)
    assert b.stamp_tax == 0.0


def test_stamp_sell_proportional():
    b = _exec(side=SELL, price=10.0, qty=1000, stamp_tax_sell_rate=0.001)
    assert b.stamp_tax == 10.0


def test_transfer_buy_proportional():
    b = _exec(side=BUY, price=10.0, qty=1000, transfer_fee_rate=0.00002)
    assert b.transfer_fee == 0.2


def test_transfer_sell_proportional():
    b = _exec(side=SELL, price=10.0, qty=1000, transfer_fee_rate=0.00002)
    assert b.transfer_fee == 0.2


def test_total_fees_exact_component_sum():
    b = _exec(side=SELL, price=10.0, qty=1000, commission_rate=0.001,
              stamp_tax_sell_rate=0.001, transfer_fee_rate=0.00002)
    assert b.total_fees == b.commission + b.stamp_tax + b.transfer_fee
    assert b.total_fees == 10.0 + 10.0 + 0.2


def test_buy_cash_delta_negative_includes_fees():
    b = _exec(side=BUY, price=10.0, qty=100, commission_rate=0.001,
              minimum_commission=5.0)
    assert b.effective_cash_delta == -(1000.0 + 5.0)


def test_sell_cash_delta_positive_subtracts_fees():
    b = _exec(side=SELL, price=10.0, qty=100, commission_rate=0.001,
              minimum_commission=5.0, stamp_tax_sell_rate=0.001)
    assert b.effective_cash_delta == 1000.0 - 5.0 - 1.0


def test_pathological_sell_fees_ge_gross_fails():
    """minimum commission 极大使 total_fees >= gross → ValueError。"""
    with pytest.raises(ValueError):
        compute_execution_cost(side=SELL, reference_price=10.0, quantity=100,
                               spec=_cost(commission_rate=0.001,
                                          minimum_commission=1e9))


def test_buy_fees_can_exceed_notional():
    """BUY 允许 fees > notional（minimum commission 在小交易上）——cash
    requirement = notional + fees。"""
    b = compute_execution_cost(side=BUY, reference_price=10.0, quantity=1,
                               spec=_cost(commission_rate=0.001,
                                          minimum_commission=100.0))
    assert b.commission == 100.0
    assert b.effective_cash_delta == -(10.0 + 100.0)


# ================================================================
# AC-46..53：golden fixtures
# ================================================================

def test_zero_cost_buy_golden():
    b = _exec(side=BUY, price=10.0, qty=100)
    assert b.execution_price == 10.0
    assert b.gross_notional == 1000.0
    assert b.commission == 0.0 and b.stamp_tax == 0.0 and b.transfer_fee == 0.0
    assert b.total_fees == 0.0
    assert b.effective_cash_delta == -1000.0


def test_zero_cost_sell_golden():
    b = _exec(side=SELL, price=10.0, qty=100)
    assert b.effective_cash_delta == 1000.0


def test_min_commission_golden():
    b = _exec(side=BUY, price=10.0, qty=100, commission_rate=0.001,
              minimum_commission=5.0)
    assert b.commission == 5.0
    assert b.effective_cash_delta == -1005.0


def test_proportional_commission_golden():
    b = _exec(side=BUY, price=100.0, qty=1000, commission_rate=0.001,
              minimum_commission=5.0)
    assert b.commission == 100.0


def test_stamp_golden():
    b = _exec(side=SELL, price=10.0, qty=1000, stamp_tax_sell_rate=0.001)
    assert b.stamp_tax == 10.0


def test_transfer_golden():
    b = _exec(side=BUY, price=10.0, qty=1000, transfer_fee_rate=0.00002)
    assert b.transfer_fee == 0.2


def test_buy_slippage_golden():
    b = _exec(side=BUY, price=10.0, qty=100, slippage_bps=10)
    assert b.execution_price == 10.0 * 1.001
    assert b.gross_notional == 10.0 * 1.001 * 100


def test_sell_slippage_golden():
    b = _exec(side=SELL, price=10.0, qty=100, slippage_bps=10)
    assert b.execution_price == 9.99
    assert b.gross_notional == 999.0


# ================================================================
# AC-54..62：边界（无 rounding / 无 code/market/date / 无 DB / 无 mutation）
# ================================================================

def test_no_cent_rounding():
    """continuous Float64——不 round(x, 2)。"""
    b = _exec(side=BUY, price=10.0, qty=333, commission_rate=0.001)
    assert b.commission == 3.33   # 3330 * 0.001 = 3.33（精确）
    b2 = _exec(side=BUY, price=3.33, qty=7, commission_rate=0.0003)
    assert b2.commission == 3.33 * 7 * 0.0003   # 连续 float，不取整


def test_no_code_market_date_inputs():
    import inspect
    params = inspect.signature(compute_execution_cost).parameters
    for forbidden in ("code", "market", "exchange", "execution_date", "db",
                      "db_path"):
        assert forbidden not in params


def test_no_polars_duckdb_imports():
    import inspect
    import re
    from factorlab.execution.costs import compute_execution_cost as f
    src = inspect.getsource(inspect.getmodule(f))
    for forbidden in ("duckdb", "polars", "MarketOpenSnapshot",
                      "PortfolioState", "OrderBatch", "TargetPortfolio"):
        assert not re.search(rf"^\s*(import|from)\s+{forbidden}", src, re.M), \
            f"costs.py 不得 import {forbidden}"


def test_breakdown_fields_present():
    b = _exec()
    assert b.gross_notional >= 0
    assert b.commission >= 0 and b.stamp_tax >= 0 and b.transfer_fee >= 0
    assert b.total_fees >= 0
    assert b.execution_price > 0
    assert isinstance(b.effective_cash_delta, float)


def test_determinism_repeated_calls():
    args = dict(side=SELL, price=12.34, qty=567, commission_rate=0.0005,
                minimum_commission=5.0, stamp_tax_sell_rate=0.0005,
                transfer_fee_rate=0.00002, slippage_bps=8)
    a = _exec(**args)
    b = _exec(**args)
    assert a == b
    assert a.gross_notional == b.gross_notional
    assert a.effective_cash_delta == b.effective_cash_delta


def test_side_asymmetry():
    """同 price/qty/spec：stamp 仅 SELL、slippage 反向、cash delta 反向。"""
    spec = dict(commission_rate=0.001, minimum_commission=5.0,
                stamp_tax_sell_rate=0.001, transfer_fee_rate=0.00002,
                slippage_bps=10)
    b = _exec(side=BUY, price=10.0, qty=1000, **spec)
    s = _exec(side=SELL, price=10.0, qty=1000, **spec)
    assert b.execution_price == 10.0 * 1.001 and s.execution_price == 9.99
    assert b.stamp_tax == 0.0 and s.stamp_tax == 9.99 * 1000 * 0.001
    assert b.effective_cash_delta < 0 < s.effective_cash_delta
    assert b.effective_cash_delta == -(b.gross_notional + b.total_fees)
    assert s.effective_cash_delta == s.gross_notional - s.total_fees
