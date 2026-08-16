# FactorLab M4b 单因子评估深化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 单因子评估深化：分层回测（十分位净值 + long-short + 摘要）、run 参数扩展（--backtest/--groups）、CLI list/show、M4a 遗留接线（pit_qfq/weekly 落盘/results_dir 锚定）。

**Architecture:** `eval/layered.py`（分层回测，纯 polars 吃周频面板）→ `cli/main.py`（run 扩展 + list/show）→ `engine/compute.py`（pit_qfq asof 传递）→ `config.py`（results_dir）。

**Tech Stack:** Python 3.13、Polars、DuckDB、quant_core。

**Spec:** `docs/superpowers/specs/2026-08-16-factorlab-m4b-single-factor-eval-design.md`

## Global Constraints

- Python 3.13；包结构 `src/factorlab`；测试 `pythonpath = ["src"]`。
- 平台库 `data/factorlab.duckdb` 是唯一数据源。
- TDD（正常/边界/错误），全量通过后提交（CLAUDE.md 硬性要求）。
- 集成测试 `@pytest.mark.integration`（真实平台库）。
- 多因子（compare/composite/factors-combine）**不做**（用户决策后置）。
- 新代码同步更新 `docs/interface.md`（Task 4 汇总）。

## File Structure

- `src/factorlab/eval/layered.py`（Create）：分层回测。
- `src/factorlab/config.py`（Modify）：`results_dir`。
- `src/factorlab/engine/compute.py`（Modify）：pit_qfq asof 传递。
- `src/factorlab/cli/main.py`（Modify）：run 扩展 + list/show 命令。
- 测试：`tests/test_layered.py`、`tests/test_cli_list_show.py`（Create）；`tests/test_cli_run.py`、`tests/test_run_factor.py`、`tests/test_e2e_m4.py`（Modify）。

---

### Task 1: eval/layered.py 分层回测

**Files:**
- Create: `src/factorlab/eval/layered.py`
- Test: `tests/test_layered.py`

**Interfaces:** `layered_backtest(panel, direction, n_groups=10, cost=0.0) -> dict`
（输入周频面板：date/code/signal/forward_return_5d）。

- [ ] **Step 1: Write the failing test**

Create `tests/test_layered.py`：

```python
import datetime

import polars as pl
import pytest

from factorlab.eval.layered import layered_backtest


def _weekly_panel(weeks=4, stocks=10):
    """构造周频面板：每周 10 只，signal 单调（0.1-1.0），forward 与 signal 正相关。"""
    rows = []
    for w in range(weeks):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for s in range(stocks):
            signal = (s + 1) / stocks
            rows.append({"date": d, "code": f"{s:06d}",
                         "signal": signal, "forward_return_5d": signal * 0.1})
    return pl.DataFrame(rows)


def test_layered_backtest_structure():
    result = layered_backtest(_weekly_panel(), direction=1)
    assert result["n_groups"] == 10
    assert result["periods"] == 4
    assert set(result["net_values"]) >= {f"D{i}" for i in range(1, 11)} | {"long_short"}
    assert len(result["net_values"]["D1"]) == 4  # 每期一点
    assert len(result["dates"]) == 4
    assert "D1" in result["summary"] and "long_short" in result["summary"]


def test_layered_backtest_direction_flips_groups():
    up = layered_backtest(_weekly_panel(), direction=1)
    down = layered_backtest(_weekly_panel(), direction=-1)
    # direction=-1 时原 D1（最高 signal）成为最差档——净值应互换
    assert up["net_values"]["D1"][-1] == down["net_values"]["D10"][-1]
    assert up["net_values"]["D10"][-1] == down["net_values"]["D1"][-1]


def test_layered_backtest_net_value_math():
    # 单期单档：D1（最高 signal）档的 forward 等权平均 → 净值
    panel = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5), datetime.date(2024, 1, 5)],
        "code": ["000001", "000002"],
        "signal": [1.0, 0.9],  # 2 只，n_groups=2 → 各 1 只
        "forward_return_5d": [0.02, 0.01],
    })
    result = layered_backtest(panel, direction=1, n_groups=2)
    assert result["net_values"]["D1"][-1] == 1.02  # 最高档 = signal 1.0 → ret 0.02
    assert result["net_values"]["D2"][-1] == 1.01


def test_layered_backtest_long_short():
    panel = _weekly_panel(weeks=2)
    result = layered_backtest(panel, direction=1)
    # long-short 净值 = D1 - D10（首期都为 1.0）
    assert result["net_values"]["long_short"][0] == 0.0
    assert result["net_values"]["long_short"][-1] == pytest.approx(
        result["net_values"]["D1"][-1] - result["net_values"]["D10"][-1])


def test_layered_backtest_summary_metrics():
    result = layered_backtest(_weekly_panel(weeks=52), direction=1)
    s = result["summary"]["D1"]
    assert set(s) >= {"annual_return", "annual_vol", "sharpe", "max_drawdown", "win_rate"}
    assert s["annual_return"] > 0  # D1 正收益（forward 正相关）
    assert s["sharpe"] == pytest.approx(s["annual_return"] / s["annual_vol"])


def test_layered_backtest_empty_panel():
    result = layered_backtest(pl.DataFrame({"date": [], "code": [], "signal": [], "forward_return_5d": []}), 1)
    assert result["periods"] == 0
    assert result["net_values"] == {}
    assert result["summary"] == {}


def test_layered_backtest_single_week():
    result = layered_backtest(_weekly_panel(weeks=1), direction=1)
    assert result["periods"] == 1
    assert all(len(v) == 1 for v in result["net_values"].values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_layered.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/eval/layered.py`：

