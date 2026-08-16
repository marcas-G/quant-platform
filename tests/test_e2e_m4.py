"""M4a 端到端：真实平台库 + quant_core 周频评估集成测试。"""
import json

import pytest

from factorlab.engine.compute import RunContext, run_factor
from factorlab.eval.rust_ic import evaluate_factor_weekly
from factorlab.spec import load_spec

pytestmark = pytest.mark.integration


def test_e2e_real_factor_run(real_db_path, tmp_path):
    # 真实平台库 5 只 × 2 年：vol_skew 因子 → run → 周频评估合理（IC 可计算、覆盖率达标）
    spec_path = tmp_path / "e2e_m4.yaml"
    spec_path.write_text("""
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
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=real_db_path, output_dir=tmp_path / "out"))
    evaluation = evaluate_factor_weekly(result.panel, "e2e_vol_skew_m4", 1)
    assert result.panel.height > 0
    assert evaluation["n_weeks"] > 50  # 2 年 ≈ 104 周
    assert evaluation["coverage"]["pct_valid"] > 0.5
    assert evaluation["ic"]["mean"] == evaluation["ic"]["mean"]  # 非 nan（真实数据 IC 可计算）
    # 数据层落盘（run_factor 行为）：summary 不含 evaluation（评估在 CLI 层追加）
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["universe_count"] == 5
    assert "evaluation" not in summary
