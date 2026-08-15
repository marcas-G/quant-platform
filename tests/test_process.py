import polars as pl
import pytest

from factorlab.process.registry import get_processor, parse_chain_item, run_process_chain
from factorlab.process import processors  # noqa: F401  # 注册副作用


def test_parse_chain_item_keyword():
    assert parse_chain_item("winsorize(quantile=0.99)") == ("winsorize", {"quantile": 0.99})


def test_parse_chain_item_no_args():
    assert parse_chain_item("standardize()") == ("standardize", {})


def test_parse_chain_item_positional_and_types():
    name, kwargs = parse_chain_item("clip(-3, 3)")
    assert name == "clip" and kwargs["lower"] == -3.0 and kwargs["upper"] == 3.0


def test_parse_chain_item_edges():
    # bool/字符串字面量
    assert parse_chain_item("foo(flag=true, name=abc)") == ("foo", {"flag": True, "name": "abc"})
    # key=value 与位置参数混用（位置参数按序命名 lower/upper/value）
    assert parse_chain_item("clip(-3, upper=3)") == ("clip", {"lower": -3, "upper": 3})
    # 无括号裸名视为无参
    assert parse_chain_item("winsorize") == ("winsorize", {})
    # 多余逗号（空参数段）拒绝
    with pytest.raises(ValueError):
        parse_chain_item("clip(-3, 3,)")
    # 纯空白项拒绝
    with pytest.raises(ValueError):
        parse_chain_item("   ")


def test_parse_chain_item_invalid():
    with pytest.raises(ValueError):
        parse_chain_item("winsorize(quantile=")


def test_unknown_processor_rejected():
    with pytest.raises(KeyError, match="nope"):
        get_processor("nope")


def test_run_chain_applies_sequentially():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
        "code": ["A", "B", "A", "B"],
        "signal": [1.0, 1000.0, 2.0, 3.0],
    })
    out = run_process_chain(df, ["winsorize(quantile=0.5)", "standardize()"], ctx=None)
    assert out.columns == ["date", "code", "signal"]
    assert out["signal"].abs().max() < 5  # 去极值后 z-score 有界
