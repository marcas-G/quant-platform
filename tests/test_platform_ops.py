import polars as pl
import pytest

from factorlab.factor.errors import FactorDSLError
from factorlab.ops import registry
from factorlab.ops.platform_ops import (
    adv20,
    expand_platform_macros,
    expand_user_macros,
    group_rank,
    register_platform_ops,
    returns,
    vwap,
)
from factorlab.spec import OperatorMacro


def _ops(**kwargs):
    return {name: OperatorMacro(**cfg) for name, cfg in kwargs.items()}


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


# ---- expand_user_macros（spec.operators 内联宏） ----


def test_expand_user_macros_basic():
    out = expand_user_macros(
        "signal = mom_ratio(close, 1)",
        _ops(mom_ratio={"params": ["x", "n"], "formula": "delay(x, n) / delay(x, 2 * n) - 1"}),
    )
    assert "mom_ratio" not in out
    assert "delay(close, 1) / delay(close, 2 * 1) - 1" in out


def test_expand_user_macros_no_operators_returns_source():
    src = "signal = close / open - 1"
    assert expand_user_macros(src, {}) is src


def test_expand_user_macros_arg_count_mismatch():
    with pytest.raises(FactorDSLError, match="mom_ratio 需要 2 个参数，实际 1 个"):
        expand_user_macros(
            "signal = mom_ratio(close)",
            _ops(mom_ratio={"params": ["x", "n"], "formula": "delay(x, n) - 1"}),
        )


def test_expand_user_macros_def_same_name_priority():
    # 公式内 def 同名函数优先：不展开宏
    src = "def mom_ratio(x, n):\n    return x - 1\nsignal = mom_ratio(close, 1)"
    out = expand_user_macros(
        src,
        _ops(mom_ratio={"params": ["x", "n"], "formula": "delay(x, n) - 1"}),
    )
    assert "def mom_ratio(x, n):" in out
    assert "delay(" not in out


def test_expand_user_macros_param_substring_safe():
    # 短参数名（n）不能误替换 ts_mean/ts_min 等标识符中的子串
    out = expand_user_macros(
        "signal = ma(close, 5)",
        _ops(ma={"params": ["x", "n"], "formula": "ts_mean(x, n) - ts_min(x, n)"}),
    )
    assert "ts_mean(close, 5) - ts_min(close, 5)" in out


def test_expand_user_macros_precedence_preserved():
    # 实参为复合表达式时运算优先级由 AST 结构保证（无需手工加括号）
    out = expand_user_macros(
        "signal = scale(close - open)",
        _ops(scale={"params": ["x"], "formula": "x / ts_mean(x, 20)"}),
    )
    assert out == "signal = (close - open) / ts_mean(close - open, 20)"


def test_expand_user_macros_can_reference_platform_wrapper():
    # 用户宏公式可引用平台薄封装 returns：随后由 expand_platform_macros 展开为 ts_ 表达式
    out = expand_user_macros(
        "signal = ret(close)",
        _ops(ret={"params": ["x"], "formula": "returns(x)"}),
    )
    assert "returns(close)" in out
    out2 = expand_platform_macros(out)
    assert "returns" not in out2
    assert "close / ts_delay(close, 1) - 1" in out2


def test_expand_user_macros_syntax_error_rejected():
    with pytest.raises(FactorDSLError, match="语法错误"):
        expand_user_macros(
            "signal = mom_ratio(close, 1",
            _ops(mom_ratio={"params": ["x", "n"], "formula": "delay(x, n) - 1"}),
        )


def test_expand_user_macros_macro_formula_syntax_error_rejected():
    with pytest.raises(FactorDSLError, match="展开失败"):
        expand_user_macros(
            "signal = mom_ratio(close, 1)",
            _ops(mom_ratio={"params": ["x", "n"], "formula": "delay(x, n) -"}),
        )
