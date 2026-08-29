"""M6-06：Semantic Guard Closure——Label contract / manifest integrity / key alignment。

核心：M6 已建立的 Signal/Label/PIT/Artifact 边界变成不可静默绕过的 fail-fast invariants。
"""

import datetime
import json

import duckdb
import polars as pl
import pytest

from factorlab.artifacts import (FactorArtifactBundle, SIGNAL_FILE, LABELS_FILE,
                                 LEGACY_PANEL_FILE, SUMMARY_FILE,
                                 load_factor_artifacts, load_label_artifact,
                                 load_signal_artifact, validate_signal_label_alignment,
                                 write_factor_artifacts)
from factorlab.domain.frames import LabelArtifact, SignalArtifact, SignalMeta
from factorlab.domain.timing import DEFAULT_EOD_SIGNAL_TIMING
from factorlab.engine.compute import RunContext, run_factor
from factorlab.spec import load_spec


def build_db(tmp_path, n_days: int = 12) -> None:
    db = duckdb.connect(str(tmp_path / "q.duckdb"))
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, "
               "low DOUBLE, close DOUBLE, vol DOUBLE, amount DOUBLE)")
    dates = [datetime.date(2024, 1, 2) + datetime.timedelta(days=i) for i in range(n_days)]
    for code, fn in (("000001.SZ", lambda i: 10.0 + i), ("000002.SZ", lambda i: 20.0 - i)):
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


def _spec(tmp_path) -> object:
    path = tmp_path / "spec.yaml"
    path.write_text("""
name: demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "000002.SZ"]
date:
  start: "2024-01-02"
  end: "2024-01-17"
formula: |
  signal = close
""", encoding="utf-8")
    return load_spec(path)


def _run(tmp_path, spec, chunk_days=None):
    return run_factor(spec, RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=tmp_path / ("out_c" if chunk_days else "out"),
        float32=False, chunk_days=chunk_days, warmup_days=3))


def _meta(name="demo"):
    return SignalMeta(name=name, frequency="1d", timing=DEFAULT_EOD_SIGNAL_TIMING,
                      adjustment="qfq")


# ================================================================
# LabelArtifact strict contract（domain 级）
# ================================================================

def _label_frame(**extra):
    base = {
        "date": pl.Series(["2024-01-02", "2024-01-03"], dtype=pl.Date),
        "code": pl.Series(["000001", "000002"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.1, 0.2], dtype=pl.Float64),
        "forward_return_20d": pl.Series([0.3, 0.4], dtype=pl.Float64),
    }
    base.update(extra)
    return pl.DataFrame(base)


@pytest.mark.parametrize("bad_col", ["signal", "close", "open", "future_price",
                                     "__factorlab_x", "foo", "industry"])
def test_label_artifact_rejects_non_label_columns(bad_col):
    with pytest.raises(ValueError, match="不允许非 label 列"):
        LabelArtifact(frame=_label_frame(**{bad_col: pl.Series([1.0, 2.0])}))


def test_label_artifact_arbitrary_horizons_still_allowed():
    LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series(["2024-01-02"], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "forward_return_1d": pl.Series([0.1], dtype=pl.Float64),
        "forward_return_60d": pl.Series([0.2], dtype=pl.Float64),
    }))


# ================================================================
# __factorlab_* 内部列不允许落盘
# ================================================================

def _sig_frame(n=2, **extra):
    base = {
        "date": pl.Series([datetime.date(2024, 1, 2) + datetime.timedelta(days=i)
                           for i in range(n)], dtype=pl.Date),
        "code": pl.Series([f"00000{i + 1}" for i in range(n)], dtype=pl.String),
        "signal": pl.Series([0.5] * n, dtype=pl.Float64),
    }
    base.update(extra)
    return pl.DataFrame(base)


def test_internal_column_rejected_in_signal_persistence(tmp_path):
    sig = SignalArtifact(frame=_sig_frame(__factorlab_x=pl.Series([1.0, 2.0])), meta=_meta())
    lab = LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)], dtype=pl.Date),
        "code": pl.Series(["000001", "000002"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.1, 0.2], dtype=pl.Float64),
    }))
    with pytest.raises(ValueError, match="内部保留列"):
        write_factor_artifacts(tmp_path / "out", sig, lab, _sig_frame(), {})
    assert not (tmp_path / "out" / SIGNAL_FILE).exists()   # 零文件写入


