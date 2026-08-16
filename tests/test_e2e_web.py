"""M5 端到端集成：真实 results 目录的 Web 可视化冒烟。

真实 results 目录在 main 工作树（C:/Users/ThinkPad/quant-platform/results/，
含 m4b_smoke/acceptance/demo_vol_skew）——与 conftest REAL_DB 同模式：
绝对路径引用 + 缺失 skip（FACTORLAB_RESULTS_DIR 可覆盖）。
"""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from factorlab.web.app import create_app

REAL_RESULTS = Path(os.environ.get(
    "FACTORLAB_RESULTS_DIR", "C:/Users/ThinkPad/quant-platform/results"
))

pytestmark = pytest.mark.integration


@pytest.fixture
def real_results_dir():
    if not REAL_RESULTS.is_dir():
        pytest.skip(f"真实 results 目录不存在: {REAL_RESULTS}")
    return REAL_RESULTS


def test_web_index_lists_real_factors(real_results_dir):
    # 列表页：真实 3 个因子全部展示（含 IC 摘要列）
    resp = TestClient(create_app(real_results_dir)).get("/")
    assert resp.status_code == 200
    for name in ("m4b_smoke", "demo_vol_skew", "momentum_20d"):  # 目录名与 summary.name 一致的可稳定断言
        assert name in resp.text


def test_web_factor_detail_real_charts(real_results_dir):
    # 详情页：真实数据渲染图表（IC 曲线/十分位/分层净值）与指标
    resp = TestClient(create_app(real_results_dir)).get("/factor/m4b_smoke")
    assert resp.status_code == 200
    assert "m4b_smoke" in resp.text
    assert "0.0786" in resp.text  # 真实 IC mean 格式化 %.4f（0.07857 → 0.0786）
    assert "Plotly" in resp.text  # 图表脚本与 figure JSON 内嵌
    assert "long_short" in resp.text  # 分层回测净值序列数据


def test_web_factor_detail_degraded_real(real_results_dir):
    # 真实数据边界：无 evaluation 的旧因子详情降级展示（不崩溃）
    resp = TestClient(create_app(real_results_dir)).get("/factor/demo_vol_skew")
    assert resp.status_code == 200
    assert "demo_vol_skew" in resp.text


def test_web_factor_missing_real_404(real_results_dir):
    # 真实数据错误路径：不存在的因子 → 404
    resp = TestClient(create_app(real_results_dir)).get("/factor/ghost")
    assert resp.status_code == 404
