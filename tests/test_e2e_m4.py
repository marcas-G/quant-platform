"""M4b 端到端：真实平台库 + quant_core 周频评估 + 分层回测集成测试。"""
import json

import pytest
from typer.testing import CliRunner

from factorlab.cli.main import app
from factorlab.engine.compute import RunContext, run_factor
from factorlab.eval.alignment import align_weekly
from factorlab.eval.layered import layered_backtest
from factorlab.eval.rust_ic import evaluate_factor_weekly
from factorlab.spec import load_spec

pytestmark = pytest.mark.integration

runner = CliRunner()

_SPEC = """
name: e2e_vol_skew_m4
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
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_std_dev, ts_delay
  _ret = ts_delay(close, 1)
  _vol = ts_std_dev(_ret, 20)
  signal = -_vol + ts_mean(close, 20)
"""


def _write_spec(tmp_path, name="e2e_m4.yaml"):
    spec_path = tmp_path / name
    spec_path.write_text(_SPEC, encoding="utf-8")
    return spec_path


def test_e2e_real_factor_run(real_db_path, tmp_path):
    # 真实平台库 5 只 × 2 年：vol_skew 因子 → run → 周频评估 + 分层回测合理
    # （回测期数 = 评估周数、long-short 摘要非 nan、净值序列逐期对齐）
    result = run_factor(load_spec(_write_spec(tmp_path)), RunContext(db_path=real_db_path, output_dir=tmp_path / "out"))
    evaluation = evaluate_factor_weekly(result.panel, "e2e_vol_skew_m4", 1)
    assert result.panel.height > 0
    assert evaluation["n_weeks"] > 50  # 2 年 ≈ 104 周（有效周 98：头部窗口未满 4 周 + 尾部 2 周不计）
    assert evaluation["coverage"]["pct_valid"] > 0.5
    assert evaluation["ic"]["mean"] == evaluation["ic"]["mean"]  # 非 nan（真实数据 IC 可计算）
    # 分层回测：同一周频对齐面板，回测期数 = 评估周数（无效周不计入，与 quant_core 口径一致）
    weekly = align_weekly(result.panel)
    bt = layered_backtest(weekly, 1)
    assert bt["periods"] == evaluation["n_weeks"]  # 回测期数 = 评估周数
    assert bt["summary"]["long_short"]["sharpe"] == bt["summary"]["long_short"]["sharpe"]  # 非 nan
    assert len(bt["net_values"]["D1"]) == bt["periods"]  # 净值序列逐期一点
    assert len(bt["dates"]) == bt["periods"]
    # 数据层落盘（run_factor 行为）：summary 不含 evaluation（评估在 CLI 层追加）
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["universe_count"] == 5
    assert "evaluation" not in summary


def test_e2e_cli_run_layered_backtest(real_db_path, tmp_path, monkeypatch):
    # CLI run 端到端冒烟（真实平台库）：summary.evaluation 含 layered_backtest，
    # 回测期数与评估周数一致（CLI 层装配）
    monkeypatch.setattr("factorlab.config.settings.platform_db", real_db_path)
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path / "results")
    result = runner.invoke(app, ["run", str(_write_spec(tmp_path, "e2e_cli.yaml"))])
    assert result.exit_code == 0, result.output
    summary = json.loads((tmp_path / "results" / "e2e_vol_skew_m4" / "summary.json").read_text(encoding="utf-8"))
    ev = summary["evaluation"]
    bt = ev["layered_backtest"]
    assert bt["periods"] == ev["n_weeks"]
    assert len(bt["net_values"]["D1"]) == bt["periods"]
    assert bt["summary"]["long_short"]["sharpe"] == bt["summary"]["long_short"]["sharpe"]
