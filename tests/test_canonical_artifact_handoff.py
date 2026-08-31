"""M7-05：Canonical Security Identity Handoff——M6 symbol → canonical ts_code 边界。"""

import datetime
import importlib.util
from pathlib import Path

import duckdb
import polars as pl
import pytest

from factorlab.data.universe import resolve_canonical_code_map
from factorlab.domain.codes import is_canonical_stock_code
from factorlab.engine.compute import RunContext, run_factor
from factorlab.strategy import (SelectionSpec, StrategySpec, WeightingSpec,
                                build_rebalance_schedule,
                                construct_target_portfolio,
                                load_strategy_artifacts,
                                write_strategy_artifacts)


def _sb_db(tmp_path, rows):
    db = duckdb.connect(tmp_path / "m.duckdb")
    db.execute("CREATE TABLE stock_basic (symbol VARCHAR, ts_code VARCHAR)")
    db.executemany("INSERT INTO stock_basic VALUES (?, ?)", rows)
    return db


def _map(db, symbols):
    return resolve_canonical_code_map(db, symbols)


# ---------------- mapping：正常路径 ----------------

def test_mapping_exact(tmp_path):
    db = _sb_db(tmp_path, [("000001", "000001.SZ"), ("600000", "600000.SH"),
                           ("920001", "920001.BJ")])
    out = _map(db, ["000001", "600000", "920001"])
    assert out.columns == ["symbol", "code"]
    assert out["code"].to_list() == ["000001.SZ", "600000.SH", "920001.BJ"]
    assert out["symbol"].to_list() == ["000001", "600000", "920001"]


def test_mapping_input_duplicates_fail(tmp_path):
    db = _sb_db(tmp_path, [("000001", "000001.SZ")])
    with pytest.raises(ValueError, match="重复|unique"):
        _map(db, ["000001", "000001"])


def test_mapping_missing_symbol_fails(tmp_path):
    db = _sb_db(tmp_path, [("000001", "000001.SZ")])
    with pytest.raises(ValueError, match="缺失|找不到"):
        _map(db, ["000001", "999999"])


def test_mapping_duplicate_reference_fails(tmp_path):
    """同一 symbol 映射到多个 ts_code → fail（不 first/last 选择）。"""
    db = _sb_db(tmp_path, [("000001", "000001.SZ"), ("000001", "000001.SH")])
    with pytest.raises(ValueError, match="多个|重复"):
        _map(db, ["000001"])


def test_mapping_noncanonical_alias_fails(tmp_path):
    """T600018 symbol → T600018.SH（非 canonical）→ fail（不映射/不 drop）。"""
    db = _sb_db(tmp_path, [("T600018", "T600018.SH")])
    with pytest.raises(ValueError, match="canonical|非 canonical"):
        _map(db, ["T600018"])


def test_mapping_symbol_mismatch_fails(tmp_path):
    """symbol=000001 / ts_code=000002.SZ（ts_code 本身 canonical 但 row 不一致）→ fail。"""
    db = _sb_db(tmp_path, [("000001", "000002.SZ")])
    with pytest.raises(ValueError, match="row|一致|前六位"):
        _map(db, ["000001"])


# ---------------- artifact transform ----------------

def test_artifact_transform_codes_only(tmp_path):
    db = _sb_db(tmp_path, [("000001", "000001.SZ"), ("600000", "600000.SH")])
    cmap = _map(db, ["000001", "600000"])
    from factorlab.engine.compute import _canonicalize_artifact_codes
    frame = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2)] * 2, dtype=pl.Date),
        "code": pl.Series(["000001", "600000"], dtype=pl.String),
        "signal": pl.Series([1.5, 2.5], dtype=pl.Float64),
    })
    out = _canonicalize_artifact_codes(frame, cmap)
    assert out["code"].to_list() == ["000001.SZ", "600000.SH"]
    assert out["signal"].to_list() == [1.5, 2.5]   # 数值严格不变
    assert out.height == 2
    assert (out["signal"] == frame["signal"]).all()


def test_artifact_transform_label_null_mask(tmp_path):
    db = _sb_db(tmp_path, [("000001", "000001.SZ"), ("600000", "600000.SH")])
    cmap = _map(db, ["000001", "600000"])
    from factorlab.engine.compute import _canonicalize_artifact_codes
    frame = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2)] * 2, dtype=pl.Date),
        "code": pl.Series(["600000", "000001"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.01, None], dtype=pl.Float64),
        "forward_return_20d": pl.Series([None, 0.05], dtype=pl.Float64),
    })
    out = _canonicalize_artifact_codes(frame, cmap)
    assert out["code"].to_list() == ["000001.SZ", "600000.SH"]   # canonical 排序
    assert out["forward_return_5d"].null_count() == 1
    assert out["forward_return_20d"].null_count() == 1


