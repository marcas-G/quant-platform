# 相关性指标 + 经典因子种子 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 平台内置因子相关性度量（CLI `factorlab corr` + Web 热力图），并加入 10 个经典因子作为挖因子新种子。

**Architecture:** 相关性计算独立模块 `src/factorlab/eval/correlation.py`（读 results panel 的 signal，周度横截面秩相关 + 全局 Pearson），CLI 与 Web 复用；数据层扩展 `_DAILY_BASIC_MAP` 使公式可引用 pe_ttm/pb/dv_ratio；10 个经典因子按 TDD 流程生成并入库（跑结果 + 档案，成为挖因子新种子池）。

**Tech Stack:** polars（join/rank/corr）、plotly heatmap、typer CLI、pytest。

**依据 spec：** `docs/superpowers/specs/2026-08-18-factorlab-correlation-and-classic-seeds-design.md`

---

### Task 1: 数据层扩展（_DAILY_BASIC_MAP）

**Files:**
- Modify: `src/factorlab/data/source.py`（_DAILY_BASIC_MAP）
- Test: `tests/test_source.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_source.py` 末尾追加：

```python
def test_daily_basic_extended_columns_loaded():
    """扩展字段（pe_ttm/pb/dv_ratio）经 daily_basic join 加载。"""
    from factorlab.data.source import load_daily, _DAILY_BASIC_MAP
    import duckdb, tempfile, pathlib
    # 构造临时库：daily 3 行 + adj_factor 3 行 + daily_basic 3 行（含扩展字段）
    with tempfile.TemporaryDirectory() as td:
        db = pathlib.Path(td) / "t.duckdb"
        con = duckdb.connect(str(db))
        con.execute("create table daily (trade_date varchar, ts_code varchar, open double, high double, low double, close double, vol double, amount double)")
        con.execute("create table adj_factor (trade_date varchar, ts_code varchar, adj_factor double)")
        con.execute("create table daily_basic (trade_date varchar, ts_code varchar, turnover_rate double, total_mv double, circ_mv double, pe_ttm double, pb double, dv_ratio double)")
        for i, d in enumerate(["20240102", "20240103", "20240104"]):
            con.execute("insert into daily values (?, ?, 10, 11, 9, 10.5, 1000, 100000)", [d, "000001.SZ"])
            con.execute("insert into adj_factor values (?, ?, 1.0)", [d, "000001.SZ"])
            con.execute("insert into daily_basic values (?, ?, 1.0, 1e10, 5e9, 12.0, 1.5, 0.02)", [d, "000001.SZ"])
        con.close()
        df = load_daily(str(db), "000001", cols=["close", "pe_ttm", "pb", "dv_ratio"])
        assert df["pe_ttm"].to_list() == [12.0] * 3
        assert df["pb"].to_list() == [1.5] * 3
        assert df["dv_ratio"].to_list() == [0.02] * 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_source.py::test_daily_basic_extended_columns_loaded -v`
Expected: FAIL（pe_ttm 不在 _DAILY_BASIC_MAP，join 不产生该列）

- [ ] **Step 3: 扩展映射**

`src/factorlab/data/source.py` 中：

```python
_DAILY_BASIC_MAP = {
    "turnover": "turnover_rate", "total_mv": "total_mv", "circ_mv": "circ_mv",
    "pe_ttm": "pe_ttm", "pb": "pb", "dv_ratio": "dv_ratio",
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_source.py -q`
Expected: 全通过（含既有测试）

- [ ] **Step 5: 提交**

```bash
git add src/factorlab/data/source.py tests/test_source.py
git commit -m "feat(data): _DAILY_BASIC_MAP 扩展 pe_ttm/pb/dv_ratio"
```

### Task 2: 相关性计算模块

**Files:**
- Create: `src/factorlab/eval/correlation.py`
- Test: `tests/test_correlation.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_correlation.py`：

