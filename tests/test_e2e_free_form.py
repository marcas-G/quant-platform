"""free-form 端到端：真实平台库 A 股日频版 RunLength 思路因子（def 内窗口算子 + params + run --set 变体）。"""
import json

import pytest
import yaml
from typer.testing import CliRunner

from factorlab.cli.main import app

pytestmark = pytest.mark.integration

runner = CliRunner()

# 量能游程 × 钟形调制（参考 RunLengthEnergyModulation.h）：
# - oi_energy：量能变化率的钟形调制（def 内窗口算子——内联展开保证分区安全）
# - run length：500 日量能连续放量游程的截面排名
# 日期 2022-01-01 起 4 年（≈967 交易日）：500 日游程窗口（min_samples=窗口长，
# 窗口 > 数据长度时全 null）需足够数据——2 年（≈483 交易日）不够（计划原 2024 起
# 会全 null，实现时修正并记录）。
_SPEC = """
name: vol_run_energy
category: custom
direction: -1
params: {win: 200, gain: 2.0}
universe:
  codes: ["000001.SZ", "600519.SH", "000002.SZ", "600036.SH", "601318.SH"]
date:
  start: "2022-01-01"
  end: "2025-12-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_rank, ts_delta, ts_count

  def oi_energy(x, n):
      _e = ts_rank(ts_delta(x, 1).abs(), n)
      return sqrt(_e * (1 - _e))

  _energy = oi_energy(volume, ${win})
  _rl = ts_count(sign(ts_delta(volume, 1)) == 1, 500)
  signal = -ts_rank(_rl, 500) * _energy * ${gain}
"""


def _write_spec(tmp_path):
    spec_path = tmp_path / "vol_run_energy.yaml"
    spec_path.write_text(_SPEC, encoding="utf-8")
    return spec_path


def test_e2e_free_form_run_length_factor(real_db_path, tmp_path, monkeypatch):
    # 真实平台库：vol_run_energy（量能游程 × 钟形调制）→ run 端到端（评估 + 分层回测）
    monkeypatch.setattr("factorlab.config.settings.platform_db", real_db_path)
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path / "results")
    result = runner.invoke(app, ["run", str(_write_spec(tmp_path))])
    assert result.exit_code == 0, result.output
    summary = json.loads((tmp_path / "results" / "vol_run_energy" / "summary.json").read_text(encoding="utf-8"))
    ev = summary["evaluation"]
    assert ev["n_weeks"] > 50  # 4 年 ≈ 207 周（500 日窗口暖机后仍有 ~180 周有效）
    assert ev["ic"]["mean"] == ev["ic"]["mean"]  # 非 nan（真实数据 IC 可计算）
    assert "layered_backtest" in ev
    assert ev["layered_backtest"]["periods"] == ev["n_weeks"]
    # 非退化：500 日全窗口语义下，暖机 + 停牌日中断窗口 → null ~0.72（实测）——上界 0.8
    assert summary["signal_null_ratio"] < 0.8
    # 参数替换生效：spec_yaml 保留 params 原文
    assert yaml.safe_load(summary["spec_yaml"])["params"] == {"win": 200, "gain": 2.0}


def test_e2e_free_form_set_variant(real_db_path, tmp_path, monkeypatch):
    # --set 变体：win/gain 覆盖 → vol_run_energy_win100_gain1.5 独立 results 目录，评估跑通
    monkeypatch.setattr("factorlab.config.settings.platform_db", real_db_path)
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path / "results")
    result = runner.invoke(app, [
        "run", str(_write_spec(tmp_path)), "--set", "win=100", "--set", "gain=1.5"])
    assert result.exit_code == 0, result.output
    variant_dir = tmp_path / "results" / "vol_run_energy_win100_gain1.5"
    assert (variant_dir / "summary.json").exists()
    assert (variant_dir / "panel.parquet").exists()
    summary = json.loads((variant_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["evaluation"]["n_weeks"] > 50
    assert yaml.safe_load(summary["spec_yaml"])["params"] == {"win": 100, "gain": 1.5}
    assert "vol_run_energy_win100_gain1.5" in result.stdout
