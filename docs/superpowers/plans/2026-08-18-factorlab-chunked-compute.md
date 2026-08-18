# 分块计算（Chunked Compute）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `factorlab run` 支持按交易日分块计算，把 16GB 内存极限从 ~3.5 年样本扩展到全历史（2015+），并保证分块结果与整段跑逐 cell 一致。

**Architecture:** 按日期分块 + warmup 重叠：日历切成 chunk_days 交易日/块，每块独立跑完整流水线（load→fill_suspensions→forward→view→formula→process），warmup 段提供 TS 窗口历史，块内横截面完整保证 CS 算子语义，qfq 时 adj_factor 按全局基准归一保证绝对水平因子一致，最后丢弃 warmup 行 concat。`chunk_days=None` 保持现行单块路径逐字节不变。

**Tech Stack:** Python 3.13 / polars / duckdb / typer / expr_codegen / pytest

**设计依据:** `docs/superpowers/specs/2026-08-18-factorlab-chunked-compute-design.md`

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `src/factorlab/data/calendar.py` | 新增 `chunk_calendar`（日历切块，纯函数） |
| `src/factorlab/engine/compute.py` | 新增 `_ts_window_days`（AST 窗口提取）、`_load_base_adj`（全局复权基准）、`_compute_panel`（单块流水线提取）；`RunContext` 加 `chunk_days`/`warmup_days`；`run_factor` 加分块分支 |
| `src/factorlab/cli/main.py` | `run` 命令加 `--chunk-days`/`--warmup-days` |
| `tests/test_calendar.py` | `chunk_calendar` 单元测试（追加） |
| `tests/test_compute.py` | `_ts_window_days` 单元测试（追加） |
| `tests/test_run_factor.py` | 分块 smoke + 一致性回归 + 错误路径（追加；复用既有 `build_db`） |
| `docs/interface.md` | run 参数表 + 分块计算章节 |

---

### Task 1: chunk_calendar（日历切块）

**Files:**
- Modify: `src/factorlab/data/calendar.py`（函数追加到文件末尾）
- Test: `tests/test_calendar.py`（追加到文件末尾）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_calendar.py`）

```python
# ---------- chunk_calendar ----------


def _cal(days: list[str]) -> pl.Series:
    return pl.Series("date", [datetime.date.fromisoformat(d) for d in days], dtype=pl.Date)


def test_chunk_calendar_basic_chunks():
    cal = _cal(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
                "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11",
                "2024-01-12", "2024-01-15", "2024-01-16", "2024-01-17"])
    chunks = chunk_calendar(cal, chunk_days=5)
    assert chunks == [
        (datetime.date(2024, 1, 2), datetime.date(2024, 1, 2), datetime.date(2024, 1, 8)),
        (datetime.date(2024, 1, 9), datetime.date(2024, 1, 9), datetime.date(2024, 1, 15)),
        (datetime.date(2024, 1, 16), datetime.date(2024, 1, 16), datetime.date(2024, 1, 17)),
    ]


def test_chunk_calendar_warmup_overlaps_previous_chunk():
    # 12 天日历、chunk 5、warmup 2：块 1/2 的 load 段向块首前推 2 个交易日
    cal = _cal(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
                "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11",
                "2024-01-12", "2024-01-15", "2024-01-16", "2024-01-17"])
    chunks = chunk_calendar(cal, chunk_days=5, warmup_days=2)
    assert chunks[1] == (
        datetime.date(2024, 1, 5), datetime.date(2024, 1, 9), datetime.date(2024, 1, 15),
    )
    assert chunks[2] == (
        datetime.date(2024, 1, 12), datetime.date(2024, 1, 16), datetime.date(2024, 1, 17),
    )


def test_chunk_calendar_warmup_truncated_at_head():
    # 首块 load 段越界（warmup 超过日历起点）→ 截断到日历首日
    cal = _cal(["2024-01-02", "2024-01-03", "2024-01-04"])
    chunks = chunk_calendar(cal, chunk_days=2, warmup_days=10)
    assert chunks[0] == (datetime.date(2024, 1, 2), datetime.date(2024, 1, 2), datetime.date(2024, 1, 3))
    assert chunks[1] == (datetime.date(2024, 1, 2), datetime.date(2024, 1, 4), datetime.date(2024, 1, 4))