def test_artifact_transform_missing_symbol_fails(tmp_path):
    db = _sb_db(tmp_path, [("000001", "000001.SZ")])
    cmap = _map(db, ["000001"])
    from factorlab.engine.compute import _canonicalize_artifact_codes
    frame = pl.DataFrame({"date": pl.Series([datetime.date(2024, 1, 2)], dtype=pl.Date),
                          "code": pl.Series(["999999"], dtype=pl.String),
                          "signal": pl.Series([1.0], dtype=pl.Float64)})
    with pytest.raises(ValueError):
        _canonicalize_artifact_codes(frame, cmap)


def test_artifact_transform_mapping_collision_fails(tmp_path):
    """两个 symbol → 同一 canonical code（人工 cmap 模拟）→ (date, code) 碰撞
    fail（不 dedup）。注：合法 mapping 下 row 一致性保证一一对应——碰撞 guard
    是 transform 层防御。"""
    cmap = pl.DataFrame({"symbol": ["000001", "000002"],
                         "code": ["000001.SZ", "000001.SZ"]})
    from factorlab.engine.compute import _canonicalize_artifact_codes
    frame = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2)] * 2, dtype=pl.Date),
        "code": pl.Series(["000001", "000002"], dtype=pl.String),
        "signal": pl.Series([1.0, 2.0], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="重复|unique"):
        _canonicalize_artifact_codes(frame, cmap)


# ---------------- 真实 M6→M7 集成 ----------------

def _platform_db(tmp_path):
    """平台库风格 fixture（stock_basic 含 symbol+ts_code 双列，canonical）。"""
    spec_loader = importlib.util.spec_from_file_location(
        "trf", str(Path("tests/test_run_factor.py")))
    mod = importlib.util.module_from_spec(spec_loader)
    spec_loader.loader.exec_module(mod)
    mod.build_db(tmp_path, n_days=10)
    # build_db 的 stock_basic 是 (symbol, ts_code, ...) 列——确认含双列
    return mod, tmp_path


def _factor_spec(tmp_path, mod):
    p = tmp_path / "spec.yaml"
    p.write_text("""
name: handoff_demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
adjustment: qfq
formula: |
  signal = close
process: []
""", encoding="utf-8")
    from factorlab.spec import load_spec
    return load_spec(p)


def test_real_run_factor_to_strategy_chain(tmp_path):
    """核心 Gate：run_factor → construct_target_portfolio → schedule → persistence。"""
    mod, td = _platform_db(tmp_path)
    spec = _factor_spec(td, mod)
    result = run_factor(spec, RunContext(db_path=td / "q.duckdb",
                                         output_dir=td / "out"))
    # SignalArtifact code 全部 canonical
    codes = result.signal_artifact.frame["code"].to_list()
    assert codes, "signal 为空"
    assert all(is_canonical_stock_code(c) for c in codes), codes
    # labels 同样 canonical + 与 signal key-aligned
    assert all(is_canonical_stock_code(c) for c in result.label_artifact.frame["code"].to_list())
    assert result.signal_artifact.frame.select(["date", "code"]).equals(
        result.label_artifact.frame.select(["date", "code"]))
    # panel 同 namespace
    assert all(is_canonical_stock_code(c) for c in result.panel["code"].to_list())
    # summary.codes canonical
    assert all(is_canonical_stock_code(c) for c in result.summary["codes"])
    # M7 链
    strategy = StrategySpec(
        name="handoff_strategy", signal_name=result.signal_artifact.meta.name,
        direction=1,
        selection=SelectionSpec(k=2),
        weighting=WeightingSpec())
    target = construct_target_portfolio(result.signal_artifact, strategy)
    assert all(is_canonical_stock_code(c) for c in target.frame["code"].to_list())
    schedule = build_rebalance_schedule(result.signal_artifact, strategy)
    out_dir = td / "strat"
    write_strategy_artifacts(out_dir, source_signal=result.signal_artifact,
                             spec=strategy, schedule=schedule, target=target)
    bundle = load_strategy_artifacts(out_dir)
    assert bundle.target.frame.equals(target.frame)
    assert bundle.target.meta == target.meta


def test_summary_counts_unchanged(tmp_path):
    mod, td = _platform_db(tmp_path)
    spec = _factor_spec(td, mod)
    result = run_factor(spec, RunContext(db_path=td / "q.duckdb",
                                         output_dir=td / "out2"))
    assert result.summary["candidate_count"] == 2
    assert result.summary["universe_count"] == 2
