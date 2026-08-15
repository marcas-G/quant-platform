import polars as pl

from factorlab.ops import registry
from factorlab.ops.platform_ops import adv20, group_rank, register_platform_ops, returns, vwap


def test_platform_ops_return_expr():
    assert isinstance(returns(pl.col("close")), pl.Expr)
    assert isinstance(vwap(pl.col("high"), pl.col("low"), pl.col("close"), pl.col("volume")), pl.Expr)
    assert isinstance(adv20(pl.col("volume")), pl.Expr)
    assert isinstance(group_rank(pl.col("industry"), pl.col("close")), pl.Expr)


def test_register_platform_ops_exposes_ops():
    registry.reset_registry()
    register_platform_ops()
    for name, kind in (("returns", "ts"), ("vwap", "ts"), ("adv20", "ts"), ("group_rank", "gp"), ("group_mean", "gp")):
        assert registry.get_op(name).kind == kind
