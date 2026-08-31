"""M7-04：Strategy Artifact Persistence——write/load round-trip + tamper 检测。"""

import datetime
import json

import polars as pl
import pytest

from factorlab.domain.frames import SignalArtifact, SignalMeta
from factorlab.domain.timing import DEFAULT_EOD_SIGNAL_TIMING
from factorlab.strategy import (SelectionSpec, StrategySpec, WeightingSpec,
                                construct_target_portfolio)
from factorlab.strategy.artifacts import (REBALANCE_SCHEDULE_FILE,
                                          STRATEGY_ARTIFACT_FORMAT_VERSION,
                                          STRATEGY_MANIFEST_FILE,
                                          STRATEGY_SPEC_SCHEMA_VERSION,
                                          TARGET_PORTFOLIO_FILE,
                                          TARGET_PORTFOLIO_SCHEMA_VERSION,
                                          REBALANCE_SCHEDULE_SCHEMA_VERSION,
                                          StrategyArtifactBundle,
                                          load_rebalance_schedule,
                                          load_strategy_artifacts,
                                          load_strategy_spec,
                                          load_target_portfolio,
                                          write_strategy_artifacts)
from factorlab.strategy.schedule import RebalanceSchedule, build_rebalance_schedule

D1, D2, D3 = (datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
              datetime.date(2024, 1, 4))


def _signal(name="alpha_x", adjustment="qfq"):
    f = pl.DataFrame({"date": pl.Series([D1, D1, D2, D2, D3, D3], dtype=pl.Date),
                      "code": pl.Series(["000001.SZ", "600000.SH"] * 3, dtype=pl.String),
                      "signal": pl.Series([10.0, 20.0, 30.0, 40.0, 5.0, 8.0],
                                          dtype=pl.Float64)})
    return SignalArtifact(frame=f, meta=SignalMeta(
        name=name, frequency="1d", timing=DEFAULT_EOD_SIGNAL_TIMING,
        adjustment=adjustment))


def _spec(**over):
    base = {"name": "strategy_x", "signal_name": "alpha_x", "direction": 1,
            "selection": {"method": "top_k", "k": 2},
            "weighting": {"method": "equal_weight"}}
    base.update(over)
    return StrategySpec.model_validate(base)


def _full_set(tmp_path, freq="daily", signal=None):
    sa = signal if signal is not None else _signal()
    spec = _spec(rebalance_frequency=freq)
    schedule = build_rebalance_schedule(sa, spec)
    target = construct_target_portfolio(sa, spec)
    return sa, spec, schedule, target


def _write(tmp_path, **kw):
    return write_strategy_artifacts(tmp_path, **kw)


def _manifest(tmp_path):
    return json.loads((tmp_path / STRATEGY_MANIFEST_FILE).read_text(encoding="utf-8"))


# ---------------- 常量 / 基础写入 ----------------

def test_constants():
    assert STRATEGY_ARTIFACT_FORMAT_VERSION == 1
    assert TARGET_PORTFOLIO_SCHEMA_VERSION == 1
    assert REBALANCE_SCHEDULE_SCHEMA_VERSION == 1
    assert STRATEGY_SPEC_SCHEMA_VERSION == 1


@pytest.mark.parametrize("freq", ["daily", "weekly", "monthly"])
def test_valid_write(tmp_path, freq):
    sa, spec, schedule, target = _full_set(tmp_path, freq)
    manifest = _write(tmp_path, source_signal=sa, spec=spec,
                      schedule=schedule, target=target)
    assert (tmp_path / TARGET_PORTFOLIO_FILE).exists()
    assert (tmp_path / REBALANCE_SCHEDULE_FILE).exists()
    assert (tmp_path / STRATEGY_MANIFEST_FILE).exists()
    assert manifest["strategy_artifact_format_version"] == 1


