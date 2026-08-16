import json

import polars as pl
import pytest
from fastapi.testclient import TestClient

from factorlab.web.app import create_app


def _write_factor(results_dir, name, with_weekly=True, with_layered=True):
    out = results_dir / name
    out.mkdir(parents=True, exist_ok=True)
    ev = {
        "ic": {"mean": 0.05, "t_stat": 1.5},
        "decile_returns": {"spread": {"ret": 0.02}, "groups": [
            {"group": 1, "mean_ret": 0.03}, {"group": 2, "mean_ret": 0.01}]},
        "turnover": {"monthly": 0.1},
        "coverage": {"pct_valid": 0.9},
    }
    if with_layered:
        ev["layered_backtest"] = {"periods": 2, "net_values": {"D1": [1.0, 1.01], "D10": [1.0, 0.99],
                                                              "long_short": [0.0, 0.02]},
                                  "summary": {"D1": {"annual_return": 0.5}}}
    summary = {
        "name": name, "category": "custom", "direction": 1,
        "universe_count": 5, "date_start": "2024-01-01", "date_end": "2025-12-31",
        "panel_rows": 100, "signal_null_ratio": 0.04,
        "spec_yaml": "name: demo\nformula: signal = close",
        "evaluation": ev,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    if with_weekly:
        rows = []
        for w, d in enumerate(["2024-01-05", "2024-01-12"]):
            for s in range(10):
                rows.append({"date": d, "code": f"{s:06d}", "signal": float(s), "forward_return_5d": 0.01})
        pl.DataFrame(rows).write_parquet(out / "weekly.parquet")


def test_index_lists_factors(tmp_path):
    _write_factor(tmp_path, "alpha_1")
    _write_factor(tmp_path, "beta_2")
    client = TestClient(create_app(results_dir=tmp_path))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "alpha_1" in resp.text and "beta_2" in resp.text


def test_index_empty_results(tmp_path):
    client = TestClient(create_app(results_dir=tmp_path / "nope"))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "暂无" in resp.text


def test_factor_detail_contains_charts(tmp_path):
    _write_factor(tmp_path, "alpha_1")
    client = TestClient(create_app(results_dir=tmp_path))
    resp = client.get("/factor/alpha_1")
    assert resp.status_code == 200
    # 图表数据（ic 曲线/十分位/净值）内嵌
    assert "0.05" in resp.text  # ic mean
    assert "Plotly" in resp.text or "plotly" in resp.text
    assert "net_values" in resp.text or "long_short" in resp.text


def test_factor_missing_404(tmp_path):
    client = TestClient(create_app(results_dir=tmp_path))
    resp = client.get("/factor/ghost")
    assert resp.status_code == 404


def test_factor_detail_without_weekly(tmp_path):
    _write_factor(tmp_path, "no_weekly", with_weekly=False)
    client = TestClient(create_app(results_dir=tmp_path))
    resp = client.get("/factor/no_weekly")
    assert resp.status_code == 200  # IC 曲线区域降级，其余照常


def test_factor_corrupt_summary_404(tmp_path):
    out = tmp_path / "broken"
    out.mkdir(parents=True)
    (out / "summary.json").write_text("{not json", encoding="utf-8")
    client = TestClient(create_app(results_dir=tmp_path))
    resp = client.get("/factor/broken")
    assert resp.status_code == 404
    # 列表页跳过损坏 summary，不中断
    assert "broken" not in client.get("/").text


def test_factor_detail_missing_evaluation_fields(tmp_path):
    # summary 缺 evaluation.ic/layered_backtest 等字段 → 页面不崩溃、降级展示
    out = tmp_path / "sparse"
    out.mkdir(parents=True)
    (out / "summary.json").write_text(json.dumps({
        "name": "sparse", "category": "custom", "direction": 1,
        "universe_count": 5, "date_start": "2024-01-01", "date_end": "2025-12-31",
        "panel_rows": 100, "signal_null_ratio": 0.04,
        "spec_yaml": "name: sparse\nformula: signal = close",
        "evaluation": {"decile_returns": {"groups": [{"group": 1, "mean_ret": 0.03}]}},
    }, ensure_ascii=False), encoding="utf-8")
    rows = []
    for d in ["2024-01-05", "2024-01-12"]:
        for s in range(10):
            rows.append({"date": d, "code": f"{s:06d}", "signal": float(s), "forward_return_5d": 0.01})
    pl.DataFrame(rows).write_parquet(out / "weekly.parquet")
    client = TestClient(create_app(results_dir=tmp_path))
    resp = client.get("/factor/sparse")
    assert resp.status_code == 200
    assert "sparse" in resp.text
    assert "decile-chart" in resp.text  # 有数据的图表照常渲染
