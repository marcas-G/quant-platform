import pytest

from factorlab.factor.ast_gate import validate_formula
from factorlab.factor.errors import FactorDSLError


def test_allows_def_import_assignment_and_ternary():
    source = '''
from polars_ta.prefix.wq import ts_delay, ts_mean

def mom(x, n):
    return ts_delay(x, n) / ts_delay(x, 2 * n) - 1

_m = ts_mean(close, 20)
signal = _m if _m > 0 else -_m
'''
    validate_formula(source)


def test_rejects_for_loop():
    with pytest.raises(FactorDSLError):
        validate_formula("for i in range(10):\n    pass\n")


def test_rejects_os_import():
    with pytest.raises(FactorDSLError):
        validate_formula("import os\nsignal = close\n")


def test_rejects_eval_call():
    with pytest.raises(FactorDSLError):
        validate_formula("signal = eval('close')\n")
