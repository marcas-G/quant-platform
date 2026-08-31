"""M7-01：StrategySpec / SelectionSpec / WeightingSpec 领域契约。"""

import math

import pytest
from pydantic import ValidationError

from factorlab.strategy import SelectionSpec, StrategySpec, WeightingSpec


def _spec(**over):
    base = {
        "name": "momentum_top30",
        "signal_name": "m6_f2_ts_cs",
        "direction": 1,
        "selection": {"method": "top_k", "k": 30},
        "weighting": {"method": "equal_weight"},
    }
    base.update(over)
    return StrategySpec.model_validate(base)


# ---------------- 正常路径 ----------------

def test_valid_top_k_equal_weight():
    s = _spec()
    assert s.name == "momentum_top30"
    assert s.direction == 1
    assert s.selection.k == 30
    assert s.selection.method == "top_k"
    assert s.weighting.method == "equal_weight"
    assert s.gross_exposure == 1.0
    assert s.rebalance_frequency == "daily"


def test_direction_minus_one():
    s = _spec(direction=-1)
    assert s.direction == -1


def test_k_one_and_thirty():
    assert _spec(selection={"method": "top_k", "k": 1}).selection.k == 1
    assert _spec(selection={"method": "top_k", "k": 30}).selection.k == 30


def test_gross_partial():
    assert _spec(gross_exposure=0.8).gross_exposure == 0.8
    assert _spec(gross_exposure=0.5).gross_exposure == 0.5


# ---------------- 非法输入 ----------------

@pytest.mark.parametrize("bad", [0, 2, True, "1"])
def test_direction_invalid(bad):
    with pytest.raises(ValidationError):
        _spec(direction=bad)


@pytest.mark.parametrize("bad_k", [0, -1, 1.5, "30", True, False])
def test_k_invalid(bad_k):
    with pytest.raises(ValidationError):
        _spec(selection={"method": "top_k", "k": bad_k})


@pytest.mark.parametrize("bad_g", [0, -1, 1.1, math.nan, math.inf, True])
def test_gross_invalid(bad_g):
    with pytest.raises(ValidationError):
        _spec(gross_exposure=bad_g)


def test_extra_unknown_field_fails():
    with pytest.raises(ValidationError):
        _spec(commission=0.001)


def test_future_label_fields_fail():
    for key in ("target", "forward_return", "label", "slippage"):
        with pytest.raises(ValidationError):
            _spec(**{key: "forward_return_5d" if key == "target" else 0.002})


def test_rebalance_weekly_monthly_valid():
    assert _spec(rebalance_frequency="weekly").rebalance_frequency == "weekly"
    assert _spec(rebalance_frequency="monthly").rebalance_frequency == "monthly"


@pytest.mark.parametrize("bad", ["5d", "quarterly", "biweekly"])
def test_rebalance_invalid_fails(bad):
    with pytest.raises(ValidationError):
        _spec(rebalance_frequency=bad)


@pytest.mark.parametrize("bad_name", ["", "123abc", "a b", "a-b", "x" * 65])
def test_invalid_name_fails(bad_name):
    with pytest.raises(ValidationError):
        _spec(name=bad_name)


def test_invalid_signal_name_fails():
    with pytest.raises(ValidationError):
        _spec(signal_name="a b")


# ---------------- 冻结 ----------------

def test_frozen():
    s = _spec()
    with pytest.raises(Exception):
        s.name = "changed"


def test_selection_frozen():
    with pytest.raises(Exception):
        _spec().selection.k = 10