```python
from __future__ import annotations

import polars as pl

WEEKS_PER_YEAR = 52


def _group_assign(panel: pl.DataFrame, n_groups: int, direction: int) -> pl.DataFrame:
    """每期按 signal 分档：direction=1 时 D1=signal 最高档；direction=-1 时反转。"""
    # 降序 rank：signal 最高 → rank 1（方向感知的"最佳"排序）
    df = panel.with_columns(
        pl.col("signal").rank("ordinal", descending=direction == 1).over("date").alias("_rank"),
        pl.col("signal").count().over("date").alias("_n"),
    )
    # 档号：rank 1..n 分 n_groups 档 → (rank-1) * n_groups // n
    return df.with_columns(
        ((pl.col("_rank") - 1) * n_groups // pl.col("_n")).alias("_group")
    )


def _summary_metrics(net_values: pl.Series, returns: pl.Series) -> dict:
    """净值序列摘要：年化收益/波动/夏普/最大回撤/胜率。"""
    if len(returns) == 0:
        return {}
    annual_return = float(returns.mean() * WEEKS_PER_YEAR)
    annual_vol = float(returns.std() * (WEEKS_PER_YEAR ** 0.5))
    sharpe = annual_return / annual_vol if annual_vol and annual_vol > 0 else 0.0
    peak = net_values.cum_max()
    drawdown = (net_values - peak) / peak
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    win_rate = float((returns > 0).mean()) if len(returns) else 0.0
    return {
        "annual_return": round(annual_return, 6),
        "annual_vol": round(annual_vol, 6),
        "sharpe": round(sharpe, 6),
        "max_drawdown": round(max_drawdown, 6),
        "win_rate": round(win_rate, 6),
    }


def layered_backtest(
    panel: pl.DataFrame,
    direction: int,
    n_groups: int = 10,
    cost: float = 0.0,
) -> dict:
    """分层回测：每期按 signal 分档，各档 forward 等权平均累积净值；long-short = D1 - D10。

    输入周频面板（date/code/signal/forward_return_5d）。cost 参数预留（当前不建模调仓成本）。
    """
    if panel.height == 0:
        return {"n_groups": n_groups, "periods": 0, "net_values": {}, "summary": {}, "dates": []}

    df = _group_assign(panel, n_groups, direction)
    # 每期每档收益（forward 等权平均，忽略 null）
    group_ret = df.group_by(["date", "_group"]).agg(
        pl.col("forward_return_5d").mean().alias("_ret")
    ).sort(["date", "_group"])

    dates = sorted(panel["date"].unique().to_list())
    net_values: dict[str, list[float]] = {}
    returns_by_group: dict[str, list[float]] = {}
    for g in range(n_groups):
        gdf = group_ret.filter(pl.col("_group") == g)
        rets = gdf.join(pl.DataFrame({"date": dates}), on="date", how="right")["_ret"]
        rets = rets.fill_null(0.0)  # 档空期视为 0 收益（净值保持）
        nv = (1.0 + rets).cum_prod().to_list()
        label = f"D{g + 1}"
        net_values[label] = [round(v, 8) for v in nv]
        returns_by_group[label] = [float(r) for r in rets.to_list()]

    # long-short：D1 - D10 净值差
    d1, d10 = net_values["D1"], net_values[f"D{n_groups}"]
    net_values["long_short"] = [round(a - b, 8) for a, b in zip(d1, d10)]
    ls_returns = [round(a - b, 8) for a, b in zip(
        returns_by_group["D1"], returns_by_group[f"D{n_groups}"])]

    summary: dict[str, dict] = {}
    for label in list(net_values):
        nv = pl.Series(net_values[label])
        if label == "long_short":
            rets = pl.Series(ls_returns)
        else:
            rets = pl.Series(returns_by_group[label])
        summary[label] = _summary_metrics(nv, rets)

    return {
        "n_groups": n_groups,
        "periods": len(dates),
        "net_values": net_values,
        "summary": summary,
        "dates": [str(d) for d in dates],
    }
```

