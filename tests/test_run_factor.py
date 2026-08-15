import json

import duckdb
import polars as pl
import pytest

from factorlab.engine.compute import RunContext, _formula_columns, run_factor
from factorlab.spec import load_spec


def build_db(tmp_path):
    db = duckdb.connect(tmp_path / "q.duckdb")
    db.execute("CREATE TABLE daily (date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, amount DOUBLE, turnover DOUBLE, pct_chg DOUBLE, code VARCHAR)")
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]
    for code, base in (("A", 10.0), ("B", 20.0)):
        for i, d in enumerate(dates):
            db.execute("INSERT INTO daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (d, base + i, base + i + 0.5, base + i - 0.5, base + i + 1, 1000.0, 1e6, 0.01, 0.1, code))
    db.execute("CREATE TABLE stock_basic_tushare (symbol VARCHAR, ts_code VARCHAR, exchange VARCHAR, list_date VARCHAR, industry VARCHAR)")
    db.execute("INSERT INTO stock_basic_tushare VALUES ('A', 'A.SZ', 'SZSE', '1991-01-01', '银行'), ('B', 'B.SH', 'SSE', '2001-01-01', '白酒')")
    db.execute("CREATE TABLE st_status (code VARCHAR, date DATE, is_st BOOLEAN)")
    db.close()


def _spec(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text("""
name: demo
category: custom
direction: 1
universe:
  codes: ["A.SZ", "B.SH"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
process:
  - standardize()
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    return load_spec(path)


def test_run_factor_end_to_end(tmp_path):
    build_db(tmp_path)
    out_dir = tmp_path / "out"
    result = run_factor(_spec(tmp_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=out_dir))
    panel = result.panel
    assert "signal" in panel.columns and "forward_return_5d" in panel.columns
    assert panel.height > 0
    assert (out_dir / "panel.parquet").exists()
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["name"] == "demo"
    assert summary["universe_count"] == 2
    assert summary["panel_rows"] == panel.height


def test_run_factor_empty_universe_rejected(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.universe.codes = ["999999.SZ"]  # 不存在
    with pytest.raises(ValueError, match="universe"):
        run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out2"))


def test_run_factor_float32_disabled(tmp_path):
    build_db(tmp_path)
    out_dir = tmp_path / "out"
    result = run_factor(_spec(tmp_path), RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=out_dir, float32=False))
    assert result.panel["close"].dtype == pl.Float64
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["float32"] is False


def test_run_factor_universe_override_file(tmp_path):
    build_db(tmp_path)
    pool = tmp_path / "pool_a.yaml"
    pool.write_text("codes: ['A']", encoding="utf-8")
    out_dir = tmp_path / "out"
    result = run_factor(_spec(tmp_path), RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=out_dir, universe_override=str(pool)))
    assert result.summary["universe_count"] == 1
    assert result.panel["code"].unique().to_list() == ["A"]


def test_run_factor_empty_process_chain(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.process = []  # 无 process 链：signal 保持原始值
    out_dir = tmp_path / "out"
    result = run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=out_dir))
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["process"] == []
    assert result.panel["signal"].null_count() < result.panel.height


def test_run_factor_empty_date_range_rejected(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.date.start, spec.date.end = "2020-01-01", "2020-01-31"  # 库中无此范围数据
    with pytest.raises(ValueError, match="无数据"):
        run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out3"))


def test_run_factor_formula_without_close_rejected(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.formula = "signal = open"
    with pytest.raises(ValueError, match="close"):
        run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out4"))


def test_run_factor_factors_combine_rejected(tmp_path):
    build_db(tmp_path)
    path = tmp_path / "multi.yaml"
    path.write_text("""
name: multi
category: custom
direction: 1
universe:
  codes: ["A.SZ", "B.SH"]
factors:
  - name: f1
    formula: signal = close
combine:
  method: equal_weight
""", encoding="utf-8")
    with pytest.raises(NotImplementedError, match="factors"):
        run_factor(load_spec(path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out5"))


def test_formula_columns_extracts_data_cols_only():
    formula = '''
from polars_ta.prefix.wq import ts_mean, ts_delay

def helper(x, n):
    return ts_mean(x, n)

_vol = helper(close, 20)
_mom = ts_delay(close, 1)
signal = abs(_vol) + _mom * open - if_else(close > open, 1, 0)
'''
    # def 名/参数、import 名、算子调用名、_ 前缀中间变量、signal 均排除
    assert _formula_columns(formula) == ["close", "open"]


def test_formula_columns_excludes_date_code():
    assert _formula_columns("signal = close / open - 1") == ["close", "open"]
    assert _formula_columns("signal = close / date") == ["close"]
