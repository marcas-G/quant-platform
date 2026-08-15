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


def _panel():
    return pl.DataFrame({
        "date": ["2024-01-02"] * 4 + ["2024-01-03"] * 4,
        "code": ["A", "B", "C", "D"] * 2,
        "signal": [1.0, 2.0, 3.0, 100.0, 1.0, 2.0, 3.0, 4.0],
    })


def test_winsorize_clips_extremes():
    out = run_process_chain(_panel(), ["winsorize(quantile=0.5)"], ctx=None)
    assert out["signal"].max() < 100.0


def test_standardize_cross_section():
    out = run_process_chain(_panel(), ["standardize()"], ctx=None)
    per_date = out.group_by("date").agg(
        mean=pl.col("signal").mean(),
        std=pl.col("signal").std(),
    )
    assert per_date["mean"].abs().max() < 1e-9
    assert per_date["std"].abs().max() > 0.9


def test_csranknorm_in_unit_interval():
    out = run_process_chain(_panel(), ["csranknorm()"], ctx=None)
    assert out["signal"].min() > 0.0 and out["signal"].max() < 1.0  # rank/(N+1) 最大 N/(N+1) < 1


def test_robustzscore_bounds_extremes():
    out = run_process_chain(_panel(), ["robustzscore()"], ctx=None)
    # 01-02 截面 [1,2,3,100]：中位数 2.5、MAD 1.0，极端值 100.0 → 稳健 z ≈ 65.8
    # （标准 MAD 公式下 <10 在数学上不可能）；断言极端值仍远小于原始幅度、其余在 ±1 附近
    abs_sig = out["signal"].abs()
    assert abs_sig.max() < 100.0
    assert abs_sig.filter(abs_sig < abs_sig.max()).max() < 1.1


def test_clip_bounds():
    out = run_process_chain(_panel(), ["clip(-1, 1)"], ctx=None)
    assert out["signal"].min() >= -1.0 and out["signal"].max() <= 1.0


def test_fillna_value():
    df = _panel().with_columns(pl.when(pl.col("code") == "D").then(None).otherwise(pl.col("signal")).alias("signal"))
    out = run_process_chain(df, ["fillna(method=value, value=0.0)"], ctx=None)
    assert out["signal"].null_count() == 0
    assert out.filter(pl.col("code") == "D")["signal"].to_list() == [0.0, 0.0]


def test_fillna_forward_within_asset():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        "code": ["A", "A", "A", "A"],
        "signal": [1.0, None, 3.0, None],
    })
    out = run_process_chain(df, ["fillna(method=forward)"], ctx=None)
    assert out["signal"].to_list() == [1.0, 1.0, 3.0, 3.0]


def test_fillna_invalid_method():
    with pytest.raises(ValueError, match="fillna"):
        run_process_chain(_panel(), ["fillna(method=bogus)"], ctx=None)


def test_parse_chain_item_colon_separator():
    assert parse_chain_item("neutralize(by: industry)") == ("neutralize", {"by": "industry"})


def test_parse_chain_item_bad_key_rejected():
    with pytest.raises(ValueError):
        parse_chain_item("clip(=3)")


def test_parse_chain_item_keyword_before_positional_rejected():
    with pytest.raises(ValueError):
        parse_chain_item("clip(upper=3, -3)")


def test_run_chain_requires_signal_column():
    df = pl.DataFrame({"date": ["2024-01-02"], "code": ["A"]})
    with pytest.raises(ValueError, match="signal"):
        run_process_chain(df, ["standardize()"], ctx=None)


def test_fillna_forward_no_cross_asset_leak():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
        "code": ["A", "A", "B", "B"],
        "signal": [1.0, None, None, 4.0],
    })
    out = run_process_chain(df, ["fillna(method=forward)"], ctx=None)
    assert out.filter(pl.col("code") == "A")["signal"].to_list() == [1.0, 1.0]
    assert out.filter(pl.col("code") == "B")["signal"].to_list() == [None, 4.0]  # B 首行不借用 A


def test_zscore_alias_registered():
    assert get_processor("zscore").name == "zscore"


def test_winsorize_rejects_quantile_one():
    with pytest.raises(ValueError):
        run_process_chain(_panel(), ["winsorize(quantile=1.0)"], ctx=None)


def test_standardize_null_preserved_for_constant_section():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
        "code": ["A", "B", "A", "B"],
        "signal": [5.0, 5.0, 1.0, 2.0],
    })
    out = run_process_chain(df, ["standardize()"], ctx=None)
    a2 = out.filter((pl.col("code") == "A") & (pl.col("date") == "2024-01-02"))["signal"]
    assert a2.to_list() == [None]  # 01-02 截面零方差 → null
    assert out["signal"].drop_nulls().len() == 2


def test_robustzscore_null_for_mad_zero_section():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
        "code": ["A", "B", "C", "A", "B"],
        "signal": [5.0, 5.0, 5.0, 1.0, 2.0],
    })
    out = run_process_chain(df, ["robustzscore()"], ctx=None)
    sec1 = out.filter(pl.col("date") == "2024-01-02")["signal"]
    assert sec1.to_list() == [None, None, None]  # MAD=0 截面 → null（不产生 inf）
    assert out["signal"].drop_nulls().len() == 2  # 01-03 截面 [1,2] MAD>0 → 有值