（实现以测试通过为准：分档边界（n 不整除 n_groups 时末档更小）、direction 翻转的 rank 方向、
档空期的 fill_null(0.0) 语义——设计说"净值保持前值"，fill_null(0) 后 cum_prod 保持 ✓。）

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_layered.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/eval/layered.py tests/test_layered.py
git commit -m "feat: add layered backtest with direction-aware groups"
```

---

### Task 2: run 命令扩展 + M4a 遗留接线

**Files:**
- Modify: `src/factorlab/cli/main.py`（--backtest/--no-backtest/--groups、weekly 落盘优化）
- Modify: `src/factorlab/config.py`（results_dir）
- Modify: `src/factorlab/engine/compute.py`（pit_qfq asof 传递）
- Test: `tests/test_cli_run.py`、`tests/test_run_factor.py`（Modify）

- [ ] **Step 1: Write the failing test**

`tests/test_run_factor.py` 新增：

```python
def test_run_factor_pit_qfq_asof(tmp_path):
    # spec.adjustment=pit_qfq：view_prices asof=spec.date.end（研究日视角）
    build_db(tmp_path)  # 平台库风格
    spec_path = ...  # adjustment: pit_qfq, date.end=2024-01-09
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=...))
    assert result.panel.height > 0  # pit_qfq 装配不崩
```

`tests/test_cli_run.py` 新增：

```python
def test_run_backtest_flag(tmp_path, monkeypatch):
    # --backtest（默认）：summary.evaluation 含 layered_backtest
    ...（复用 test_run_end_to_end 的 tmp 库/spec）
    result = runner.invoke(app, ["run", str(spec_path)])
    summary = json.loads(...)
    assert "layered_backtest" in summary["evaluation"]


def test_run_no_backtest_flag(tmp_path, monkeypatch):
    result = runner.invoke(app, ["run", "--no-backtest", str(spec_path)])
    summary = json.loads(...)
    assert "layered_backtest" not in summary["evaluation"]


