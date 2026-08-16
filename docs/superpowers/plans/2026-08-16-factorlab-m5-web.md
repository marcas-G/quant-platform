# FactorLab M5 Web 可视化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 results_dir 只读展示单因子评估结果：因子列表页 + 详情页（IC 曲线/十分位柱状图/分层回测净值曲线/spec 原文）。

**Architecture:** `eval/`（weekly_ic 新增）→ `web/`（FastAPI + charts + Jinja2 模板 + plotly.js 本地）→ CLI serve。

**Tech Stack:** Python 3.13、FastAPI、uvicorn、Jinja2、Plotly。

**Spec:** `docs/superpowers/specs/2026-08-16-factorlab-m5-web-design.md`

## Global Constraints

- Python 3.13；包结构 `src/factorlab`；测试 `pythonpath = ["src"]`。
- Web 只读 `results_dir`；不碰平台库。
- 单因子定位（无 /compare 页面）。
- TDD（正常/边界/错误），全量通过后提交（CLAUDE.md 硬性要求）。
- 新代码同步更新 `docs/interface.md`（Task 4）。

## File Structure

- `src/factorlab/eval/ic_series.py`（Create）：weekly_ic。
- `src/factorlab/web/__init__.py`、`app.py`、`charts.py`（Create）。
- `src/factorlab/web/templates/index.html`、`factor.html`（Create）。
- `src/factorlab/web/static/plotly.min.js`（vendored，下载一次）。
- `src/factorlab/cli/main.py`（Modify）：serve 命令。
- 测试：`tests/test_ic_series.py`、`tests/test_web.py`（Create）。

---

### Task 1: eval 层 weekly_ic

**Files:**
- Create: `src/factorlab/eval/ic_series.py`
- Test: `tests/test_ic_series.py`

**Interfaces:** `weekly_ic(panel, target="forward_return_5d") -> pl.DataFrame`（(date, ic) 序列）。

- [ ] **Step 1: Write the failing test**

Create `tests/test_ic_series.py`：

```python
import datetime

import polars as pl
import pytest

from factorlab.eval.ic_series import weekly_ic


def _panel(weeks=4, stocks=10, seed=1):
    import random
    rng = random.Random(seed)
    rows = []
    for w in range(weeks):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for s in range(stocks):
            signal = s / stocks + rng.uniform(-0.05, 0.05)
            rows.append({"date": d, "code": f"{s:06d}",
                         "signal": signal, "forward_return_5d": signal * 0.1 + rng.uniform(-0.01, 0.01)})
    return pl.DataFrame(rows)


def test_weekly_ic_structure():
    result = weekly_ic(_panel())
    assert result.columns == ["date", "ic"]
    assert result.height == 4  # 每周一点
    assert result["ic"].null_count() == 0


def test_weekly_ic_positive_correlation():
    # signal 与 forward 正相关构造 → ic 应为正
    result = weekly_ic(_panel())
    assert result["ic"].mean() > 0


def test_weekly_ic_exact_rank_correlation():
    # 手工推演：signal = [1,2,3,4], forward = [0.1,0.2,0.3,0.4]（完全单调）→ ic = 1.0
    panel = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5)] * 4,
        "code": ["a", "b", "c", "d"],
        "signal": [1.0, 2.0, 3.0, 4.0],
        "forward_return_5d": [0.1, 0.2, 0.3, 0.4],
    })
    result = weekly_ic(panel)
    assert result["ic"][0] == pytest.approx(1.0)


def test_weekly_ic_insufficient_stocks_null():
    # 单期只有 2 只 → 秩相关不稳健 → null
    panel = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5)] * 2,
        "code": ["a", "b"],
        "signal": [1.0, 2.0],
        "forward_return_5d": [0.1, 0.2],
    })
    result = weekly_ic(panel)
    assert result["ic"][0] is None


def test_weekly_ic_excludes_null_rows():
    # 某行 signal null → 排除（不影响其余）
    panel = _panel(weeks=1, stocks=10)
    panel = panel.with_columns(pl.when(pl.col("code") == "000000").then(None).otherwise(pl.col("signal")).alias("signal"))
    result = weekly_ic(panel)
    assert result["ic"].null_count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ic_series.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/eval/ic_series.py`：

