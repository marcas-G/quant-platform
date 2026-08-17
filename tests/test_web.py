import asyncio
import json

import polars as pl
import pytest
from fastapi.testclient import TestClient

from factorlab.web.app import create_app


def _raw_get(app, path):
    """直连 ASGI scope 发起 GET——绕过 httpx 客户端路径规范化（等价真实服务器/curl 的原始路径）。"""
    scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": [], "client": ("127.0.0.1", 1),
             "server": ("test", 80), "scheme": "http", "root_path": "",
             "http_version": "1.1", "app": app}
    res = {"status": None, "body": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            res["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            res["body"] += msg["body"]

    asyncio.run(app(scope, receive, send))
    return res["status"], res["body"].decode("utf-8", errors="replace")


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


def test_factor_name_path_traversal_rejected(tmp_path):
    """CWE-22 回归：因子名含路径穿越片段/分隔符 → 一律 404，不泄露 results_dir 之外的文件。"""
    results_dir = tmp_path / "results"
    _write_factor(results_dir, "alpha_1")
    # results_dir 上一级放一个可读目标目录（模拟越权读取的 summary）
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "summary.json").write_text(json.dumps(
        {"name": "victim", "spec_yaml": "TOP-SECRET"}, ensure_ascii=False), encoding="utf-8")
    app = create_app(results_dir=results_dir)
    client = TestClient(app)
    # TestClient 会把 %5c/%2e 解码后交给处理器——这些变体必须被服务端拒绝
    # （".." 会被 httpx 客户端规范化为 "/" 重写为首页，故在下方 RAW scope 中覆盖）
    for bad in ("%2e%2e", "..%5cvictim", "..%5c..%5c", "..%5cvictim%5csummary.json",
                "../victim", "..%2fvictim", "a/b", "a\\b", "a%5cb", "C%3asecret"):
        resp = client.get(f"/factor/{bad}")
        assert resp.status_code == 404, f"/factor/{bad} 应 404（实际 {resp.status_code}）"
        assert "TOP-SECRET" not in resp.text
    # 直连 ASGI scope：真实服务器会收到原始路径（curl 的原始反斜杠、裸 ".."）
    for path in ("/factor/..", "/factor/..\\victim", "/factor/a\\b"):
        status, body = _raw_get(app, path)
        assert status == 404, f"RAW {path} 应 404（实际 {status}）"
        assert "TOP-SECRET" not in body
    # 正常因子不受影响
    assert client.get("/factor/alpha_1").status_code == 200


def test_factor_detail_corrupt_weekly_degrade(tmp_path):
    # 损坏的 weekly.parquet → IC 曲线区域降级为"无周频数据"（不 500，其余图表照常）
    _write_factor(tmp_path, "broken", with_weekly=True)
    (tmp_path / "broken" / "weekly.parquet").write_bytes(b"not a parquet file")
    client = TestClient(create_app(results_dir=tmp_path))
    resp = client.get("/factor/broken")
    assert resp.status_code == 200
    assert "无周频数据" in resp.text
    assert "decile-chart" in resp.text


def test_factor_detail_has_correlation_block(tmp_path):
    """详情页含相关热力图区块（库内有多因子时）。"""
    import polars as pl
    _write_factor(tmp_path, "alpha_1")
    # 第二个因子：只有 panel（无 summary 也应被 corr 逻辑处理）
    out2 = tmp_path / "beta_2"
    out2.mkdir()
    rows = []
    for w, d in enumerate(["2024-01-05", "2024-01-12"]):
        for s in range(10):
            rows.append({"date": d, "code": f"{s:06d}", "signal": float(s * 2)})
    pl.DataFrame(rows).write_parquet(out2 / "panel.parquet")
    client = TestClient(create_app(results_dir=tmp_path))
    r = client.get("/factor/alpha_1")
    assert r.status_code == 200
    assert "correlation-chart" in r.text


def test_factor_detail_correlation_single_factor(tmp_path):
    """库内只有当前因子 → 相关区块降级不崩溃。"""
    _write_factor(tmp_path, "alpha_1")
    client = TestClient(create_app(results_dir=tmp_path))
    r = client.get("/factor/alpha_1")
    assert r.status_code == 200
    assert "correlation-chart" not in r.text
