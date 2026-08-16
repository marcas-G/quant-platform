import datetime
import random

import polars as pl
import pytest

from factorlab.eval.rust_ic import evaluate_factor_weekly


def _panel(weeks=12, stocks=10, seed=7):
    rng = random.Random(seed)
    rows = []
    for w in range(weeks):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)  # 每周五
        for s in range(stocks):
            code = f"{s:06d}"
            base = s / stocks  # 股票固定效应
            signal = base + rng.uniform(-0.1, 0.1)
            fwd = signal * 0.1 + rng.uniform(-0.02, 0.02)  # 正相关
            rows.append({"date": d, "code": code, "signal": signal, "forward_return_5d": fwd})
    return pl.DataFrame(rows)


def test_evaluate_factor_weekly_full_structure():
    result = evaluate_factor_weekly(_panel(), "demo", direction=1)
    assert result["factor"] == "_factor"
    assert result["target"] == "forward_return_5d"
    assert result["n_weeks"] == 12
    assert set(result["ic"]) >= {"mean", "std", "t_stat", "ir"}
    assert result["ic"]["mean"] == result["ic"]["mean"]  # 非 nan
    assert "decile_returns" in result and "turnover" in result and "coverage" in result


def test_evaluate_factor_weekly_direction_flips_decile():
    up = evaluate_factor_weekly(_panel(), "demo", direction=1)
    down = evaluate_factor_weekly(_panel(), "demo", direction=-1)
    assert up["decile_returns"]["spread"]["ret"] == pytest.approx(-down["decile_returns"]["spread"]["ret"])


def test_evaluate_factor_weekly_aligns_weekly():
    # 日频输入（60 个隔日 ≈ 12 周）→ 桥接内部周频对齐，n_weeks 反映周数
    rows = []
    for i in range(60):
        d = datetime.date(2024, 1, 2) + datetime.timedelta(days=i * 2)  # 隔日（工作日近似）
        for s in range(10):
            rows.append({"date": d, "code": f"{s:06d}", "signal": float(s), "forward_return_5d": 0.01})
    result = evaluate_factor_weekly(pl.DataFrame(rows), "demo", 1)
    assert result["n_weeks"] >= 10  # 60 个隔日 ≈ 12 周（周末跳过）


def test_evaluate_factor_weekly_missing_columns():
    with pytest.raises(ValueError, match="缺少列"):
        evaluate_factor_weekly(pl.DataFrame({"date": [], "code": []}), "demo", 1)


def test_evaluate_factor_weekly_null_rows_filtered():
    # quant_core 拒绝 None（实测 TypeError）；桥接层须过滤 null 行。
    # 停牌补全（signal null）与尾部无未来数据（forward null）是真实管线常态。
    rows = _panel().to_dicts()
    rows[5]["signal"] = None                      # 周内一只停牌股
    rows[-1]["forward_return_5d"] = None          # 最后一周无未来收益
    result = evaluate_factor_weekly(pl.DataFrame(rows), "demo", 1)
    assert result["n_weeks"] == 12
    assert result["coverage"]["pct_valid"] == 1.0  # null 在桥接层过滤，quant_core 所见全有效
    assert result["ic"]["mean"] == result["ic"]["mean"]


def test_evaluate_factor_weekly_empty_panel():
    # 空面板（列齐全、类型正确）：不崩溃，quant_core 返回 nan 结构
    panel = pl.DataFrame(schema={
        "date": pl.Date, "code": pl.String, "signal": pl.Float64, "forward_return_5d": pl.Float64,
    })
    result = evaluate_factor_weekly(panel, "demo", 1)
    assert result["n_weeks"] == 0
    assert result["ic"]["mean"] != result["ic"]["mean"]  # nan