def test_run_groups_param(tmp_path, monkeypatch):
    result = runner.invoke(app, ["run", "--groups", "5", str(spec_path)])
    summary = json.loads(...)
    assert summary["evaluation"]["layered_backtest"]["n_groups"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_run.py tests/test_run_factor.py -q`
Expected: FAIL — run 无 backtest 参数；pit_qfq asof 未传递。

- [ ] **Step 3: Implement**

`src/factorlab/config.py`：

```python
    results_dir: Path = Path("results")  # FACTORLAB_RESULTS_DIR 可覆盖；run 落盘根目录
```

`src/factorlab/engine/compute.py` 的 run_factor 装配（pit_qfq asof）：

```python
        adjustment = getattr(spec, "adjustment", None) or ctx.adjustment
        asof = None
        if adjustment == "pit_qfq":
            asof = spec.date.end or str(panel["date"].max())
        panel = view_prices(panel, adjustment, asof=asof)
```

（view_prices 的 asof 参数需支持 str 'YYYY-MM-DD'——M4a 的 asof 是 datetime.date——
**实现时确认**：view_prices 的 pit_qfq 分支 filter date <= asof——date 是 pl.Date，asof 需兼容
str/date。若 str 不支持，run_factor 转 date 对象。）

`src/factorlab/cli/main.py` 的 run 命令扩展：

```python
@app.command("run")
def run_factor_cli(spec_path: Path, universe: str | None = None, max_memory: str = "4GB",
                   output_dir: Path | None = None, float32: bool = True,
                   backtest: bool = True, groups: int = 10) -> None:
    """计算因子并评估（平台库）。--backtest 默认产出分层回测；--no-backtest 关闭。"""
    from factorlab.engine.compute import RunContext, run_factor as run_impl
    from factorlab.eval.alignment import align_weekly
    from factorlab.eval.layered import layered_backtest
    from factorlab.eval.rust_ic import evaluate_factor_weekly

    spec = load_spec(spec_path)
    ctx = RunContext(
        db_path=settings.platform_db,
        output_dir=output_dir or (settings.results_dir / spec.name),
        universe_override=universe or settings.default_universe,
        float32=float32,
    )
    result = run_impl(spec, ctx)
    weekly = align_weekly(result.panel)
    weekly.write_parquet(ctx.output_dir / "weekly.parquet")  # 周频对齐面板（评估/回测输入）
    evaluation = evaluate_factor_weekly(result.panel, spec.name, spec.direction)
    if backtest:
        evaluation["layered_backtest"] = layered_backtest(weekly, spec.direction, n_groups=groups)
    result.summary["evaluation"] = evaluation
    (ctx.output_dir / "summary.json").write_text(
        json.dumps(result.summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    ...
```

**注意**：`evaluate_factor_weekly` 内部也 align_weekly（重复对齐）——weekly 变量已对齐，
评估可改用 weekly 输入？**保持现状**（evaluate_factor_weekly 吃日频面板——它内部对齐；
weekly 变量单独用于回测与落盘）。**性能优化**（可选）：evaluate_factor_weekly 增加
`already_aligned` 参数——本任务不做（YAGNI）。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_run.py tests/test_run_factor.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/config.py src/factorlab/engine/compute.py src/factorlab/cli/main.py tests/test_cli_run.py tests/test_run_factor.py
git commit -m "feat: extend run with backtest flag, pit_qfq asof, results_dir"
```

---

### Task 3: CLI list / show

**Files:**
- Modify: `src/factorlab/cli/main.py`
- Test: `tests/test_cli_list_show.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_list_show.py`：

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from factorlab.cli.main import app

runner = CliRunner()


def _write_summary(results_dir: Path, name: str, **overrides):
    out = results_dir / name
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "name": name, "category": "custom", "direction": 1,
        "universe_count": 5, "panel_rows": 100,
        "evaluation": {"ic": {"mean": 0.05}, "decile_returns": {"spread": {"ret": 0.02}}},
        "timestamp": "2026-08-16T12:00:00",
    }
    summary.update(overrides)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


def test_list_shows_factors(monkeypatch, tmp_path):
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path)
    _write_summary(tmp_path, "alpha_1")
    _write_summary(tmp_path, "beta_2")
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "alpha_1" in result.stdout and "beta_2" in result.stdout
    assert "0.05" in result.stdout  # IC 摘要


def test_list_empty_results(monkeypatch, tmp_path):
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path / "nope")
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "暂无" in result.stdout


def test_show_factor_summary(monkeypatch, tmp_path):
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path)
    _write_summary(tmp_path, "alpha_1")
    result = runner.invoke(app, ["show", "alpha_1"])
    assert result.exit_code == 0
    assert "alpha_1" in result.stdout and "0.05" in result.stdout


