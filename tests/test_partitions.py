import pytest

from factorlab.engine.partitions import reject_future_shifts, validate_partition_calls
from factorlab.factor.errors import FactorDSLError
from factorlab.ops import registry
from factorlab.ops.platform_ops import register_platform_ops
from factorlab.ops.polars_ta_wrappers import register_polars_ta_ops


@pytest.fixture(autouse=True)
def _registered_ops():
    registry.reset_registry()
    register_polars_ta_ops()
    register_platform_ops()


def test_allows_known_prefixed_calls():
    validate_partition_calls("signal = ts_mean(close, 20) + cs_rank(close)")


def test_allows_platform_thin_ops():
    validate_partition_calls("signal = returns(close) + adv20(volume)")


def test_allows_elementwise_functions():
    validate_partition_calls("signal = abs(close - open) + log(volume) / sqrt(abs(close))")


def test_allows_inline_def_with_elementwise_ops():
    validate_partition_calls(
        "def flip(x, n):\n    return x * n\n"
        "signal = flip(close, 5)"
    )


def test_rejects_window_op_inside_def():
    with pytest.raises(ValueError, match="def"):
        validate_partition_calls(
            "def momentum(x, n):\n    return ts_delay(x, n) / ts_delay(x, 2 * n) - 1\n"
            "signal = momentum(close, 5)"
        )


def test_rejects_unknown_operator():
    with pytest.raises(ValueError):
        validate_partition_calls("signal = not_real_operator(close)")


def test_rejects_negative_delay():
    with pytest.raises(ValueError):
        reject_future_shifts("signal = ts_delay(close, -1)")


def test_rejects_negative_delta():
    with pytest.raises(ValueError):
        reject_future_shifts("signal = ts_delta(close, -5)")


def test_allows_positive_delay():
    reject_future_shifts("signal = ts_delay(close, 5)")


def test_errors_carry_source_location():
    with pytest.raises(FactorDSLError) as exc_info:
        reject_future_shifts("signal = ts_delay(close, -1)")
    assert exc_info.value.line == 1


def test_rejects_folded_negative_delay():
    with pytest.raises(ValueError):
        reject_future_shifts("signal = ts_delay(close, 1 - 2)")


def test_rejects_keyword_negative_delay():
    with pytest.raises(ValueError):
        reject_future_shifts("signal = ts_delay(close, d=-1)")


def test_rejects_float_negative_delay():
    with pytest.raises(ValueError):
        reject_future_shifts("signal = ts_delay(close, -1.0)")


def test_allows_variable_shift_and_positive_expr():
    reject_future_shifts("signal = ts_delay(close, n)")


def test_import_alias_resolves_to_known_op():
    validate_partition_calls(
        "from factorlab.ops.platform_ops import returns as ret\nsignal = ret(close)"
    )


def test_import_alias_of_window_op_inside_def_rejected():
    with pytest.raises(ValueError, match="def"):
        validate_partition_calls(
            "from polars_ta.prefix.wq import ts_delay as d\n"
            "def f(x):\n    return d(x, 1)\n"
            "signal = f(close)"
        )