def test_chunk_calendar_exact_division():
    cal = _cal(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"])
    chunks = chunk_calendar(cal, chunk_days=3)
    assert chunks == [
        (datetime.date(2024, 1, 2), datetime.date(2024, 1, 2), datetime.date(2024, 1, 4)),
        (datetime.date(2024, 1, 5), datetime.date(2024, 1, 5), datetime.date(2024, 1, 9)),
    ]


def test_chunk_calendar_empty_calendar_returns_empty():
    assert chunk_calendar(pl.Series("date", [], dtype=pl.Date), chunk_days=5) == []


def test_chunk_calendar_invalid_params_raise():
    cal = _cal(["2024-01-02", "2024-01-03"])
    with pytest.raises(ValueError, match="chunk_days"):
        chunk_calendar(cal, chunk_days=0)
    with pytest.raises(ValueError, match="warmup_days"):
        chunk_calendar(cal, chunk_days=5, warmup_days=-1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_calendar.py -q`
Expected: 6 个新测试 FAIL（`ImportError: cannot import name 'chunk_calendar'`）

- [ ] **Step 3: 最小实现**（追加到 `src/factorlab/data/calendar.py` 末尾）

```python
def chunk_calendar(
    cal: pl.Series,
    chunk_days: int,
    warmup_days: int = 0,
) -> list[tuple[datetime.date, datetime.date, datetime.date]]:
    """日历切块：(load_start, chunk_start, chunk_end) 三元组（日期含两端，升序）。

    chunk_days：每块交易日数（>=1）；warmup_days：块首向前多取的预热天数
    （TS 窗口历史，>=0；首块越界自动截断）。load 段 = chunk 段 + warmup 段，
    相邻块 load 段重叠 warmup_days 天（每块独立重取，无块间依赖）。
    cal 需升序去重。空日历 → []。
    """
    if chunk_days < 1:
        raise ValueError(f"chunk_days 必须 >= 1（收到 {chunk_days}）")
    if warmup_days < 0:
        raise ValueError(f"warmup_days 必须 >= 0（收到 {warmup_days}）")
    dates = cal.to_list()
    n = len(dates)
    if n == 0:
        return []
    chunks = []
    for start in range(0, n, chunk_days):
        end = min(start + chunk_days, n) - 1
        load_start = max(start - warmup_days, 0)
        chunks.append((dates[load_start], dates[start], dates[end]))
    return chunks
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_calendar.py -q`
Expected: 全部 PASS（原 13 个 + 新 6 个）

- [ ] **Step 5: 提交**

```bash
git add src/factorlab/data/calendar.py tests/test_calendar.py
git commit -m "feat(engine): add chunk_calendar for date-chunked compute

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: _ts_window_days（AST 窗口提取）

**Files:**
- Modify: `src/factorlab/engine/compute.py`（`_formula_columns` 之后插入）
- Test: `tests/test_compute.py`（追加到文件末尾）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_compute.py`）

```python
# ---------- _ts_window_days ----------


def test_ts_window_single():
    assert _ts_window_days("signal = ts_mean(close, 20)") == 20


def test_ts_window_takes_max_of_multiple():
    formula = """
_a = ts_mean(close, 5)
_b = ts_std_dev(close, 60)
signal = _a + _b
"""
    assert _ts_window_days(formula) == 60


def test_ts_window_no_window_ops_returns_zero():
    assert _ts_window_days("signal = cs_rank(-close)") == 0


def test_ts_window_variable_window_ignored():
    # 参数化 ${w} 已在展开链替换为字面量；未替换的变量窗口不参与提取
    assert _ts_window_days("signal = ts_mean(close, w)") == 0


def test_ts_window_float_window_ignored():
    assert _ts_window_days("signal = ts_mean(close, 2.5)") == 0


def test_ts_window_qualified_name_and_ta_family():
    assert _ts_window_days("signal = wq.ts_sum(close, 10) + ta_MA(close, 5)") == 10
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_compute.py -q`
Expected: 6 个新测试 FAIL（`ImportError: cannot import name '_ts_window_days'`）
（`tests/test_compute.py` 顶部 import 需补 `_ts_window_days`）

- [ ] **Step 3: 最小实现**（`src/factorlab/engine/compute.py`，`_formula_columns` 之后插入）

```python
_WINDOW_PREFIXES = ("ts_", "ta_")  # 窗口参数在第二位置的算子族（tdx_* 参数语义不同，不提取）


def _ts_window_days(formula: str) -> int:
    """AST 提取公式中所有 ts_*/ta_* 窗口算子的窗口参数最大值（第二位置参数，int 字面量）；
    无窗口算子 → 0（纯 CS/元素级公式不需要 warmup）。窗口参数非常量时忽略该项。"""
    tree = ast.parse(formula)
    windows = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in ("wq", "ta"):
            name = node.func.attr
        else:
            continue
        if not name.startswith(_WINDOW_PREFIXES):
            continue
        arg = node.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, int) and not isinstance(arg.value, bool):
            windows.append(arg.value)
    return max(windows) if windows else 0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_compute.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/factorlab/engine/compute.py tests/test_compute.py
git commit -m "feat(engine): extract ts window length from formula AST

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: run_factor 分块路径（核心重构）

把 `run_factor` 的单块流水线提取为 `_compute_panel`（行为不变），新增
`_load_base_adj`（qfq 全局复权基准）与分块分支。**验收：既有 `test_run_factor.py`
全绿（单块路径回归）+ 新分块 smoke 测试通过。**

**Files:**
- Modify: `src/factorlab/engine/compute.py`（`RunContext` 加字段；新增两个函数；`run_factor` 重构）
- Test: `tests/test_run_factor.py`（追加）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_run_factor.py` 末尾）

```python
def test_run_factor_chunked_smoke(tmp_path):
    # 分块跑通：12 天日历、chunk 2（6 块）、warmup 1 → panel 行数 = 12 天 × 2 代码
    build_db(tmp_path, n_days=12)
    spec = _spec(tmp_path)
    spec.date.end = "2024-01-17"
    out_dir = tmp_path / "out_chunked"
    result = run_factor(spec, RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=out_dir, chunk_days=2, warmup_days=1))
    assert result.panel.height == 12 * 2
    assert result.panel["date"].min() == datetime.date(2024, 1, 2)
    assert result.panel["date"].max() == datetime.date(2024, 1, 17)
    assert result.panel["signal"].is_not_null().sum() > 0
    assert json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))["panel_rows"] == 24


