import polars as pl

from factorlab.engine.compute import compute_formula


def test_compute_formula_returns_signal_column():
    df = pl.DataFrame({
        "date": ["2020-01-01", "2020-01-01", "2020-01-01"],
        "code": ["A", "B", "C"],
        "close": [10.0, 20.0, 30.0],
        "open": [9.0, 19.0, 29.0],
    })
    formula = '''
from polars_ta.prefix.wq import ts_delay
signal = ts_delay(close, 1)
'''
    result = compute_formula(df, formula)
    assert result.columns == ["date", "code", "signal"]
    assert result.height == 3
    assert result["signal"].null_count() == 3


def test_compute_formula_supports_def_and_ternary():
    df = pl.DataFrame({
        "date": ["2020-01-02", "2020-01-03"],
        "code": ["A", "A"],
        "close": [10.0, 12.0],
        "open": [9.0, 13.0],
    })
    formula = '''
from polars_ta.prefix.wq import ts_delay

def momentum(x, n):
    return ts_delay(x, n) / ts_delay(x, 2 * n) - 1

_m = momentum(close, 1)
signal = _m if _m > 0 else -_m
'''
    result = compute_formula(df, formula)
    assert result.columns == ["date", "code", "signal"]
    assert result.height == 2