```python
import polars as pl
import pytest
from factorlab.eval.correlation import factor_correlation


def _write_panel(tmp_path, name, signals):
    """构造 panel.parquet：date/code/signal 三列。"""
    df = pl.DataFrame({"date": d, "code": c, "signal": s}
                      for d, c, s in signals)
    d = tmp_path / name
    d.mkdir()
    df.write_parquet(d / "panel.parquet")


def test_rank_correlation_positive():
    """完全正相关的两信号 → 周度秩相关 ≈ 1。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        signals = [(f"2024-01-0{i}", f"{j:06d}", float(i * 100 + j))
                   for i in range(1, 4) for j in range(1, 51)]
        _write_panel(td, "a", signals)
        _write_panel(td, "b", [(d, c, 2 * s + 1) for d, c, s in signals])
        m = factor_correlation(["a", "b"], td)
        assert abs(m["rank_corr"][0] - 1.0) < 1e-6


def test_rank_correlation_negative():
    """完全负相关 → 周度秩相关 ≈ -1。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        signals = [(f"2024-01-0{i}", f"{j:06d}", float(j)) for i in range(1, 4) for j in range(1, 51)]
        _write_panel(td, "a", signals)
        _write_panel(td, "b", [(d, c, -s) for d, c, s in signals])
        m = factor_correlation(["a", "b"], td)
        assert abs(m["rank_corr"][0] + 1.0) < 1e-6


def test_missing_factor_raises():
    """缺失 results → 报错。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(FileNotFoundError):
            factor_correlation(["a", "b"], td)


def test_single_factor_raises():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ValueError):
            factor_correlation(["a"], td)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_correlation.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现模块**

创建 `src/factorlab/eval/correlation.py`：

```python
from __future__ import annotations

import pathlib

import numpy as np
import polars as pl

MAX_JOINED_ROWS = 20_000_000  # 内存护栏：超过则每周降采样
WEEKLY_SAMPLE_STOCKS = 5000


def _load_signal(results_dir: pathlib.Path, name: str) -> pl.DataFrame:
    """读因子 panel 的 date/code/signal。"""
    p = pathlib.Path(results_dir) / name / "panel.parquet"
    if not p.exists():
        raise FileNotFoundError(f"因子 {name} 无结果（results/{name}/panel.parquet）")
    return pl.read_parquet(p).select(["date", "code", "signal"]).rename({"signal": name})


def _join_panels(names: list[str], results_dir: pathlib.Path) -> pl.DataFrame:
    joined = _load_signal(results_dir, names[0])
    for name in names[1:]:
        joined = joined.join(_load_signal(results_dir, name), on=["date", "code"], how="inner")
    if joined.height > MAX_JOINED_ROWS:
        # 每周最多 WEEKLY_SAMPLE_STOCKS 只（均匀抽样）——护栏
        joined = (joined
                  .with_columns(pl.int_range(0, pl.len()).over("date").alias("_r"))
                  .filter(pl.col("_r") < WEEKLY_SAMPLE_STOCKS)
                  .drop("_r"))
    return joined


def factor_correlation(names: list[str], results_dir: str | pathlib.Path,
                       ) -> pl.DataFrame:
    """两两相关矩阵：周度横截面秩相关均值 + 全局 Pearson。

    返回列：factor_a/factor_b/rank_corr/pearson。
    """
    if len(names) < 2:
        raise ValueError("至少需要 2 个因子")
    joined = _join_panels(names, pathlib.Path(results_dir))
    n = len(names)
    rank_sum = np.zeros((n, n))
    pearson = np.zeros((n, n))
    weeks = 0
    for d in joined["date"].unique().to_list():
        sub = joined.filter(pl.col("date") == d)
        if sub.height < 30:
            continue
        mat = sub.select(names).to_numpy()
        for i in range(n):
            for j in range(i + 1, n):
                xi, xj = mat[:, i], mat[:, j]
                pr = np.corrcoef(xi, xj)[0, 1]
                if not np.isnan(pr):
                    pearson[i, j] += pr
                    pearson[j, i] += pr
                # 秩相关：rank 后 Pearson 等价 Spearman
                ri = np.argsort(np.argsort(xi)).astype(float)
                rj = np.argsort(np.argsort(xj)).astype(float)
                rr = np.corrcoef(ri, rj)[0, 1]
                if not np.isnan(rr):
                    rank_sum[i, j] += rr
                    rank_sum[j, i] += rr
        weeks += 1
    denom = max(weeks, 1)
    rows = []
    for i in range(n):
        for j in range(i + 1, n):
            rows.append({
                "factor_a": names[i], "factor_b": names[j],
                "rank_corr": rank_sum[i, j] / denom,
                "pearson": pearson[i, j] / denom,
            })
    return pl.DataFrame(rows)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_correlation.py -q`
Expected: 全通过

- [ ] **Step 5: 提交**

```bash
git add src/factorlab/eval/correlation.py tests/test_correlation.py
git commit -m "feat(eval): 因子相关性计算模块（周度秩相关 + Pearson）"
```

### Task 3: CLI corr 命令

**Files:**
- Modify: `src/factorlab/cli/main.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_cli.py` 末尾追加（monkeypatch results 目录到临时合成面板）：

```python
def test_corr_command_outputs_matrix(tmp_path, monkeypatch):
    """factorlab corr 输出两两相关矩阵。"""
    import types
    from typer.testing import CliRunner
    import polars as pl
    from factorlab.cli.main import app
    runner = CliRunner()
    # 构造两个因子 panel
    for name, mult in [("a", 1.0), ("b", 2.0)]:
        d = tmp_path / name
        d.mkdir()
        df = pl.DataFrame({
            "date": [f"2024-01-0{i}" for i in range(1, 4) for _ in range(50)],
            "code": [f"{j:06d}" for _ in range(3) for j in range(50)],
            "signal": [float(mult * (i * 100 + j)) for i in range(1, 4) for j in range(50)],
        })
        df.write_parquet(d / "panel.parquet")
    monkeypatch.setattr("factorlab.cli.main.settings",
                        types.SimpleNamespace(results_dir=tmp_path))
    result = runner.invoke(app, ["corr", "a", "b"])
    assert result.exit_code == 0
    assert "rank_corr" in result.stdout
    assert "a" in result.stdout and "b" in result.stdout


