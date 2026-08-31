"""M8-01：ExecutionSpec 领域契约。"""

import math

import pytest
from pydantic import ValidationError

from factorlab.execution import ExecutionSpec


def _spec(**over):
    base = {}
    base.update(over)
    return ExecutionSpec.model_validate(base)


def test_default_valid():
    s = _spec()
    assert s.initial_cash == 1_000_000.0


def test_integer_initial_cash_valid():
    assert _spec(initial_cash=1_000_000).initial_cash == 1_000_000.0


def test_float_initial_cash_valid():
    assert _spec(initial_cash=100_000.50).initial_cash == 100_000.50


@pytest.mark.parametrize("bad", [0, -1, math.nan, math.inf, -math.inf, True, False])
def test_invalid_initial_cash(bad):
    with pytest.raises(ValidationError):
        _spec(initial_cash=bad)


def test_string_initial_cash_rejected():
    with pytest.raises(ValidationError):
        _spec(initial_cash="1000000")


@pytest.mark.parametrize("bad", [100, 1, 200, "100"])
def test_lot_size_field_forbidden(bad):
    """M8-01B：全局 lot_size 已移除——SecurityQuantityRule 是唯一数量权威。"""
    with pytest.raises(ValidationError):
        _spec(lot_size=bad)


def test_extra_field_fails():
    with pytest.raises(ValidationError):
        _spec(commission_rate=0.001)


def test_cost_fields_fail():
    for key in ("commission_rate", "min_commission", "stamp_tax",
                "transfer_fee", "slippage", "impact"):
        with pytest.raises(ValidationError):
            _spec(**{key: 0.001})


def test_no_timing_fields():
    for key in ("execution_time", "signal_time", "decision_time"):
        with pytest.raises(ValidationError):
            _spec(**{key: "open"})


def test_frozen():
    s = _spec()
    with pytest.raises(Exception):
        s.initial_cash = 0.0