def test_run_factor_chunked_invalid_chunk_days(tmp_path):
    build_db(tmp_path, n_days=12)
    spec = _spec(tmp_path)
    with pytest.raises(ValueError, match="chunk_days"):
        run_factor(spec, RunContext(
            db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_bad", chunk_days=0))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_run_factor.py -q`
Expected: 2 个新测试 FAIL（`TypeError: __init__() got an unexpected keyword argument 'chunk_days'`）

- [ ] **Step 3: 实现**

**3a. `RunContext` 加字段**（`compute.py` 第 109-118 行 dataclass）：

```python
@dataclass
class RunContext:
    """运行上下文。universe_override：6 位代码（如 600519）、universe 引用名或 yaml 文件路径。
    adjustment：复权视图口径兜底（raw|qfq|hfq|pit_qfq；spec.adjustment 声明时以 spec 为准）。
    chunk_days：日期分块（交易日/块；None=单块整段跑）。warmup_days：TS 窗口预热天数
    （None=按公式自动提取窗口最大值 + 20 安全垫）。"""

    db_path: Path = _settings.platform_db
    output_dir: Path = Path("results")
    universe_override: str | None = None
    float32: bool = _settings.use_float32
    adjustment: str = "qfq"
    chunk_days: int | None = None
    warmup_days: int | None = None
```

**3b. 新增两个函数**（`compute.py`，`run_factor` 之前插入）：

```python
_WARMUP_SAFETY_PAD = 20  # 自动 warmup 的安全垫：覆盖 ts_delay 等窗口内偏移


def _load_base_adj(con: duckdb.DuckDBPyConnection, date_end: str | None) -> pl.DataFrame:
    """全局 qfq 复权基准：每代码在 <= date_end 的最新 adj_factor（与整段跑的组内 latest 语义一致）。

    返回 (code, base_adj) 两列 DataFrame；date_end 为 ISO 'YYYY-MM-DD' 或 'YYYYMMDD'。
    """
    where, params = "", []
    if date_end:
        where, params = " WHERE trade_date <= ?", [date_end.replace("-", "")]
    return con.execute(
        f"SELECT substr(ts_code, 1, 6) AS code, "
        f"last(adj_factor ORDER BY trade_date) AS base_adj "
        f"FROM adj_factor{where} GROUP BY substr(ts_code, 1, 6)",
        params,
    ).pl()


def _compute_panel(
    con: duckdb.DuckDBPyConnection,
    ctx: RunContext,
    spec: FactorSpec,
    formula: str,
    codes: list[str],
    date_start: str,
    date_end: str,
    cal: pl.Series,
    base_adj: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """单块流水线：load（SQL 按段过滤）→ 停牌补全 → 前向收益 → 复权视图 → 因子 → process。

    base_adj 仅在 qfq 时传入（分块路径）：归一 adj_factor 使组内最新=1 → factor=adj/base_adj，
    跨块绝对水平因子与整段跑一致。hfq/pit_qfq 不归一（归一会改变 hfq 结果；pit_qfq 分子分母同消）。
    """
    cols = _formula_columns(formula) + ["close", "adj_factor"]
    raw = load_daily(
        ctx.db_path, codes,
        date_start=date_start, date_end=date_end,
        cols=cols, float32=ctx.float32,
    ).collect()
    panel = fill_suspensions(raw, cal)
    if panel.height == 0:
        raise ValueError("日期段无数据，可运行 data refresh（M3b）")
    adjustment = getattr(spec, "adjustment", None) or ctx.adjustment
    if adjustment == "qfq" and base_adj is not None:
        panel = panel.join(base_adj, on="code", how="left").with_columns(
            (pl.col("adj_factor") / pl.col("base_adj")).alias("adj_factor")
        ).drop("base_adj")
    panel = compute_forward_returns(panel)
    asof = None
    if adjustment == "pit_qfq":
        asof = datetime.date.fromisoformat(spec.date.end) if spec.date.end else panel["date"].max()
    panel = view_prices(panel, adjustment, asof=asof)
    panel = panel.join(compute_formula(panel, formula), on=["date", "code"], how="left")
    panel = run_process_chain(panel, spec.process, ctx=con)
    return panel
```

**3c. `run_factor` 重构**：把原 154-184 行的加载-计算段替换为：

```python
        codes = resolve_codes(spec, con, override=ctx.universe_override)
        cal = trading_calendar(ctx.db_path, date_start=spec.date.start, date_end=spec.date.end)
        # trade_cal 含未来公告日（~94 个到 20261231）：补全面板截断到今天，不产生未来 null 行
        today = datetime.date.today()
        cal = cal.filter(cal <= today)
        if ctx.chunk_days is None:
            # 单块整段（现行路径，逐字节不变）：base_adj=None → qfq 组内 latest 基准
            panel = _compute_panel(con, ctx, spec, formula, codes, spec.date.start, spec.date.end, cal)
        else:
            warmup = ctx.warmup_days if ctx.warmup_days is not None \
                else _ts_window_days(formula) + _WARMUP_SAFETY_PAD
            chunks = chunk_calendar(cal, ctx.chunk_days, warmup)
            base_adj = _load_base_adj(con, spec.date.end)
            panels = []
            for load_start, chunk_start, chunk_end in chunks:
                cal_chunk = cal.filter((cal >= load_start) & (cal <= chunk_end))
                chunk_panel = _compute_panel(
                    con, ctx, spec, formula, codes, load_start, chunk_end, cal_chunk, base_adj)
                panels.append(chunk_panel.filter(pl.col("date") >= chunk_start))
            panel = pl.concat(panels)
```

原 154-184 行从 `codes = resolve_codes(...)` 到 `panel = run_process_chain(...)` 删除
（被 `_compute_panel` 调用取代）。`formula_cols` 变量不再需要（移入 `_compute_panel`）。
`con` 的 with 块、`summary`/落盘部分保持不动（操作 concat 后的 `panel`）。

`compute.py` 顶部 import 补：

```python
from factorlab.data.calendar import chunk_calendar, fill_suspensions, trading_calendar
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_run_factor.py tests/test_compute.py tests/test_calendar.py -q`
Expected: 全部 PASS（既有单块测试 = 重构回归；新 smoke 通过）

- [ ] **Step 5: 提交**

```bash
git add src/factorlab/engine/compute.py tests/test_run_factor.py
git commit -m "feat(engine): chunked compute path in run_factor

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: CLI 参数接线

**Files:**
- Modify: `src/factorlab/cli/main.py:118-160`
- Test: `tests/test_cli_run.py`（追加，参照该文件既有 CLI 测试模式）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_cli_run.py`；如该文件无既有模式，用 `typer.testing.CliRunner` 或直接断言参数存在——按该文件既有风格）

```python
def test_run_cli_accepts_chunk_options(tmp_path):
    # --chunk-days/--warmup-days 接线到 RunContext：分块跑通且摘要正确
    # （参照本文件既有 run CLI 测试的建库与调用方式）
    ...
    result = runner.invoke(app, ["run", str(spec_path), "--chunk-days", "2", "--warmup-days", "1", "--no-backtest", ...])
    assert result.exit_code == 0
    assert "panel_rows" in ...
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cli_run.py -q`
Expected: FAIL（`no such option: --chunk-days`）

- [ ] **Step 3: 实现**（`main.py` `run_factor_cli` 签名，`set_params` 之后加两参）

```python
    chunk_days: int | None = typer.Option(None, "--chunk-days", min=1,
                                          help="日期分块（交易日/块；缺省=单块整段跑）"),
    warmup_days: int | None = typer.Option(None, "--warmup-days", min=0,
                                           help="TS 窗口预热天数（缺省=按公式自动提取窗口+20）"),
```

`RunContext(...)` 调用补两参：

```python
    ctx = RunContext(
        db_path=settings.platform_db,
        output_dir=output_dir or (settings.results_dir / variant),
        universe_override=universe or settings.default_universe,
        float32=float32,
        chunk_days=chunk_days,
        warmup_days=warmup_days,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_cli_run.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/factorlab/cli/main.py tests/test_cli_run.py
git commit -m "feat(cli): add --chunk-days/--warmup-days to run

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 一致性回归（关键测试）

验证分块 vs 整段**逐 cell 一致**：signal 全部相等（含绝对水平 close 输入 → 验证 qfq
归一）；forward 除块边界 null 外相等。两个场景：混合公式（ts_ + cs_rank + process）、
纯 CS 公式（warmup=0）。

**Files:**
- Modify: `tests/test_run_factor.py`（追加到文件末尾）

- [ ] **Step 1: 写测试**（追加到 `tests/test_run_factor.py` 末尾）

```python
# ---------- 分块一致性回归 ----------

_CHUNK_FORMULA = """
from polars_ta.prefix.wq import ts_mean, ts_std_dev, cs_rank
_m = ts_mean(close, 3)
_v = ts_std_dev(close, 3)
signal = cs_rank(-_m) + log(close) - _v
"""


def _chunk_spec(tmp_path):
    path = tmp_path / "spec_chunk.yaml"
    path.write_text("""
name: demo_chunk
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
date:
  start: "2024-01-02"
  end: "2024-01-17"
process:
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_std_dev, cs_rank
  _m = ts_mean(close, 3)
  _v = ts_std_dev(close, 3)
  signal = cs_rank(-_m) + log(close) - _v
""", encoding="utf-8")
    return load_spec(path)


def test_chunked_consistency_with_full_run(tmp_path):
    # 关键回归：分块（含 qfq 归一）vs 整段跑，signal 逐 cell 相等、forward 非 null 区相等
    # chunk_days=6（12 天 → 2 块）：块内首行有完整 forward_5d（需未来 5 个交易日），
    #   非 null 交集 = 块 0 首行 + 块 1 首行 × 2 代码 = 4 行，可验证 forward 一致性
    build_db(tmp_path, ex_date=True, n_days=12)
    spec = _chunk_spec(tmp_path)
    full = run_factor(spec, RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_full", float32=False))
    chunked = run_factor(spec, RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_chunked",
        float32=False, chunk_days=6, warmup_days=1))
    joined = full.panel.join(chunked.panel, on=["date", "code"], how="inner", suffix="_c")
    # 行数一致（12 天 × 2 代码；warmup 段行已在分块内丢弃）
    assert joined.height == full.panel.height == 12 * 2
    # signal 逐 cell 相等（float64：1e-9；含 log(close) 绝对水平输入 → 验证 qfq 归一）
    diff = (joined["signal"] - joined["signal_c"]).abs().max()
    assert float(diff) < 1e-9
    # forward：仅两边都非 null 的行可比（块边界 null 是接受的差异）
    mask = joined["forward_return_5d"].is_not_null() & joined["forward_return_5d_c"].is_not_null()
    assert mask.sum() == 4  # 块 0 首行 + 块 1 首行 × 2 代码
    fdiff = (joined.filter(mask)["forward_return_5d"] - joined.filter(mask)["forward_return_5d_c"]).abs().max()
    assert float(fdiff) < 1e-9
    # 块边界 forward null 存在但受限：2 块 → 块尾 5 天 × 2 代码
    null_rows = joined.filter(joined["forward_return_5d"].is_not_null() & joined["forward_return_5d_c"].is_null())
    assert null_rows.height <= 5 * 2


def test_chunked_pure_cs_consistency(tmp_path):
    # 纯 CS 公式（无 ts_ 窗口）→ warmup 自动=0；分块 vs 整段一致
    build_db(tmp_path, n_days=12)
    spec = _chunk_spec(tmp_path)
    spec.formula = "signal = cs_rank(-close)"
    full = run_factor(spec, RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_pure_full", float32=False))
    chunked = run_factor(spec, RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_pure_chunked",
        float32=False, chunk_days=3))
    joined = full.panel.join(chunked.panel, on=["date", "code"], how="inner", suffix="_c")
    assert joined.height == full.panel.height == 12 * 2
    diff = (joined["signal"] - joined["signal_c"]).abs().max()
    assert float(diff) < 1e-9
```

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/test_run_factor.py -q`
Expected: 2 个新测试 PASS（若失败，排查 `_compute_panel` 的 qfq 归一或 warmup 逻辑）

- [ ] **Step 3: 提交**

```bash
git add tests/test_run_factor.py
git commit -m "test(engine): chunked vs full-run consistency regression

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 文档同步

**Files:**
- Modify: `docs/interface.md`

- [ ] **Step 1: 读 `docs/interface.md` 的 run 命令参数表**，在参数表补两行

```markdown
| `--chunk-days N` | 日期分块（交易日/块；缺省=单块整段跑）。样本超过 ~3.5 年（约 850 交易日）全网格内存触顶 16GB 时使用 |
| `--warmup-days N` | TS 窗口预热天数（缺省=按公式自动提取窗口最大值+20） |
```

- [ ] **Step 2: 新增"分块计算"章节**（run 命令章节之后）

```markdown
## 分块计算（--chunk-days）

长样本（2015+）全市场面板超过 16GB 内存护栏时，按交易日分块计算：

```
factorlab run factor/crash_bottom_leader_timed.yaml --chunk-days 500
```

**语义保证**（与单块整段跑逐 cell 一致）：

- TS 窗口（ts_*/ta_*）：每块带 warmup 重叠（自动提取公式窗口最大值 + 20 天），
  窗口历史完整；
- CS 算子（cs_rank/winsorize/standardize 等 per-date 横截面）：块内每日期全市场
  股票完整，结果与整段跑一致；
- qfq 复权：块内 adj_factor 按全局基准（样本末最新 adj）归一，绝对水平类因子
  （直接用 close 值的公式）跨块一致；hfq/pit_qfq 无需处理（hfq 无基准；
  pit_qfq 的 asof 全局固定）。

**已知限制**：

- 每块块尾的 forward_return_h 为 null（块尾无未来数据；单块跑只有样本末如此），
  周频评估时该周跳过，块大小 500 天时损失 <1%；
- process 链的 `fillna(method="forward")` 在块首重新填充，块边界前几行与单块
  跑略异（低频使用）；
- 块大小 + warmup 应控制在约 850 交易日以内（单块内存 ≈ 已验证可跑的 3.5 年量级）。

**warmup 自动提取**：`--warmup-days` 缺省时从公式 AST 提取所有 ts_*/ta_* 调用的
窗口参数最大值 + 20 天安全垫；纯横截面公式 warmup=0。
```

- [ ] **Step 3: 提交**

```bash
git add docs/interface.md
git commit -m "docs: document chunked compute in interface.md

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 全量测试 + 扩样验证

**Files:**
- Modify: `factor/crash_bottom_leader_timed.yaml`（`start: "2023-01-01"` → `"2015-01-01"`）
- Modify: `docs/factors/crash_bottom_leader_timed.md`（扩样后更新验证数据）

- [ ] **Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: 全部 PASS（0 failures）

- [ ] **Step 2: 扩样重跑股灾策略**

```bash
python -m pytest -q  # 确认全绿后
FLAB=/c/Users/ThinkPad/AppData/Roaming/Python/Python313/Scripts/factorlab.exe
```

改 `factor/crash_bottom_leader_timed.yaml` 第 7 行 `start: "2023-01-01"` → `start: "2015-01-01"`，然后：

```bash
$FLAB run factor/crash_bottom_leader_timed.yaml --chunk-days 500
```

Expected: 跑通（2015-2026 ≈ 2806 交易日 → ~6 块），无段错误；`results/crash_bottom_leader_timed/summary.json` 的 `n_weeks` 显著大于 14（2015 股灾/2016 熔断/2018 熊市/2024 微盘/2025 关税/2026 多段均应触发）。若某块失败，读报错修复重跑。

- [ ] **Step 3: 更新策略档案** `docs/factors/crash_bottom_leader_timed.md`：替换 §4 验证数据快照为扩样结果（触发周数、IC、分层、long_short 年化/Sharpe），注明"分块计算（--chunk-days 500）"与快照日期。

- [ ] **Step 4: 提交**

```bash
git add factor/crash_bottom_leader_timed.yaml docs/factors/crash_bottom_leader_timed.md
git commit -m "feat(strategy): extend crash-bottom sample to 2015 with chunked compute

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec 覆盖对照：**

| Spec 要求 | 计划任务 |
|-----------|---------|
| `chunk_calendar` 切块函数 | Task 1 |
| `_ts_window_days` AST 提取（无窗口=0、变量窗口忽略） | Task 2 |
| `RunContext.chunk_days` + 分块循环 + 块尾丢弃 warmup | Task 3 |
| `_load_base_adj` SQL 全局基准 + qfq 归一（仅 qfq） | Task 3（3b） |
| CLI `--chunk-days`/`--warmup-days` | Task 4 |
| 一致性回归（逐 cell signal、forward 边界 null 受限） | Task 5 |
| 纯 CS 公式 warmup=0 一致性 | Task 5 |
| 错误路径（chunk_days<1、warmup_days<0） | Task 1 + Task 3 smoke |
| `docs/interface.md` 参数表 + 分块章节（语义保证/限制） | Task 6 |
| 2015-2026 扩样重跑 + 档案更新 | Task 7 |
| 已知限制文档化（forward 边界 null、fillna forward） | Task 6 |

**2. 占位符扫描：** 无 TBD/TODO；所有代码步骤含完整代码。Task 4 Step 1 的测试标注
"参照该文件既有模式"并给骨架——实施者需按 `test_cli_run.py` 既有风格补全（该文件已有
CLI 建库模式，与 test_run_factor.py 的 build_db 同构）。

**3. 类型/命名一致性：** `chunk_calendar` 返回 `(load_start, chunk_start, chunk_end)`
三元组在 Task 1 定义、Task 3 解包使用一致；`_compute_panel` 的 `base_adj` 参数在
3b 定义、3c 单块传缺省/分块传 `_load_base_adj` 结果一致；`RunContext.warmup_days`
在 Task 3 定义、Task 3c 使用一致；`_WARMUP_SAFETY_PAD = 20` 在 3b 定义、3c 引用一致。
