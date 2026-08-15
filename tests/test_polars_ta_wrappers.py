from factorlab.ops import registry
from factorlab.ops.polars_ta_wrappers import register_polars_ta_ops


def test_registers_core_wq_operators():
    registry.reset_registry()
    register_polars_ta_ops()
    for name in ("ts_mean", "ts_std_dev", "ts_sum", "ts_delay", "cs_rank", "cs_zscore"):
        assert registry.get_op(name).kind in {"ts", "cs"}


def test_registers_ta_family_operators():
    registry.reset_registry()
    register_polars_ta_ops()
    assert registry.get_op("ts_RSI").kind == "ta"
    assert registry.get_op("ts_ATR").kind == "ta"


def test_registers_version_mapped_operators():
    registry.reset_registry()
    register_polars_ta_ops()
    assert registry.get_op("ts_CCI").kind == "ta"
    assert registry.get_op("cs_regression_resid").kind == "cs"