def test_corr_missing_factor(tmp_path, monkeypatch):
    import types
    from typer.testing import CliRunner
    from factorlab.cli.main import app
    runner = CliRunner()
    monkeypatch.setattr("factorlab.cli.main.settings",
                        types.SimpleNamespace(results_dir=tmp_path))
    result = runner.invoke(app, ["corr", "a", "b"])
    assert result.exit_code != 0
    assert "无结果" in result.stdout
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cli.py -q`
Expected: FAIL（corr 命令不存在）

- [ ] **Step 3: 实现命令**

在 `src/factorlab/cli/main.py` 中 `show_factor` 之后添加：

```python
@app.command("corr")
def corr_factors(names: list[str] = typer.Argument(..., min_length=2)) -> None:
    """因子两两相关性：周度横截面秩相关均值 + 全局 Pearson。

    用法: factorlab corr <name1> <name2> [<name3>...]
    """
    from factorlab.eval.correlation import factor_correlation
    m = factor_correlation(names, settings.results_dir)
    console.print(m.to_pandas().to_string(index=False))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_cli.py -q`
Expected: 全通过

- [ ] **Step 5: 提交**

```bash
git add src/factorlab/cli/main.py tests/test_cli.py
git commit -m "feat(cli): factorlab corr 因子相关性命令"
```

### Task 4: Web 相关热力图

**Files:**
- Modify: `src/factorlab/web/charts.py`
- Modify: `src/factorlab/web/app.py`
- Modify: `src/factorlab/web/templates/factor.html`
- Test: `tests/test_web.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_web.py` 末尾追加：

```python
def test_factor_detail_has_correlation_block(tmp_path):
    """详情页含相关热力图区块（有结果的因子）。"""
    from factorlab.web.app import create_app
    from fastapi.testclient import TestClient
    import polars as pl
    # 两个因子：a 有结果，b 有结果（与 a 相关）
    for name, mult in [("a", 1.0), ("b", 2.0)]:
        d = tmp_path / name
        d.mkdir()
        df = pl.DataFrame({
            "date": [f"2024-01-0{i}" for i in range(1, 4) for _ in range(50)],
            "code": [f"{j:06d}" for _ in range(3) for j in range(50)],
            "signal": [float(mult * (i * 100 + j)) for i in range(1, 4) for j in range(50)],
        })
        df.write_parquet(d / "panel.parquet")
    # a 的完整结果（含 summary.json 最小结构）
    import json
    (tmp_path / "a" / "summary.json").write_text(json.dumps({"name": "a"}), encoding="utf-8")
    client = TestClient(create_app(tmp_path))
    r = client.get("/factor/a")
    assert r.status_code == 200
    assert "correlation-chart" in r.text  # 热力图容器
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_web.py -q`
Expected: FAIL（correlation-chart 不存在）

- [ ] **Step 3: charts.py 加热力图函数**

在 `src/factorlab/web/charts.py` 末尾添加：

```python
def correlation_heatmap_figure(names: list[str], matrix: list[list[float]]) -> str:
    """因子相关热力图（diverging：正蓝负红，0 白）→ plotly figure JSON。"""
    fig = go.Figure(go.Heatmap(
        z=matrix, x=names, y=names,
        zmin=-1, zmax=1, colorscale=[
            [0.0, "#e34948"], [0.5, "#fcfcfb"], [1.0, "#2a78d6"]],
        colorbar=dict(title="corr", tickfont=dict(color=_SECONDARY_INK)),
        hovertemplate="%{x} × %{y}<br>corr=%{z:.3f}<extra></extra>"))
    fig.update_layout(**_base_layout("因子相关性", 340))
    return fig.to_json()
