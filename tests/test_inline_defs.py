import pytest

from factorlab.factor.errors import FactorDSLError
from factorlab.ops.platform_ops import inline_defs


def test_inline_single_def_with_window_ops():
    src = '''
def my_ts(x, n):
    return ts_mean(x, n) / ts_delay(x, 1)

signal = my_ts(close, 20)
'''
    out = inline_defs(src)
    assert "def my_ts" not in out            # def 删除
    assert "ts_mean" in out and "ts_delay" in out  # 窗口算子内联到顶层
    assert "close" in out


def test_inline_multi_statement_def():
    src = '''
def oi_energy(x, n):
    _e = ts_rank(ts_delta(x, 1).abs(), n)
    return sqrt(_e * (1 - _e))

signal = oi_energy(volume, 200)
'''
    out = inline_defs(src)
    assert "def oi_energy" not in out
    assert "ts_rank" in out and "sqrt" in out


def test_inline_def_calls_def():
    src = '''
def inner(x, n):
    return ts_mean(x, n)

def outer(x, n):
    return inner(x, n) * 2

signal = outer(close, 20)
'''
    out = inline_defs(src)
    assert "def inner" not in out and "def outer" not in out
    assert "ts_mean" in out


def test_inline_same_def_multiple_calls_isolated():
    src = '''
def scale_it(x, n):
    _m = ts_mean(x, n)
    return x / _m

signal = scale_it(close, 20) - scale_it(volume, 5)
'''
    out = inline_defs(src)
    # 两次调用各自实例化（变量不串、参数不串）
    assert "ts_mean" in out
    assert "ts_mean(close, 20)" in out
    assert "ts_mean(volume, 5)" in out


def test_inline_recursive_def_rejected():
    src = '''
def loop(x, n):
    return loop(x, n - 1)

signal = loop(close, 5)
'''
    with pytest.raises(FactorDSLError, match="递归"):
        inline_defs(src)


def test_inline_elementwise_def_kept_behavior():
    src = '''
def flip(x, n):
    return x * n

signal = flip(close, 2)
'''
    out = inline_defs(src)
    assert "def flip" not in out
    assert "close * 2" in out or "* 2" in out


def test_inline_no_def_unchanged():
    src = "signal = ts_mean(close, 20)"
    assert inline_defs(src) == src


# ---- 边界/错误路径 ----


def test_inline_def_without_return_rejected():
    src = '''
def f(x):
    _a = x * 2

signal = f(close)
'''
    with pytest.raises(FactorDSLError, match="必须恰有一个"):
        inline_defs(src)


def test_inline_def_multiple_returns_rejected():
    src = '''
def f(x):
    return x
    return -x

signal = f(close)
'''
    with pytest.raises(FactorDSLError, match="必须恰有一个"):
        inline_defs(src)


def test_inline_def_arg_count_mismatch():
    src = '''
def f(x, n):
    return ts_mean(x, n)

signal = f(close)
'''
    with pytest.raises(FactorDSLError, match="需要 2 个参数，实际 1 个"):
        inline_defs(src)


def test_inline_def_unsupported_statement_rejected():
    src = '''
def f(x):
    y = x * 2
    print(y)
    return y

signal = f(close)
'''
    with pytest.raises(FactorDSLError, match="仅支持赋值与 return"):
        inline_defs(src)


def test_inline_nested_def_rejected():
    src = '''
def f(x):
    def g(y):
        return y * 2
    return g(x)

signal = f(close)
'''
    with pytest.raises(FactorDSLError, match="仅支持赋值与 return"):
        inline_defs(src)


def test_inline_def_reassignment_in_body():
    # 体内中间变量重赋值：后者引用前者，不得自引用
    src = '''
def accumulate(x):
    _m = x * 2
    _m = _m + 1
    return _m

signal = accumulate(close)
'''
    out = inline_defs(src)
    assert "def accumulate" not in out
    assert "_inline_accumulate_1_0 = close * 2" in out
    assert "_inline_accumulate_1_0 + 1" in out
    assert "signal = _inline_accumulate_1_1" in out


def test_inline_def_calls_def_defined_later():
    # def 调 def 不依赖源码定义顺序
    src = '''
def outer(x, n):
    return inner(x, n) * 2

def inner(x, n):
    return ts_mean(x, n)

signal = outer(close, 20)
'''
    out = inline_defs(src)
    assert "def outer" not in out and "def inner" not in out
    assert "ts_mean(close, 20) * 2" in out


def test_inline_indirect_recursion_rejected():
    # a 调 b、b 调 a：间接递归同样拒绝
    src = '''
def a(x, n):
    return b(x, n)

def b(x, n):
    return a(x, n)

signal = a(close, 5)
'''
    with pytest.raises(FactorDSLError, match="递归"):
        inline_defs(src)


def test_inline_underscore_prefixed_def_rejected():
    # _ 前缀为中间变量约定，不允许作为 def 名（无法内联）
    src = '''
def _helper(x):
    return x * 2

signal = _helper(close)
'''
    with pytest.raises(FactorDSLError, match="下划线"):
        inline_defs(src)


def test_inline_def_default_args():
    src = '''
def sma(x, n=20):
    return ts_mean(x, n)

signal = sma(close) + sma(volume, 5)
'''
    out = inline_defs(src)
    assert "def sma" not in out
    assert "ts_mean(close, 20)" in out  # 缺省参数按默认值绑定
    assert "ts_mean(volume, 5)" in out  # 显式参数覆盖默认值


def test_inline_def_keyword_args_rejected():
    src = '''
def f(x, n):
    return ts_mean(x, n)

signal = f(x=close, n=20)
'''
    with pytest.raises(FactorDSLError, match="关键字"):
        inline_defs(src)


def test_inline_expanded_formula_executes_correctly():
    # 展开结果可直接执行：绑定、提升顺序、多次调用隔离均为真实语义
    src = '''
def scale_it(x, n):
    _m = x * 2
    return x / _m

signal = scale_it(10, 5) + scale_it(20, 5)
'''
    out = inline_defs(src)
    ns: dict = {}
    exec(out, ns)
    assert ns["signal"] == 1.0  # 10/20 + 20/40