def test_internal_column_rejected_in_label_domain():
    """Label 的 __factorlab_* 在 domain 构造时已被拒（contract 收紧）——
    persistence 内部列 guard 对 label 不可达（先于构造失败），由 domain 测试锁定。"""
    with pytest.raises(ValueError, match="不允许非 label 列"):
        LabelArtifact(frame=pl.DataFrame({
            "date": pl.Series([datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)], dtype=pl.Date),
            "code": pl.Series(["000001", "000002"], dtype=pl.String),
            "forward_return_5d": pl.Series([0.1, 0.2], dtype=pl.Float64),
            "__factorlab_x": pl.Series([1.0, 2.0]),
        }))


def test_internal_column_rejected_in_panel(tmp_path):
    sig = SignalArtifact(frame=_sig_frame(), meta=_meta())
    lab = LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)], dtype=pl.Date),
        "code": pl.Series(["000001", "000002"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.1, 0.2], dtype=pl.Float64),
    }))
    panel = _sig_frame(__factorlab_y=pl.Series([3.0, 4.0]))
    with pytest.raises(ValueError, match="内部保留列"):
        write_factor_artifacts(tmp_path / "out", sig, lab, panel, {})
    assert not (tmp_path / "out" / SIGNAL_FILE).exists()


# ================================================================
# Alignment（row count / key / order）
# ================================================================

def test_alignment_row_count_mismatch():
    sig = SignalArtifact(frame=_sig_frame(3), meta=_meta())
    lab = LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)], dtype=pl.Date),
        "code": pl.Series(["000001", "000002"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.1, 0.2], dtype=pl.Float64),
    }))
    with pytest.raises(ValueError, match="row count 不一致"):
        validate_signal_label_alignment(sig, lab)


def test_alignment_key_mismatch():
    sig = SignalArtifact(frame=_sig_frame(), meta=_meta())
    lab = LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)], dtype=pl.Date),
        "code": pl.Series(["000001", "000003"], dtype=pl.String),   # B → C
        "forward_return_5d": pl.Series([0.1, 0.2], dtype=pl.Float64),
    }))
    with pytest.raises(ValueError, match="key 不一致"):
        validate_signal_label_alignment(sig, lab)


def test_alignment_key_order_mismatch():
    sig = SignalArtifact(frame=_sig_frame(), meta=_meta())
    lab = LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 3), datetime.date(2024, 1, 2)], dtype=pl.Date),
        "code": pl.Series(["000002", "000001"], dtype=pl.String),   # 顺序颠倒
        "forward_return_5d": pl.Series([0.2, 0.1], dtype=pl.Float64),
    }))
    with pytest.raises(ValueError, match="key 不一致"):
        validate_signal_label_alignment(sig, lab)


def test_alignment_mismatch_zero_files_written(tmp_path):
    """pair mismatch → write_factor_artifacts 在任何文件写出前失败（零文件）。"""
    sig = SignalArtifact(frame=_sig_frame(), meta=_meta())
    lab = LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)], dtype=pl.Date),
        "code": pl.Series(["000001", "000003"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.1, 0.2], dtype=pl.Float64),
    }))
    with pytest.raises(ValueError, match="key 不一致"):
        write_factor_artifacts(tmp_path / "out", sig, lab, _sig_frame(), {})
    assert not (tmp_path / "out" / SIGNAL_FILE).exists()
    assert not (tmp_path / "out" / SUMMARY_FILE).exists()


# ================================================================
# Manifest tampering（rows / columns / horizons / meta）
# ================================================================

def _summary(tmp_path) -> dict:
    return json.loads((tmp_path / "out" / SUMMARY_FILE).read_text(encoding="utf-8"))


def _tamper(tmp_path, path: str, key: str, value) -> None:
    s = _summary(tmp_path)
    obj = s
    for part in path.split("."):
        if part:
            obj = obj[part]
    obj[key] = value
    (tmp_path / "out" / SUMMARY_FILE).write_text(json.dumps(s), encoding="utf-8")