def test_show_missing_factor(monkeypatch, tmp_path):
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path)
    result = runner.invoke(app, ["show", "ghost"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_list_show.py -v`
Expected: FAIL — list/show 命令不存在。

- [ ] **Step 3: Implement**

`src/factorlab/cli/main.py`：

```python
@app.command("list")
def list_factors() -> None:
    """列出已保存因子与最近运行摘要。"""
    results_dir = settings.results_dir
    if not results_dir.exists():
        console.print("暂无因子结果（先运行 factorlab run）")
        return
    rows = []
    for summary_path in sorted(results_dir.glob("*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        ev = summary.get("evaluation", {})
        rows.append({
            "name": summary.get("name", summary_path.parent.name),
            "category": summary.get("category", ""),
            "direction": summary.get("direction", ""),
            "ic_mean": ev.get("ic", {}).get("mean"),
            "spread": ev.get("decile_returns", {}).get("spread", {}).get("ret"),
            "run_at": summary.get("timestamp", ""),
        })
    if not rows:
        console.print("暂无因子结果（先运行 factorlab run）")
        return
    for row in sorted(rows, key=lambda r: str(r["run_at"]), reverse=True):
        console.print(f"{row['name']} | {row['category']} | dir={row['direction']} "
                      f"| ic={row['ic_mean']} | spread={row['spread']} | {row['run_at']}")


@app.command("show")
def show_factor(name: str) -> None:
    """查看单因子完整摘要（spec/评估/分层回测）。"""
    summary_path = settings.results_dir / name / "summary.json"
    if not summary_path.exists():
        console.print(f"错误: 因子 {name} 不存在（{settings.results_dir / name}）")
        raise typer.Exit(code=1)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    console.print(f"=== {name} ===")
    console.print(f"spec: {summary.get('spec_yaml', '')}")
    console.print(f"评估: ic={summary.get('evaluation', {}).get('ic')}")
    console.print(f"分层回测: {summary.get('evaluation', {}).get('layered_backtest', {}).get('summary', '无')}")
```

（list/show 的展示用 rich 表更佳——实现时可升级为 table；测试断言名称/IC 出现即可。）

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_list_show.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/cli/main.py tests/test_cli_list_show.py
git commit -m "feat: add factorlab list and show commands"
```

---

### Task 4: 集成验证与文档汇总

**Files:**
- Modify: `tests/test_e2e_m4.py`（backtest 断言）
- Modify: `docs/interface.md`、`docs/data-ops-playbook.md`
- Test: 全量验证

- [x] **Step 1: 集成测试扩展**

`tests/test_e2e_m4.py` 的 `test_e2e_real_factor_run` 增加：

```python
    weekly = align_weekly(result.panel)
    bt = layered_backtest(weekly, 1)
    assert bt["periods"] == evaluation["n_weeks"]  # 回测期数 = 评估周数
    assert bt["summary"]["long_short"]["sharpe"] == bt["summary"]["long_short"]["sharpe"]  # 非 nan
    assert len(bt["net_values"]["D1"]) == bt["periods"]  # 净值序列逐期一点
```

另加 CLI 级端到端 `test_e2e_cli_run_layered_backtest`（真实平台库 `runner.invoke run` →
summary.evaluation.layered_backtest 期数 = n_weeks）。

**集成验证发现的设计缺口（已修复，T4 内补 T1 单测）**：真实数据 2 年 5 只跑出
`bt["periods"]=104 ≠ evaluation["n_weeks"]=98`——layered 把 signal/forward 全 null 的周
（头部 ts 窗口未满 4 周 + 尾部无未来收益 2 周）也计入期数（fill_null(0) 平值假净值），
quant_core 只计有效周。设计 spec 示例（`periods: 98`）与 §2.3「signal 全 null → 空回测」
表明设计意图为期数 = 有效周数。修复：`layered_backtest` 先过滤
`signal/forward_return_5d` 非 null 行再分档计期（周内部分 null 仍计入）；新增单测
`test_layered_backtest_dead_week_excluded` / `test_layered_backtest_all_null_signal_empty` /
`test_layered_backtest_tail_week_with_partial_null_kept`。修复后 104→98，断言成立。

- [x] **Step 2: 文档更新**

`docs/interface.md`：layered_backtest API、run 参数（--backtest/--groups）、list/show 命令、
results_dir、pit_qfq 消费说明。
`docs/data-ops-playbook.md`：§6 更新（run 默认产出分层回测；list/show 加入闭环）。

- [x] **Step 3: 全量验证**

Run: `python -m pytest -q`
Expected: 全部 PASS（含集成——真实平台库 run + 分层回测）。

- [x] **Step 4: Commit**

```bash
git add tests/test_e2e_m4.py docs/interface.md docs/data-ops-playbook.md
git commit -m "docs: document M4b layered backtest and factor listing"
```

---

## Self-Review

**1. Spec coverage（对照 M4b spec）：**
- §2 分层回测（输入/语义/输出/边界）→ Task 1 ✓
- §3.1 run 参数 → Task 2 ✓；§3.2 weekly 落盘 → Task 2 ✓；§3.3 pit_qfq → Task 2 ✓；
  §3.4 results_dir 锚定 → Task 2 ✓
- §4 list/show → Task 3 ✓；§5 测试策略 → 各任务 + Task 4 集成 ✓；§6 不做（多因子）→ 计划不含 ✓

**2. Placeholder scan：** 无 TBD/TODO；Task 2 的 view_prices asof 兼容性给了实现注记（str/date 转换）。

**3. Type consistency：** `layered_backtest(panel, direction, n_groups=10, cost=0.0)`、
`evaluate_factor_weekly`（不变）、`align_weekly`（不变）、run 参数（--backtest/--groups）任务间一致 ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-16-factorlab-m4b-single-factor-eval.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks.
2. Inline Execution - execute tasks in this session using executing-plans with checkpoints.

Which approach?