```python
from __future__ import annotations

import polars as pl

MIN_STOCKS = 3  # 秩相关稳健性的最小有效股票数


def weekly_ic(panel: pl.DataFrame, target: str = "forward_return_5d") -> pl.DataFrame:
    """周度 RankIC：每期（周）signal 与 target 的 Spearman 秩相关序列。

    - 与 quant_core 的 RankIC 同源定义（秩相关）；polars 1.38 的
      pl.corr(method="spearman") 直接支持，无需手工 rank（rank 后
      Pearson 与之一致——秩相关即秩的 Pearson）。
    - signal/target null 行排除（复用 rust_ic 的过滤语义）。
    - 面板中每个日期都保留一行：有效股票 < MIN_STOCKS 的周 ic = null
      （秩相关不稳健；含有效股票为 0 的周）。
    - 输出 (date, ic) 按日期排序。
    - 缺列（date/code/signal/target）抛 ValueError（不依赖 polars 内部异常）。
    """
    required = {"date", "code", "signal", target}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"评估面板缺少列: {sorted(missing)}")

    valid = panel.drop_nulls(["signal", target])
    stats = valid.group_by("date").agg(
        ic=pl.corr(pl.col("signal"), pl.col(target), method="spearman"),
        n_valid=pl.len(),
    )
    return (
        panel.select("date").unique()
        .join(stats, on="date", how="left")
        .with_columns(
            pl.when(pl.col("n_valid") < MIN_STOCKS).then(None).otherwise(pl.col("ic")).alias("ic")
        )
        .select(["date", "ic"])
        .sort("date")
    )
```

（polars 1.38 的 `pl.corr(..., method="spearman")` 在 group_by.agg 中直接支持，
用原始值即可（rank 输入多余），精确秩相关 = 1.0 与平局 average-rank 测试锁定。

实现与初稿的两处差异（记录自执行）：
1. 有效股票为 0 的周（某周 signal/target 全 null）**保留**在输出且 ic = null
   ——spec §4 "每期有效股票 < 3 → 该期 ic = null" 的字面语义；初稿 drop_nulls
   后 group_by 会丢失该周（与 1-2 只股票的周留 null 不一致）。测试
   test_weekly_ic_week_all_null 锁定。
2. 缺列抛 `ValueError`（初稿会让 polars 抛 ColumnNotFoundError）——复用
   rust_ic 的显式列检查语义。测试 test_weekly_ic_missing_target_column 锁定。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ic_series.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/eval/ic_series.py tests/test_ic_series.py
git commit -m "feat: add weekly rank-IC time series"
```

---

### Task 2: web 包（FastAPI + charts + 模板）

**Files:**
- Create: `src/factorlab/web/__init__.py`、`app.py`、`charts.py`
- Create: `src/factorlab/web/templates/index.html`、`factor.html`
- Create: `src/factorlab/web/static/plotly.min.js`（vendored）
- Test: `tests/test_web.py`

**Step 1: 测试**（fastapi TestClient）

Create `tests/test_web.py`：

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_web.py -v`
Expected: FAIL — web 包不存在。

**Step 3: Implement**

`src/factorlab/web/__init__.py`（空）。

`src/factorlab/web/charts.py`：

```python
from __future__ import annotations

import plotly.graph_objects as go
import polars as pl


def ic_curve_figure(ic_series: pl.DataFrame) -> str:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ic_series["date"].to_list(), y=ic_series["ic"].to_list(),
                             mode="lines", name="RankIC"))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(title="周度 RankIC", height=320, margin=dict(l=40, r=20, t=40, b=30))
    return fig.to_json()


def decile_bar_figure(groups: list[dict]) -> str:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[g.get("group") for g in groups], y=[g.get("mean_ret") for g in groups],
        name="十分位平均收益"))
    fig.update_layout(title="十分位收益", height=320, margin=dict(l=40, r=20, t=40, b=30))
    return fig.to_json()


def layered_net_value_figure(net_values: dict[str, list[float]], dates: list[str]) -> str:
    fig = go.Figure()
    for label, values in net_values.items():
        fig.add_trace(go.Scatter(x=dates, y=values, mode="lines", name=label))
    fig.update_layout(title="分层回测净值", height=420, margin=dict(l=40, r=20, t=40, b=30))
    return fig.to_json()
```