```

- [ ] **Step 4: app.py 计算相关性**

`factor_detail` 中 `layered` 区块之后、`return` 之前添加：

```python
        # 相关因子热力图：与库内其他有结果因子（复用 correlation 模块）
        try:
            from factorlab.eval.correlation import factor_correlation
            all_names = sorted(p.name for p in results_dir.glob("*/panel.parquet")
                               if p.parent.name != name)
            if all_names:
                cm = factor_correlation([name] + all_names, results_dir)
                pairs = [(r["factor_b"], r["rank_corr"]) for r in cm.to_dicts()
                         if r["factor_a"] == name]
                pairs.sort(key=lambda x: abs(x[1]), reverse=True)
                top = pairs[:10]
                if top:
                    others = [t[0] for t in top]
                    # 重算 top 子集矩阵
                    cm2 = factor_correlation([name] + others, results_dir)
                    names_l = [name] + others
                    matrix = [[0.0] * len(names_l) for _ in names_l]
                    for r in cm2.to_dicts():
                        i, j = names_l.index(r["factor_a"]), names_l.index(r["factor_b"])
                        matrix[i][j] = matrix[j][i] = r["rank_corr"]
                    for k in range(len(names_l)):
                        matrix[k][k] = 1.0
                    charts_data["correlation"] = charts.correlation_heatmap_figure(names_l, matrix)
        except (OSError, ValueError, pl.exceptions.PolarsError):
            pass  # 相关区块降级（无其他因子/面板异常）
