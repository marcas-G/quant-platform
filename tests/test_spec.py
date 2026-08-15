import pytest
import yaml

from factorlab.spec import FactorSpec, load_spec


def make_spec(tmp_path, **overrides):
    data = {
        "name": "demo_factor",
        "category": "custom",
        "direction": 1,
        "universe": {"codes": ["000001.SZ", "600519.SH"]},
        "date": {"start": "2020-01-01", "end": "2021-01-01"},
        "formula": "signal = close / open - 1",
    }
    data.update(overrides)
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_load_valid_spec(tmp_path):
    spec = load_spec(make_spec(tmp_path))
    assert spec.name == "demo_factor"
    assert spec.universe.codes == ["000001.SZ", "600519.SH"]


def test_rejects_missing_direction(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(tmp_path, direction=None))


def test_rejects_universe_both_codes_and_rules(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(tmp_path, universe={"codes": ["000001.SZ"], "rules": {"exclude_st": True}}))


def test_rejects_formula_and_factors_together(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(
            tmp_path,
            factors=[{"name": "a", "formula": "signal = close"}],
            combine={"method": "equal_weight"},
        ))


def test_load_valid_factors_and_combine(tmp_path):
    path = make_spec(
        tmp_path,
        formula=None,
        factors=[
            {"name": "a", "formula": "signal = close / open - 1"},
            {"name": "b", "formula": "signal = close - open"},
        ],
        combine={"method": "equal_weight"},
    )
    spec = load_spec(path)
    assert len(spec.factors) == 2
    assert spec.combine.method == "equal_weight"


def test_rejects_invalid_date_format(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(tmp_path, date={"start": "2020/01/01"}))


def test_rejects_weight_sum_without_weights(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(
            tmp_path,
            formula=None,
            factors=[{"name": "a", "formula": "signal = close"}],
            combine={"method": "weight_sum"},
        ))


def test_rejects_weight_sum_length_mismatch(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(
            tmp_path,
            formula=None,
            factors=[
                {"name": "a", "formula": "signal = close"},
                {"name": "b", "formula": "signal = open"},
            ],
            combine={"method": "weight_sum", "weights": [0.5]},
        ))