（chart 函数返回 JSON 字符串，模板内嵌 `Plotly.newPlot`。以测试断言（图表数据出现）为准。）

`src/factorlab/web/app.py`：

```python
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from factorlab.eval.ic_series import weekly_ic
from factorlab.web import charts

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_summary(results_dir: Path, name: str) -> dict:
    path = results_dir / name / "summary.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"因子 {name} 不存在")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=404, detail=f"因子 {name} 的 summary 损坏") from exc


def create_app(results_dir: Path) -> FastAPI:
    app = FastAPI(title="FactorLab")
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_TEMPLATES_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        factors = []
        if results_dir.exists():
            for summary_path in sorted(results_dir.glob("*/summary.json")):
                try:
                    s = json.loads(summary_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                ev = s.get("evaluation", {})
                factors.append({
                    "name": s.get("name", summary_path.parent.name),
                    "category": s.get("category", ""),
                    "direction": s.get("direction", ""),
                    "ic_mean": ev.get("ic", {}).get("mean"),
                    "spread": ev.get("decile_returns", {}).get("spread", {}).get("ret"),
                    "run_at": summary_path.stat().st_mtime,
                })
        return templates.TemplateResponse("index.html", {"request": request, "factors": factors})

    @app.get("/factor/{name}", response_class=HTMLResponse)
    def factor_detail(request: Request, name: str):
        summary = _load_summary(results_dir, name)
        ev = summary.get("evaluation", {})
        charts_data = {}
        weekly_path = results_dir / name / "weekly.parquet"
        if weekly_path.exists():
            panel = pl.read_parquet(weekly_path)
            ic_series = weekly_ic(panel)
            charts_data["ic"] = charts.ic_curve_figure(ic_series)
        if ev.get("decile_returns", {}).get("groups"):
            charts_data["decile"] = charts.decile_bar_figure(ev["decile_returns"]["groups"])
        layered = ev.get("layered_backtest", {})
        if layered.get("net_values"):
            charts_data["layered"] = charts.layered_net_value_figure(
                layered["net_values"], layered.get("dates", []))
        return templates.TemplateResponse("factor.html", {
            "request": request, "name": name, "summary": summary, "charts": charts_data,
            "has_weekly": weekly_path.exists(),
        })

    return app
```

`src/factorlab/web/templates/index.html`：

```html
<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>FactorLab</title></head>
<body>
<h1>FactorLab 因子库</h1>
{% if factors %}
<table border="1" cellpadding="6">
<tr><th>名称</th><th>类别</th><th>方向</th><th>IC mean</th><th>十分位 spread</th><th>最近运行</th></tr>
{% for f in factors %}
<tr><td><a href="/factor/{{ f.name }}">{{ f.name }}</a></td>
<td>{{ f.category }}</td><td>{{ f.direction }}</td>
<td>{{ f.ic_mean }}</td><td>{{ f.spread }}</td>
<td>{{ f.run_at }}</td></tr>
{% endfor %}
</table>
{% else %}<p>暂无因子结果（先运行 factorlab run）</p>{% endif %}
</body></html>
```

`src/factorlab/web/templates/factor.html`：