def test_tamper_manifest_signal_rows(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _tamper(tmp_path, "artifacts.signal", "rows", 999)
    with pytest.raises(ValueError, match="signal manifest rows 999 != 实际 parquet rows"):
        load_signal_artifact(tmp_path / "out")


def test_tamper_manifest_label_rows(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _tamper(tmp_path, "artifacts.labels", "rows", 999)
    with pytest.raises(ValueError, match="labels manifest rows 999 != 实际 parquet rows"):
        load_label_artifact(tmp_path / "out")


def test_tamper_manifest_signal_columns(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _tamper(tmp_path, "artifacts.signal", "columns", ["date", "signal", "code"])
    with pytest.raises(ValueError, match="signal manifest columns"):
        load_signal_artifact(tmp_path / "out")


def test_tamper_parquet_rows(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    sig = pl.read_parquet(tmp_path / "out" / SIGNAL_FILE)
    sig.head(sig.height - 1).write_parquet(tmp_path / "out" / SIGNAL_FILE)  # 少一行，manifest 不改
    with pytest.raises(ValueError, match="signal manifest rows"):
        load_signal_artifact(tmp_path / "out")


def test_tamper_parquet_extra_column(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    sig = pl.read_parquet(tmp_path / "out" / SIGNAL_FILE)
    sig.with_columns(pl.lit(1.0).alias("extra")).write_parquet(tmp_path / "out" / SIGNAL_FILE)
    with pytest.raises(ValueError, match="signal manifest columns"):
        load_signal_artifact(tmp_path / "out")


@pytest.mark.parametrize("horizons", [[5], [5, 60], [20, 5]])
def test_tamper_label_horizons(tmp_path, horizons):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _tamper(tmp_path, "artifacts.labels", "horizons", horizons)
    with pytest.raises(ValueError, match="horizons"):
        load_label_artifact(tmp_path / "out")


# ================================================================
# Meta corrupt（清晰 ValueError，非裸 KeyError）
# ================================================================

def _del_meta(tmp_path, key: str, sub: str | None = None) -> None:
    s = _summary(tmp_path)
    meta = s["artifacts"]["signal"]["meta"]
    if sub:
        del meta["timing"][sub]
    else:
        del meta[key]
    (tmp_path / "out" / SUMMARY_FILE).write_text(json.dumps(s), encoding="utf-8")


def test_meta_missing_timing(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _del_meta(tmp_path, "timing")
    with pytest.raises(ValueError, match="signal meta 缺少字段"):
        load_signal_artifact(tmp_path / "out")


def test_meta_missing_name(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _del_meta(tmp_path, "name")
    with pytest.raises(ValueError, match="signal meta 缺少字段"):
        load_signal_artifact(tmp_path / "out")


@pytest.mark.parametrize("sub", ["information_cutoff", "available_at", "default_earliest_execution"])
def test_meta_missing_timing_subfield(tmp_path, sub):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _del_meta(tmp_path, None, sub)
    with pytest.raises(ValueError, match="signal meta timing 缺少字段"):
        load_signal_artifact(tmp_path / "out")


def test_meta_invalid_timing_enum(tmp_path):
    build_db(tmp_path)
    _run(tmp_path, _spec(tmp_path))
    _tamper(tmp_path, "artifacts.signal.meta.timing", "information_cutoff", "tomorrow")
    with pytest.raises(ValueError, match="invalid signal timing value"):
        load_signal_artifact(tmp_path / "out")


# ================================================================
# Bundle loader
# ================================================================

def test_bundle_loader(tmp_path):
    build_db(tmp_path)
    r = _run(tmp_path, _spec(tmp_path))
    bundle = load_factor_artifacts(tmp_path / "out")
    assert isinstance(bundle, FactorArtifactBundle)
    assert bundle.signal.frame.equals(r.signal_artifact.frame)
    assert bundle.labels.frame.equals(r.label_artifact.frame)
    assert not (tmp_path / "out" / LEGACY_PANEL_FILE).exists() is False  # panel 存在但 bundle 不加载


# ================================================================
# E2E Semantic Gate（run → disk → bundle 全链验证）
# ================================================================

def test_semantic_gate_e2e(tmp_path):
    build_db(tmp_path)
    r = _run(tmp_path, _spec(tmp_path), chunk_days=4)
    bundle = load_factor_artifacts(tmp_path / "out_c")
    # Signal 无未来字段（磁盘复验）
    for c in bundle.signal.frame.columns:
        assert not (c.startswith("forward_") or c.startswith("future_")
                    or c in ("target", "label"))
    # Label 无 signal/非 label 字段
    for c in bundle.labels.frame.columns:
        assert c in {"date", "code"} or c.startswith("forward_return_")
    assert "signal" not in bundle.labels.frame.columns
    # key 对齐（bundle loader 已验证——显式断言）
    assert bundle.signal.frame.select(["date", "code"]).equals(
        bundle.labels.frame.select(["date", "code"]))
    # timing
    assert bundle.signal.meta.timing == DEFAULT_EOD_SIGNAL_TIMING
    # disk round-trip
    assert bundle.signal.frame.equals(r.signal_artifact.frame)
    assert bundle.labels.frame.equals(r.label_artifact.frame)
