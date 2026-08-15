import json

import polars as pl
import pytest

from factorlab.engine.compute import RunContext, run_factor
from factorlab.spec import load_spec


@pytest.mark.integration
def test_e2e_small_universe(real_db_path, tmp_path):
    spec_path = tmp_path / "e2e.yaml"
    spec_path.write_text("""
name: e2e_vol_skew
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH", "000002.SZ", "600036.SH", "601318.SH"]
date:
  start: "2024-01-01"
  end: "2025-12-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
  - neutralize(by=market)
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_std_dev, ts_delay
  _ret = ts_delay(close, 1)
  _vol = ts_std_dev(_ret, 20)
  _mom = ts_mean(close, 20)
  signal = -_vol + ts_delay(_mom, 1)
""", encoding="utf-8")
    out_dir = tmp_path / "out"
    spec = load_spec(spec_path)
    result = run_factor(spec, RunContext(db_path=real_db_path, output_dir=out_dir))

    panel = result.panel
    assert panel.height > 0
    assert panel.columns == ["date", "code", "signal", "forward_return_5d", "forward_return_20d", "close"]
    assert panel["date"].dtype == pl.Date
    assert (out_dir / "panel.parquet").exists()
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["name"] == "e2e_vol_skew"
    assert summary["universe_count"] == 5
    assert summary["signal_null_ratio"] < 0.5


@pytest.mark.integration
def test_e2e_rules_universe(real_db_path, tmp_path):
    spec_path = tmp_path / "e2e_rules.yaml"
    spec_path.write_text("""
name: e2e_rules
category: custom
direction: -1
universe:
  rules: {exclude_st: true, exchanges: ["SSE"]}
date:
  start: "2024-01-01"
  end: "2024-03-31"
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    spec = load_spec(spec_path)
    result = run_factor(spec, RunContext(db_path=real_db_path, output_dir=tmp_path / "out2"))
    assert result.panel.height > 0


@pytest.mark.integration
def test_e2e_neutralize_size(real_db_path, tmp_path):
    # 回归：neutralize(by=size) 在真实库跑通不崩（原实现全表拉取 daily_basic 1714 万行，
    # 16GB 机器段错误 exit 139）；回归目标是崩溃/段错误，不是统计性质——5 只股票
    # N=5 时每十分位桶 1 只，demean 恒 0 是已知固有属性（计划文档 Task 7 实现备注）。
    spec_path = tmp_path / "e2e_size.yaml"
    spec_path.write_text("""
name: e2e_size
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH", "000002.SZ", "600036.SH", "601318.SH"]
date:
  start: "2024-01-01"
  end: "2024-03-31"
process:
  - neutralize(by=size)
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=real_db_path, output_dir=tmp_path / "out_size"))
    assert "signal" in result.panel.columns
    assert result.panel.height > 0