```

- [ ] **Step 5: factor.html 加热力图区块**

在分层净值区块后添加：

```html
  {% if charts.correlation %}
  <div class="chart-card"><h2>相关因子</h2>
    <div id="correlation-chart"></div>
    <script>Plotly.newPlot("correlation-chart", {{ charts.correlation | safe }});</script>
  </div>
  {% endif %}
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_web.py -q`
Expected: 全通过

- [ ] **Step 7: 提交**

```bash
git add src/factorlab/web/charts.py src/factorlab/web/app.py src/factorlab/web/templates/factor.html tests/test_web.py
git commit -m "feat(web): 因子详情页相关热力图"
```

### Task 5: 经典因子——价值 3 个

**Files:**
- Create: `factor/value_ep.yaml`、`factor/value_bp.yaml`、`factor/dividend_yield.yaml`
- Create: `docs/factors/value_ep.md`、`docs/factors/value_bp.md`、`docs/factors/dividend_yield.md`

- [ ] **Step 1: 写 3 个因子 spec**

`factor/value_ep.yaml`：

```yaml
name: value_ep
category: custom
direction: 1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2023-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  signal = 1 / pe_ttm
```

`factor/value_bp.yaml`：同上但 `signal = 1 / pb`。
`factor/dividend_yield.yaml`：同上但 `signal = dv_ratio`。

- [ ] **Step 2: 逐个运行**

Run（每个）: `factorlab run factor/<name>.yaml`
Expected: 成功输出 n_weeks/ic_mean/spread；记录 summary 指标（缺失率可能高——daily_basic 早期覆盖）

- [ ] **Step 3: 建档案**

按 `docs/factors/_template.md` 为 3 个因子建档案（逻辑/验证快照/判定；
判定按实际：显著→候选，不显著→观察中/无效，表现差不影响入库——正交种子价值）。

- [ ] **Step 4: 提交**

```bash
git add factor/value_ep.yaml factor/value_bp.yaml factor/dividend_yield.yaml docs/factors/value_ep.md docs/factors/value_bp.md docs/factors/dividend_yield.md
git commit -m "feat(factor): 价值三因子种子（EP/BP/股息率）"
```

### Task 6: 经典因子——波动/彩票/流动性/规模 4 个

**Files:**
- Create: `factor/low_vol_20d.yaml`、`factor/max_effect_20d.yaml`、`factor/amihud_illiq_20d.yaml`、`factor/small_cap.yaml`
- Create: 对应 `docs/factors/*.md`

- [ ] **Step 1: 写 4 个因子 spec**

`factor/low_vol_20d.yaml`：

```yaml
name: low_vol_20d
category: custom
direction: 1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2023-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  signal = -ts_std_dev(returns(close), 20)
```

`factor/max_effect_20d.yaml`：`signal = ts_max(returns(close), 20)`，direction: -1。
`factor/amihud_illiq_20d.yaml`：`signal = ts_mean(abs(returns(close)) / amount, 20)`，direction: 1。
`factor/small_cap.yaml`：`signal = -log(circ_mv)`，direction: 1。

- [ ] **Step 2: 逐个运行 + 建档案**（同 Task 5 Step 2-3）
- [ ] **Step 3: 提交**

```bash
git add factor/low_vol_20d.yaml factor/max_effect_20d.yaml factor/amihud_illiq_20d.yaml factor/small_cap.yaml docs/factors/low_vol_20d.md docs/factors/max_effect_20d.md docs/factors/amihud_illiq_20d.md docs/factors/small_cap.md
git commit -m "feat(factor): 波动/彩票/流动性/规模因子种子"
```

### Task 7: 经典因子——技术 3 个

**Files:**
- Create: `factor/rsi_reversal_14.yaml`、`factor/volume_ratio.yaml`、`factor/turnover_level.yaml`
- Create: 对应 `docs/factors/*.md`

- [ ] **Step 1: 写 3 个因子 spec**

`factor/rsi_reversal_14.yaml`：

```yaml
name: rsi_reversal_14
category: custom
direction: -1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2023-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.tdx import ts_RSI
  signal = ts_RSI(close, 14)
```

`factor/volume_ratio.yaml`：`signal = volume_ratio`，direction: -1。
`factor/turnover_level.yaml`：`signal = turnover`，direction: -1。

- [ ] **Step 2: 逐个运行 + 建档案**（同 Task 5 Step 2-3）
- [ ] **Step 3: 提交**

```bash
git add factor/rsi_reversal_14.yaml factor/volume_ratio.yaml factor/turnover_level.yaml docs/factors/rsi_reversal_14.md docs/factors/volume_ratio.md docs/factors/turnover_level.md
git commit -m "feat(factor): 技术因子种子（RSI/量比/换手水平）"
```

### Task 8: 文档同步

**Files:**
- Modify: `docs/interface.md`

- [ ] **Step 1: interface.md 更新**

- §1 命令表：加 `factorlab corr <name1> <name2> ...`（两两相关：周度横截面秩相关均值 + 全局 Pearson；任一因子无 results 报错）
- §数据字段：daily_basic 映射新增 pe_ttm/pb/dv_ratio（引用自动加载；早期覆盖不足→缺失传播）
- 新因子清单：10 个经典因子一行列表（value_ep/value_bp/dividend_yield/low_vol_20d/max_effect_20d/amihud_illiq_20d/small_cap/rsi_reversal_14/volume_ratio/turnover_level）

- [ ] **Step 2: 提交**

```bash
git add docs/interface.md
git commit -m "docs: interface.md 更新（corr 命令/新字段/经典因子）"
```

### Task 9: 全量验证

- [ ] **Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: 全通过（439+ 既有 + 新增）

- [ ] **Step 2: 相关性抽查**

Run: `factorlab corr reversal_20d reversal_20d_cumret vol_run_energy_symrun`
Expected: 输出矩阵（reversal×cumret 高、reversal×symrun 低——与批次 3 分析一致）

- [ ] **Step 3: Web 抽查**

Run: `factorlab serve` 后访问 `http://127.0.0.1:8000/factor/reversal_20d`
Expected: 详情页含"相关因子"热力图区块

- [ ] **Step 4: 汇报**

汇总：10 个经典因子结果表（IC/t/判定）、corr 命令示例输出、Web 热力图。
