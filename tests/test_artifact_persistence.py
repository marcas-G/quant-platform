"""M6-05：Versioned Signal/Label Artifact Persistence。

核心 invariant：
- signal.parquet 直接来自 SignalArtifact.frame（不是 panel 派生）
- loader 绝不 fallback 到 panel.parquet
- manifest rows/columns 与实际文件一致
- format/schema version fail fast
"""

import datetime
import json

import duckdb
import polars as pl
import pytest

from factorlab.artifacts import (LABELS_FILE, LEGACY_PANEL_FILE, SIGNAL_FILE,
                                 SUMMARY_FILE, load_label_artifact,
                                 load_signal_artifact)
from factorlab.domain.timing import (DEFAULT_EOD_SIGNAL_TIMING, ExecutionTiming,
                                     InformationCutoff, SignalAvailability)
from factorlab.engine.compute import RunContext, run_factor
from factorlab.spec import load_spec


def build_db(tmp_path, n_days: int = 12) -> None:
    db = duckdb.connect(str(tmp_path / "q.duckdb"))
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, "
               "low DOUBLE, close DOUBLE, vol DOUBLE, amount DOUBLE)")
    dates = [datetime.date(2024, 1, 2) + datetime.timedelta(days=i) for i in range(n_days)]
    for code, fn in (("000001.SZ", lambda i: 10.0 + i),
                     ("000002.SZ", lambda i: 20.0 - i)):
        rows = [(code, d.strftime("%Y%m%d"), fn(i), fn(i) * 1.01, fn(i) * 0.99, fn(i),
                 1e6, fn(i) * 1e6) for i, d in enumerate(dates)]
        db.executemany("INSERT INTO daily VALUES (?,?,?,?,?,?,?,?)", rows)
    db.execute("CREATE TABLE adj_factor (ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
    for code in ("000001.SZ", "000002.SZ"):
        db.executemany("INSERT INTO adj_factor VALUES (?,?,?)",
                       [(code, d.strftime("%Y%m%d"), 1.0) for d in dates])
    db.execute("CREATE TABLE trade_cal (exchange VARCHAR, cal_date VARCHAR, is_open BIGINT)")
    db.executemany("INSERT INTO trade_cal VALUES ('SSE', ?, 1)",
                   [(d.strftime("%Y%m%d"),) for d in dates])
    db.execute("CREATE TABLE stock_basic (ts_code VARCHAR, symbol VARCHAR, exchange VARCHAR, "
               "list_date VARCHAR, industry VARCHAR, market VARCHAR, delist_date VARCHAR)")
    for code in ("000001.SZ", "000002.SZ"):
        db.execute("INSERT INTO stock_basic VALUES (?,?,?,?,?,?,?)",
                   (code, code[:6], "SZSE", "20240101", "x", "主板", None))
    db.execute("CREATE TABLE stock_st (ts_code VARCHAR, name VARCHAR, trade_date VARCHAR, "
               "type VARCHAR, type_name VARCHAR)")
    db.close()


def _spec(tmp_path, formula: str = "signal = close") -> object:
    path = tmp_path / "spec.yaml"
    path.write_text(f"""
name: demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "000002.SZ"]
date:
  start: "2024-01-02"
  end: "2024-01-17"
formula: |
  {formula}
""", encoding="utf-8")
    return load_spec(path)


def _run(tmp_path, spec, chunk_days=None):
    return run_factor(spec, RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=tmp_path / ("out_c" if chunk_days else "out"),
        float32=False, chunk_days=chunk_days, warmup_days=3))


# ================================================================
# Test A-D — core files + disk schemas
# ================================================================