def test_no_summary_or_signal_copy(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    files = {p.name for p in tmp_path.iterdir()}
    assert "summary.json" not in files
    assert "signal.parquet" not in files
    assert "labels.parquet" not in files
    assert "panel.parquet" not in files
    assert files == {TARGET_PORTFOLIO_FILE, REBALANCE_SCHEDULE_FILE,
                     STRATEGY_MANIFEST_FILE}


# ---------------- writer type guards ----------------

def test_wrong_source_signal_type(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        _write(tmp_path, source_signal=pl.DataFrame(), spec=spec,
               schedule=schedule, target=target)


def test_wrong_spec_type(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        _write(tmp_path, source_signal=sa, spec={"name": "x"},
               schedule=schedule, target=target)


def test_wrong_schedule_type(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        _write(tmp_path, source_signal=sa, spec=spec,
               schedule=(D1,), target=target)


def test_wrong_target_type(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        _write(tmp_path, source_signal=sa, spec=spec,
               schedule=schedule, target=target.frame)


# ---------------- cross-object invariants ----------------

def test_source_spec_name_mismatch(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    sa2 = _signal(name="alpha_b")
    with pytest.raises(ValueError, match="signal_name"):
        _write(tmp_path, source_signal=sa2, spec=spec,
               schedule=schedule, target=target)


def test_source_schedule_name_mismatch(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    schedule2 = RebalanceSchedule(decision_dates=schedule.decision_dates,
                                  frequency=schedule.frequency,
                                  source_signal_name="alpha_b")
    with pytest.raises(ValueError):
        _write(tmp_path, source_signal=sa, spec=spec,
               schedule=schedule2, target=target)


def test_spec_schedule_frequency_mismatch(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    schedule2 = RebalanceSchedule(decision_dates=schedule.decision_dates,
                                  frequency="weekly",
                                  source_signal_name=schedule.source_signal_name)
    with pytest.raises(ValueError, match="frequency"):
        _write(tmp_path, source_signal=sa, spec=spec,
               schedule=schedule2, target=target)


def test_target_schedule_dates_mismatch(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    from factorlab.domain import TargetPortfolio
    # frame 只含 D1/D2（domain 可构造），但 schedule 含 D3——writer cross-check 拦截
    f2 = target.frame.filter(pl.col("decision_date") != D3)
    t2 = TargetPortfolio(frame=f2, decision_dates=(D1, D2), meta=target.meta)
    with pytest.raises(ValueError, match="decision_dates"):
        _write(tmp_path, source_signal=sa, spec=spec,
               schedule=schedule, target=t2)


def test_target_spec_strategy_name_mismatch(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    from factorlab.domain import TargetPortfolioMeta
    m2 = TargetPortfolioMeta(strategy_name="other", source_signal_name="alpha_x",
                             source_timing=DEFAULT_EOD_SIGNAL_TIMING,
                             gross_exposure=1.0)
    t2 = target.frame  # 保持 frame
    from factorlab.domain import TargetPortfolio
    t2 = TargetPortfolio(frame=target.frame, decision_dates=target.decision_dates, meta=m2)
    with pytest.raises(ValueError, match="strategy_name"):
        _write(tmp_path, source_signal=sa, spec=spec,
               schedule=schedule, target=t2)


def test_gross_mismatch(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    from factorlab.domain import TargetPortfolio, TargetPortfolioMeta
    m2 = TargetPortfolioMeta(strategy_name="strategy_x", source_signal_name="alpha_x",
                             source_timing=DEFAULT_EOD_SIGNAL_TIMING,
                             gross_exposure=0.8)
    f2 = target.frame.with_columns((pl.col("target_weight") * 0.8).alias("target_weight"))
    t2 = TargetPortfolio(frame=f2, decision_dates=target.decision_dates, meta=m2)
    with pytest.raises(ValueError, match="gross"):
        _write(tmp_path, source_signal=sa, spec=spec,
               schedule=schedule, target=t2)


def test_failure_before_write_zero_files(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    sa2 = _signal(name="alpha_b")
    with pytest.raises(ValueError):
        _write(tmp_path, source_signal=sa2, spec=spec,
               schedule=schedule, target=target)
    assert list(tmp_path.iterdir()) == []


# ---------------- manifest content ----------------

def test_manifest_stores_full_spec(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path, freq="weekly")
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    assert m["strategy_spec"]["value"]["name"] == "strategy_x"
    assert m["strategy_spec"]["value"]["rebalance_frequency"] == "weekly"
    assert m["strategy_spec"]["value"]["selection"]["k"] == 2


def test_manifest_source_signal_provenance(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    ss = m["source_signal"]
    assert ss["name"] == "alpha_x"
    assert ss["frequency"] == "1d"
    assert ss["adjustment"] == "qfq"
    assert ss["timing"] == {"information_cutoff": "close",
                            "available_at": "after_close",
                            "default_earliest_execution": "next_open"}


def test_manifest_adjustment_null(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    sa2 = _signal(adjustment=None)
    spec2 = _spec()
    sch2 = build_rebalance_schedule(sa2, spec2)
    tgt2 = construct_target_portfolio(sa2, spec2)
    _write(tmp_path, source_signal=sa2, spec=spec2, schedule=sch2, target=tgt2)
    assert _manifest(tmp_path)["source_signal"]["adjustment"] is None


def test_manifest_target_meta(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path, freq="weekly")
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    tm = m["artifacts"]["target_portfolio"]["meta"]
    assert tm["strategy_name"] == "strategy_x"
    assert tm["source_signal_name"] == "alpha_x"
    assert tm["signal_frequency"] == "1d"
    assert tm["rebalance_frequency"] == "weekly"
    assert tm["gross_exposure"] == 1.0


# ---------------- round-trip ----------------

@pytest.mark.parametrize("freq", ["daily", "weekly", "monthly"])
def test_round_trip(tmp_path, freq):
    sa, spec, schedule, target = _full_set(tmp_path, freq)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    bundle = load_strategy_artifacts(tmp_path)
    assert bundle.spec == spec
    assert bundle.schedule == schedule
    assert bundle.target.frame.equals(target.frame)
    assert bundle.target.decision_dates == target.decision_dates
    assert bundle.target.meta == target.meta


def test_single_loaders(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path, freq="monthly")
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    assert load_strategy_spec(tmp_path) == spec
    assert load_rebalance_schedule(tmp_path) == schedule
    tp = load_target_portfolio(tmp_path)
    assert tp.frame.equals(target.frame)
    assert tp.decision_dates == target.decision_dates


def test_all_cash_preserved(tmp_path):
    """D2 全 null → 0 rows，round-trip 后 decision date 不丢失。"""
    f = pl.DataFrame({"date": pl.Series([D1, D1, D2, D2, D3, D3], dtype=pl.Date),
                      "code": pl.Series(["000001.SZ", "600000.SH"] * 3, dtype=pl.String),
                      "signal": pl.Series([10.0, 20.0, None, None, 5.0, 8.0],
                                          dtype=pl.Float64)})
    sa = _signal(); sa = SignalArtifact(frame=f, meta=sa.meta)
    spec = _spec()
    schedule = build_rebalance_schedule(sa, spec)
    target = construct_target_portfolio(sa, spec)
    assert D2 in target.decision_dates and target.frame.filter(
        pl.col("decision_date") == D2).height == 0
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    bundle = load_strategy_artifacts(tmp_path)
    assert D2 in bundle.target.decision_dates
    assert bundle.target.frame.filter(pl.col("decision_date") == D2).height == 0


def test_empty_round_trip(tmp_path):
    f = pl.DataFrame({"date": pl.Series([], dtype=pl.Date),
                      "code": pl.Series([], dtype=pl.String),
                      "signal": pl.Series([], dtype=pl.Float64)})
    sa = SignalArtifact(frame=f, meta=SignalMeta(
        name="alpha_x", frequency="1d", timing=DEFAULT_EOD_SIGNAL_TIMING,
        adjustment="qfq"))
    spec = _spec()
    schedule = build_rebalance_schedule(sa, spec)
    target = construct_target_portfolio(sa, spec)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    sch = pl.read_parquet(tmp_path / REBALANCE_SCHEDULE_FILE)
    assert sch.schema["decision_date"] == pl.Date and sch.height == 0
    bundle = load_strategy_artifacts(tmp_path)
    assert bundle.schedule.decision_dates == ()
    assert bundle.target.frame.height == 0


# ---------------- tamper 检测 ----------------

def test_missing_manifest(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    (tmp_path / STRATEGY_MANIFEST_FILE).unlink()
    with pytest.raises(ValueError, match="manifest"):
        load_strategy_artifacts(tmp_path)


@pytest.mark.parametrize("bad", [True, 1.0, "1", 0, -1, None])
def test_invalid_format_version(tmp_path, bad):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    m["strategy_artifact_format_version"] = bad
    (tmp_path / STRATEGY_MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="format_version"):
        load_strategy_artifacts(tmp_path)


def test_unsupported_format_version(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    m["strategy_artifact_format_version"] = 2
    (tmp_path / STRATEGY_MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        load_strategy_artifacts(tmp_path)


@pytest.mark.parametrize("which", ["target_portfolio", "rebalance_schedule"])
def test_invalid_schema_version(tmp_path, which):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    m["artifacts"][which]["schema_version"] = "1"
    (tmp_path / STRATEGY_MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        load_strategy_artifacts(tmp_path)


def test_fixed_filename_tamper(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    m["artifacts"]["target_portfolio"]["file"] = "other.parquet"
    (tmp_path / STRATEGY_MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="file"):
        load_strategy_artifacts(tmp_path)


def test_target_rows_tamper(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    m["artifacts"]["target_portfolio"]["rows"] += 1
    (tmp_path / STRATEGY_MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="rows"):
        load_strategy_artifacts(tmp_path)


def test_target_columns_tamper(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    m["artifacts"]["target_portfolio"]["columns"].append("foo")
    (tmp_path / STRATEGY_MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="columns"):
        load_strategy_artifacts(tmp_path)


def test_schedule_dtype_tamper(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    sch = pl.DataFrame({"decision_date": ["2024-01-02"]}, schema={"decision_date": pl.String})
    sch.write_parquet(tmp_path / REBALANCE_SCHEDULE_FILE)
    with pytest.raises(ValueError):
        load_strategy_artifacts(tmp_path)


def test_schedule_rows_tamper(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    m["artifacts"]["rebalance_schedule"]["rows"] -= 1
    (tmp_path / STRATEGY_MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="rows"):
        load_strategy_artifacts(tmp_path)


def test_spec_k_tamper(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    m["strategy_spec"]["value"]["selection"]["k"] = 0
    (tmp_path / STRATEGY_MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError):
        load_strategy_artifacts(tmp_path)


def test_spec_extra_target_field_tamper(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    m["strategy_spec"]["value"]["target"] = "forward_return_5d"
    (tmp_path / STRATEGY_MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError):
        load_strategy_artifacts(tmp_path)


def test_target_parquet_extra_column_tamper(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    t = pl.read_parquet(tmp_path / TARGET_PORTFOLIO_FILE)
    t.with_columns(pl.lit(1.0).alias("forward_return_5d")).write_parquet(
        tmp_path / TARGET_PORTFOLIO_FILE)
    with pytest.raises(ValueError):
        load_strategy_artifacts(tmp_path)


def test_source_timing_invalid(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    m = _manifest(tmp_path)
    m["source_signal"]["timing"]["available_at"] = "tomorrow"
    (tmp_path / STRATEGY_MANIFEST_FILE).write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError):
        load_strategy_artifacts(tmp_path)


# ---------------- strategy-safe ----------------

def test_unrelated_labels_panel_ignored(tmp_path):
    sa, spec, schedule, target = _full_set(tmp_path)
    _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    pl.DataFrame({"date": [D1], "code": ["000001.SZ"],
                  "forward_return_5d": [0.01]}).write_parquet(tmp_path / "labels.parquet")
    pl.DataFrame({"date": [D1], "code": ["000001.SZ"],
                  "signal": [1.0]}).write_parquet(tmp_path / "panel.parquet")
    bundle = load_strategy_artifacts(tmp_path)
    assert bundle.target.frame.equals(target.frame)


def test_bundle_frozen():
    sa, spec, schedule, target = _full_set(tmp_path=None)
    b = StrategyArtifactBundle(spec=spec, schedule=schedule, target=target)
    with pytest.raises(Exception):
        b.spec = spec


def test_manifest_written_last(tmp_path, monkeypatch):
    """manifest 写失败（模拟核心文件写成功后的失败）→ manifest 不存在。"""
    sa, spec, schedule, target = _full_set(tmp_path)
    from factorlab.strategy import artifacts as A
    def boom(path, writer):
        raise RuntimeError("manifest boom")
    monkeypatch.setattr(A, "_write_text", boom)
    with pytest.raises(RuntimeError):
        _write(tmp_path, source_signal=sa, spec=spec, schedule=schedule, target=target)
    assert not (tmp_path / STRATEGY_MANIFEST_FILE).exists()
    assert (tmp_path / TARGET_PORTFOLIO_FILE).exists()
    assert (tmp_path / REBALANCE_SCHEDULE_FILE).exists()