```html
<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>{{ name }} - FactorLab</title>
<script src="/static/plotly.min.js"></script></head>
<body>
<h1>{{ name }}</h1>
<p>universe={{ summary.universe_count }} | {{ summary.date_start }} ~ {{ summary.date_end }}
| rows={{ summary.panel_rows }} | null={{ summary.signal_null_ratio }}</p>
{% if charts.ic %}
<div id="ic-chart"></div>
<script>Plotly.newPlot("ic-chart", {{ charts.ic | safe }});</script>
{% elif not has_weekly %}<p>无周频数据（IC 曲线不可用）</p>{% endif %}
{% if charts.decile %}
<div id="decile-chart"></div>
<script>Plotly.newPlot("decile-chart", {{ charts.decile | safe }});</script>
{% endif %}
{% if charts.layered %}
<div id="layered-chart"></div>
<script>Plotly.newPlot("layered-chart", {{ charts.layered | safe }});</script>
{% endif %}
<pre>{{ summary.spec_yaml }}</pre>
</body></html>
```

**plotly.min.js vendored**：下载一次（`pip show plotly` 的 package_data 里有
`plotly.min.js`——从安装包复制，或 CDN 下载）——实现时选择（优先本地包内文件）。

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_web.py -v`
Expected: PASS。

**Step 5: Commit**

```bash
git add src/factorlab/web tests/test_web.py
git commit -m "feat: add web visualization app with factor list and detail"
```

---

### Task 3: CLI serve 命令

**Files:**
- Modify: `src/factorlab/cli/main.py`
- Test: `tests/test_cli_web.py`

**Step 1: 测试**

```python
def test_serve_help():
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.stdout
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_web.py -v`
Expected: FAIL — serve 命令不存在。

**Step 3: Implement**

```python
@app.command("serve")
def serve(port: int = 8000, host: str = "127.0.0.1") -> None:
    """启动 Web 可视化（只读 results_dir）。"""
    import uvicorn

    from factorlab.web.app import create_app
    uvicorn.run(create_app(settings.results_dir), host=host, port=port)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_web.py -v`
Expected: PASS。

**Step 5: Commit**

```bash
git add src/factorlab/cli/main.py tests/test_cli_web.py
git commit -m "feat: add factorlab serve command"
```

---

### Task 4: 集成冒烟与文档

**Files:**
- Modify: `docs/interface.md`、`docs/data-ops-playbook.md`
- Test: `tests/test_e2e_web.py`（集成）

**Step 1: 集成测试**

`tests/test_e2e_web.py`（真实 results 目录——3 个因子）：

```python
import pytest
from fastapi.testclient import TestClient

from factorlab.web.app import create_app


@pytest.mark.integration
def test_web_real_results():
    from factorlab.config import settings
    client = TestClient(create_app(settings.results_dir))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "m4b_smoke" in resp.text or "acceptance" in resp.text
    detail = client.get("/factor/m4b_smoke")
    assert detail.status_code == 200
```

（依赖 main 工作树的 results 目录——conftest 类似 REAL_DB 的处理：results 路径可配置，
集成测试用真实 results_dir。）

**Step 2: 文档更新**

- `docs/interface.md`：web 包（create_app/路由）、weekly_ic、serve 命令。
- `docs/data-ops-playbook.md`：§6 运维闭环加 serve（run → list/show → serve 可视化）。

**Step 3: 全量验证**

Run: `python -m pytest -q`
Expected: 全部 PASS。

**Step 4: Commit**

```bash
git add tests/test_e2e_web.py docs/interface.md docs/data-ops-playbook.md
git commit -m "docs: document M5 web visualization"
```

---

## Self-Review

**1. Spec coverage（对照 M5 spec）：**
- §2 架构（app/charts/templates/static）→ Task 2 ✓
- §3 页面（列表/详情/缺失兼容）→ Task 2 ✓
- §4 weekly_ic → Task 1 ✓
- §5 CLI serve → Task 3 ✓
- §6 测试策略 → 各任务 + Task 4 集成 ✓
- §7 不做（/compare 等）→ 计划不含 ✓

**2. Placeholder scan：** 无 TBD/TODO；plotly.min.js 的 vendored 来源给了两个选项（包内/下载）。

**3. Type consistency：** `weekly_ic(panel, target)`、`create_app(results_dir)`、chart 函数
（入 DataFrame/dict → JSON str）、serve 参数——任务间一致 ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-16-factorlab-m5-web.md`. Two execution options:

1. Subagent-Driven (recommended)
2. Inline Execution

Which approach?