def test_core_files_exist(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    out = tmp_path / "out"
    for f in (SIGNAL_FILE, LABELS_FILE, LEGACY_PANEL_FILE, SUMMARY_FILE):
        assert (out / f).exists(), f"{f} 缺失"


def test_signal_disk_schema(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    sig = pl.read_parquet(tmp_path / "out" / SIGNAL_FILE)
    assert sig.columns == ["date", "code", "signal"]
    for c in sig.columns:
        assert not (c.startswith("forward_") or c.startswith("future_")
                    or c in ("target", "label")), f"signal.parquet 含未来列 {c}"


def test_labels_disk_schema(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    lab = pl.read_parquet(tmp_path / "out" / LABELS_FILE)
    assert {"date", "code", "forward_return_5d", "forward_return_20d"} <= set(lab.columns)
    assert "signal" not in lab.columns


def test_legacy_panel_still_exists(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    panel = pl.read_parquet(tmp_path / "out" / LEGACY_PANEL_FILE)
    assert {"signal", "forward_return_5d", "forward_return_20d"} <= set(panel.columns)


# ================================================================
# Test E/F — round-trip
# ================================================================

def test_signal_roundtrip(tmp_path):
    build_db(tmp_path)
    r = _run(tmp_path, _spec(tmp_path))
    loaded = load_signal_artifact(tmp_path / "out")
    assert loaded.frame.equals(r.signal_artifact.frame)
    assert loaded.meta == r.signal_artifact.meta
    assert loaded.meta.timing == DEFAULT_EOD_SIGNAL_TIMING


def test_labels_roundtrip(tmp_path):
    build_db(tmp_path)
    r = _run(tmp_path, _spec(tmp_path))
    loaded = load_label_artifact(tmp_path / "out")
    assert loaded.frame.equals(r.label_artifact.frame)


# ================================================================
# Test G — timing manifest（来自 SignalMeta，非硬编码）
# ================================================================

def test_timing_manifest(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    summary = json.loads((tmp_path / "out" / SUMMARY_FILE).read_text(encoding="utf-8"))
    t = summary["artifacts"]["signal"]["meta"]["timing"]
    assert t == {
        "information_cutoff": InformationCutoff.CLOSE.value,
        "available_at": SignalAvailability.AFTER_CLOSE.value,
        "default_earliest_execution": ExecutionTiming.NEXT_OPEN.value,
    }
    assert t["information_cutoff"] == "close"
    assert t["available_at"] == "after_close"
    assert t["default_earliest_execution"] == "next_open"


# ================================================================
# Test H/I — manifest rows/columns == 实际文件
# ================================================================

def test_manifest_rows_match(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    out = tmp_path / "out"
    summary = json.loads((out / SUMMARY_FILE).read_text(encoding="utf-8"))
    for name, fname in (("signal", SIGNAL_FILE), ("labels", LABELS_FILE), ("panel", LEGACY_PANEL_FILE)):
        assert summary["artifacts"][name]["rows"] == pl.read_parquet(out / fname).height


def test_manifest_columns_match_order(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    out = tmp_path / "out"
    summary = json.loads((out / SUMMARY_FILE).read_text(encoding="utf-8"))
    for name, fname in (("signal", SIGNAL_FILE), ("labels", LABELS_FILE), ("panel", LEGACY_PANEL_FILE)):
        assert summary["artifacts"][name]["columns"] == pl.read_parquet(out / fname).columns


# ================================================================
# Test J-L — unsupported versions
# ================================================================

def _tamper(tmp_path, path: str, key: str, value) -> None:
    p = tmp_path / "out" / SUMMARY_FILE
    s = json.loads(p.read_text(encoding="utf-8"))
    obj = s
    for part in path.split("."):
        if part:
            obj = obj[part]
    obj[key] = value
    p.write_text(json.dumps(s), encoding="utf-8")


def test_unsupported_format_version(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _tamper(tmp_path, "", "artifact_format_version", 999)
    for loader in (load_signal_artifact, load_label_artifact):
        with pytest.raises(ValueError, match="unsupported artifact format version 999"):
            loader(tmp_path / "out")


def test_unsupported_signal_schema(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _tamper(tmp_path, "artifacts.signal", "schema_version", 999)
    with pytest.raises(ValueError, match="unsupported signal schema version 999"):
        load_signal_artifact(tmp_path / "out")


def test_unsupported_label_schema(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _tamper(tmp_path, "artifacts.labels", "schema_version", 999)
    with pytest.raises(ValueError, match="unsupported labels schema version 999"):
        load_label_artifact(tmp_path / "out")


# ================================================================
# Test M — no panel fallback
# ================================================================

def test_no_panel_fallback(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    out = tmp_path / "out"
    (out / SIGNAL_FILE).unlink()           # 删 signal、保留 panel
    assert (out / LEGACY_PANEL_FILE).exists()
    with pytest.raises(ValueError, match="signal.parquet 不存在"):
        load_signal_artifact(out)


# ================================================================
# Test N — legacy result directory
# ================================================================

def test_legacy_result_dir_no_fallback(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    out = tmp_path / "out"
    # 构造 legacy 目录：保留 panel，删 signal/labels + manifest 字段
    (out / SIGNAL_FILE).unlink()
    (out / LABELS_FILE).unlink()
    s = json.loads((out / SUMMARY_FILE).read_text(encoding="utf-8"))
    del s["artifact_format_version"]
    del s["artifacts"]
    (out / SUMMARY_FILE).write_text(json.dumps(s), encoding="utf-8")
    with pytest.raises(ValueError, match="legacy result directory does not contain"):
        load_signal_artifact(out)
    with pytest.raises(ValueError, match="legacy result directory does not contain"):
        load_label_artifact(out)


# ================================================================
# Test O — declared filename mismatch
# ================================================================

def test_declared_filename_mismatch(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _tamper(tmp_path, "artifacts.signal", "file", "../panel.parquet")
    with pytest.raises(ValueError, match="平台固定"):
        load_signal_artifact(tmp_path / "out")


# ================================================================
# Test P — CLI-style summary rewrite preserves manifest
# ================================================================

def test_cli_rewrite_preserves_manifest(tmp_path):
    build_db(tmp_path)
    r = _run(tmp_path, _spec(tmp_path))
    out = tmp_path / "out"
    # CLI 行为：追加 evaluation 后整体重写 summary.json
    r.summary["evaluation"] = {"ic": 0.01}
    (out / SUMMARY_FILE).write_text(
        json.dumps(r.summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    s = json.loads((out / SUMMARY_FILE).read_text(encoding="utf-8"))
    assert s["artifact_format_version"] == 1
    assert "artifacts" in s and s["evaluation"] == {"ic": 0.01}
    # 重写后 loader 仍可读
    loaded = load_signal_artifact(out)
    assert loaded.frame.height == r.signal_artifact.frame.height


# ================================================================
# Test Q — chunked artifacts 与内存一致
# ================================================================

def test_chunked_artifacts_match_memory(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    r = _run(tmp_path, spec, chunk_days=4)
    loaded_sig = load_signal_artifact(tmp_path / "out_c")
    loaded_lab = load_label_artifact(tmp_path / "out_c")
    assert loaded_sig.frame.equals(r.signal_artifact.frame)
    assert loaded_lab.frame.equals(r.label_artifact.frame)
