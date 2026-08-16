# FactorLab M4a 引擎接入与评估实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 因子从平台库端到端跑通到评估：数据层全面切换（quant-data 彻底移除）、复权口径消费、quant_core 评估桥接、`factorlab run` 命令。

**Architecture:** `data/`（source/universe/calendar 改读平台库，列映射+复权 join）→ `engine/`（run_factor 装配：复权视图 → 因子 → process → total_return 前向收益）→ `eval/`（自包含：周频对齐 + quant_core 桥接）→ CLI run。

**Tech Stack:** Python 3.13、Polars、DuckDB、quant_core（PyO3）。

**Spec:** `docs/superpowers/specs/2026-08-16-factorlab-m4a-engine-eval-design.md`

## Global Constraints

- Python 3.13；包结构 `src/factorlab`；测试 `pythonpath = ["src"]`。
- **平台库 `data/factorlab.duckdb` 是唯一数据源**；quant-data 路径从代码彻底移除（项目自包含）。
- 每个功能 TDD（正常/边界/错误），全量通过后提交（CLAUDE.md 硬性要求）。
- 集成测试 `@pytest.mark.integration`（真实平台库/真实 quant_core）。
- 新代码同步更新 `docs/interface.md`（Task 8 汇总）。
- 平台库 schema 事实（实测，M3b 建表）：
  - `daily`: ts_code/trade_date/open/high/low/close/pre_close/change/pct_chg/vol/amount
  - `daily_basic`: ts_code/trade_date/.../turnover_rate/total_mv/circ_mv/...
  - `stock_basic`: ts_code/symbol/name/area/industry/market/list_date/...（**无 exchange 列**）
  - `stock_st`: ts_code/name/trade_date/type/type_name（type='ST'；**无 is_st 列**）
  - `trade_cal`: exchange/cal_date/is_open(BIGINT)/pretrade_date
  - `adj_factor`: ts_code/trade_date/adj_factor

## File Structure

- `src/factorlab/config.py`（Modify）：移除 `quant_db`；新增 `platform_db` 默认路径。
- `src/factorlab/data/source.py`（Modify）：load_daily 读平台库（列映射/复权 join/daily_basic 可选 join）。
- `src/factorlab/data/universe.py`（Modify）：平台库表适配（stock_st type 语义、ts_code 后缀 exchange）。
- `src/factorlab/data/calendar.py`（Modify）：trading_calendar 读平台库 trade_cal。
- `src/factorlab/engine/forward.py`（Modify）：compute_forward_returns 升级 total_return 口径。
- `src/factorlab/engine/compute.py`（Modify）：run_factor 装配升级（复权/宏/默认库）+ 移除 align_weekly 调用。
- `src/factorlab/ops/platform_ops.py`（Modify）：宏展开器扩展用户宏。
- `src/factorlab/eval/__init__.py`、`alignment.py`、`rust_ic.py`、`metrics.py`（Create）。
- `src/factorlab/cli/main.py`（Modify）：run 命令。
- 测试：现有 fixture 全面更新为平台库风格 + 新增 test_eval/test_run 等。

---

### Task 1: source.py 平台库加载

**Files:**
- Modify: `src/factorlab/data/source.py`
- Test: `tests/test_source.py`（fixture 全面更新）

**Interfaces:** `load_daily(db_path, codes, date_start=None, date_end=None, cols=None, float32=True) -> pl.LazyFrame`
（读平台库 daily；`trade_date→date`、`ts_code→code`（去后缀）、`vol→volume` 映射；join adj_factor；cols 含 turnover/total_mv 时 join daily_basic）。

- [ ] **Step 1: 更新测试 fixture（平台库风格）**

`tests/test_source.py` 的 `build_db` 改为建平台库风格表：

```python
def build_db(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE)")
    db.execute("""INSERT INTO daily VALUES
        ('000001.SZ', '20240102', 10.0, 11.0, 9.5, 10.5, 10.2, 0.3, 0.0294, 100000.0, 1e6),
        ('000001.SZ', '20240103', 10.5, 11.5, 10.0, 11.0, 10.5, 0.5, 0.0476, 110000.0, 1.1e6),
        ('600519.SH', '20240102', 20.0, 21.0, 19.0, 20.5, 19.8, 0.7, 0.0354, 200000.0, 2e6)""")
    db.execute("CREATE TABLE adj_factor (ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
    db.execute("""INSERT INTO adj_factor VALUES
        ('000001.SZ', '20240102', 1.0), ('000001.SZ', '20240103', 1.0),
        ('600519.SH', '20240102', 1.2)""")
    db.execute("CREATE TABLE daily_basic (ts_code VARCHAR, trade_date VARCHAR, turnover_rate DOUBLE, total_mv DOUBLE)")
    db.execute("""INSERT INTO daily_basic VALUES
        ('000001.SZ', '20240102', 1.5, 1e6), ('000001.SZ', '20240103', 1.8, 1.1e6),
        ('600519.SH', '20240102', 0.5, 5e6)""")
    db.close()
```

更新既有测试（列名/代码格式/date 类型断言），新增：

```python
def test_load_daily_maps_platform_columns(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["close", "adj_factor"]).collect()
    assert df.columns == ["date", "code", "close", "adj_factor"]
    assert df["code"].to_list() == ["000001", "000001"]  # ts_code 去后缀
    assert df["date"].dtype == pl.Date


def test_load_daily_maps_volume_column(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["volume"]).collect()
    assert "volume" in df.columns  # vol → volume


def test_load_daily_joins_daily_basic_when_requested(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["close", "turnover"]).collect()
    assert "turnover" in df.columns
    assert df["turnover"].to_list() == [1.5, 1.8]  # turnover_rate join
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_source.py -v`
Expected: FAIL — load_daily 仍读 quant-data 风格（date/code 列、无 adj_factor）。

- [ ] **Step 3: 实现平台库加载**

Rewrite `src/factorlab/data/source.py`：

```python
from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from factorlab.config import settings

# 平台库 daily 列映射：tushare 列名 → 平台引擎列名
_COL_MAP = {"vol": "volume"}
_PLATFORM_COLS = ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
# cols 请求的平台语义列 → daily_basic 来源
_DAILY_BASIC_MAP = {"turnover": "turnover_rate", "total_mv": "total_mv", "circ_mv": "circ_mv"}


def load_daily(
    db_path: Path,
    codes: list[str],
    date_start: str | None = None,
    date_end: str | None = None,
    cols: list[str] | None = None,
    float32: bool = settings.use_float32,
) -> pl.LazyFrame:
    """平台库加载 daily：列映射（trade_date→date、ts_code→code、vol→volume）、
    adj_factor join；cols 含 turnover/total_mv 时 join daily_basic。"""
    if not codes:
        raise ValueError("universe 为空，无法加载数据")
    codes_sql = ", ".join(f"'{c}'" for c in codes)
    date_sql = " AND ".join(
        f"trade_date {'>=' if date_start else '<='} '{date_start or date_end}'"
        for _ in [0] if date_start or date_end
    )

    daily_cols = [c for c in (cols or list(_PLATFORM_COLS)) if c not in _DAILY_BASIC_MAP]
    basic_cols = [c for c in (cols or []) if c in _DAILY_BASIC_MAP]

    select_cols = ["trade_date", "ts_code", *daily_cols, "adj_factor"]
    join_daily_basic = bool(basic_cols) or "close" in daily_cols  # close 恒在（forward 需要）
    # ——简化：close 恒选（forward/评估依赖）；daily_basic 按需 join
    select_cols = list(dict.fromkeys(select_cols))

    with duckdb.connect(str(db_path), read_only=True) as con:
        con.execute(f"SET memory_limit='{settings.default_max_memory}'")
        sql = f"""
            SELECT d.trade_date, d.ts_code, {', '.join(f'd.{c}' for c in daily_cols)}, a.adj_factor
            FROM daily d JOIN adj_factor a ON d.trade_date = a.trade_date AND d.ts_code = a.ts_code
            WHERE d.ts_code IN ({codes_sql}){f" AND {date_sql}" if date_sql else ""}
            ORDER BY d.ts_code, d.trade_date
        """
        df = con.execute(sql).pl()
        if join_daily_basic and basic_cols:
            basic_sql = f"SELECT trade_date, ts_code, {', '.join(_DAILY_BASIC_MAP[c] for c in basic_cols)} FROM daily_basic"
            basic = con.execute(basic_sql).pl()
            df = df.join(basic, on=["trade_date", "ts_code"], how="left")

    df = df.with_columns(
        pl.col("trade_date").str.strptime(pl.Date, "%Y%m%d").alias("date"),
        pl.col("ts_code").str.split(".").list.first().alias("code"),
    ).drop(["trade_date", "ts_code"])
    df = df.rename({k: v for k, v in _COL_MAP.items() if k in df.columns})
    for platform_name, basic_name in _DAILY_BASIC_MAP.items():
        if basic_name in df.columns:
            df = df.rename({basic_name: platform_name})
    if float32:
        num_cols = [c for c in df.columns if c not in {"date", "code"}]
        df = df.with_columns([pl.col(c).cast(pl.Float32) for c in num_cols])
    return df.lazy()
```

（实现时以测试为准调整：codes 参数化、join 键、日期过滤；**保持 SQL-first + 参数化**——codes_sql 用字符串拼接有注入风险，改用 `unnest(?)` 参数化，与 M3a 一致。）

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_source.py -v`
Expected: PASS（含更新后的既有测试——float32/列裁剪/空 codes 报错保持）。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/data/source.py tests/test_source.py
git commit -m "feat: load daily from platform db with column mapping and adjustment join"
```

---

### Task 2: universe/calendar 平台库适配

**Files:**
- Modify: `src/factorlab/data/universe.py`
- Modify: `src/factorlab/data/calendar.py`
- Test: `tests/test_universe.py`、`tests/test_calendar.py`（fixture 更新）

**平台库事实**：stock_basic 无 exchange 列（用 ts_code 后缀推断：SH→SSE/SZ→SZSE/BJ→BSE）；
stock_st 无 is_st（`type='ST'` 即 ST）；trade_cal is_open BIGINT。

- [ ] **Step 1: 更新测试 fixture 并新增**

`tests/test_universe.py` 的 `build_db` 改为平台库风格（stock_basic 含 ts_code/symbol/market/list_date/industry；
stock_st 含 ts_code/trade_date/type；无 st_status 表）。新增：

```python
def test_resolve_codes_exclude_st_platform_db(tmp_path):
    db = build_db(tmp_path)
    spec = spec_with(rules={"exclude_st": True})
    assert resolve_codes(spec, db) == ["600519"]  # 000001 在 stock_st 最新快照


def test_resolve_codes_exchanges_by_suffix(tmp_path):
    db = build_db(tmp_path)
    spec = spec_with(rules={"exchanges": ["SSE"]})
    assert resolve_codes(spec, db) == ["600519"]  # ts_code 后缀 .SH → SSE


def test_resolve_codes_rejects_bse(tmp_path):
    db = build_db(tmp_path)  # 含 830001.BJ
    with pytest.raises(ValueError, match="BSE"):
        resolve_codes(spec_with(rules={"exchanges": ["BSE"]}), db)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_universe.py -v`
Expected: FAIL — 现有实现读 st_status/exchange 列。

- [ ] **Step 3: 实现平台库适配**

`src/factorlab/data/universe.py` 修改：

```python
_EXCHANGE_BY_SUFFIX = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}


def _codes_from_rules(rules, db, date_start):
    sql = "SELECT symbol FROM stock_basic WHERE 1=1"
    params: list = []
    if rules.get("exclude_st"):
        sql += """ AND symbol NOT IN (
            SELECT substr(ts_code, 1, 6) FROM stock_st
            WHERE trade_date = (SELECT max(trade_date) FROM stock_st)
        )"""
    exchanges = rules.get("exchanges")
    if exchanges:
        bad = [e for e in exchanges if e not in VALID_EXCHANGES]
        if bad:
            raise ValueError(f"不支持的交易所: {bad}（v1 支持 {VALID_EXCHANGES}，不含 BSE）")
        suffixes = [s for e in exchanges for s, ex in _EXCHANGE_BY_SUFFIX.items() if ex == e]
        sql += f" AND substr(ts_code, -2) IN ({', '.join('?' for _ in suffixes)})"
        params.extend(suffixes)
    min_days = rules.get("min_list_days")
    if min_days is not None:
        min_days = int(min_days)
        if min_days < 0:
            raise ValueError(f"min_list_days 不能为负: {min_days}")
        if date_start is None:
            date_start = db.execute("SELECT min(trade_date) FROM daily").fetchone()[0]
        sql += " AND strptime(list_date, '%Y%m%d') <= CAST(? AS DATE) - INTERVAL (?) DAY"
        params.extend([date_start, min_days])
    rows = db.execute(sql, params).fetchall()
    return sorted(r[0] for r in rows)
```

`src/factorlab/data/calendar.py` 修改（`trading_calendar` 读平台库 trade_cal，is_open 过滤）：

```python
def trading_calendar(db_path: Path, date_start: str | None = None, date_end: str | None = None) -> pl.Series:
    """交易日历：平台库 trade_cal 的 is_open=1 日期（YYYYMMDD → pl.Date）。"""
    with duckdb.connect(str(db_path), read_only=True) as con:
        where, params = [], []
        if date_start is not None:
            where.append("cal_date >= ?")
            params.append(date_start.replace("-", ""))
        if date_end is not None:
            where.append("cal_date <= ?")
            params.append(date_end.replace("-", ""))
        sql = "SELECT cal_date FROM trade_cal WHERE is_open = 1" + (f" AND {' AND '.join(where)}" if where else "")
        dates = [r[0] for r in con.execute(sql, params).fetchall()]
    return pl.Series("date", [datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])) for d in sorted(dates)], dtype=pl.Date)
```

（注意：M4a 后 run_factor 的日期范围参数是 `YYYY-MM-DD`（spec.date.start）——calendar 内转 `YYYYMMDD` 查询；fill_suspensions 不变。）

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_universe.py tests/test_calendar.py -v`
Expected: PASS（fixture 更新后；min_list_days 测试的假表 list_date 同步 'YYYYMMDD' 格式）。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/data/universe.py src/factorlab/data/calendar.py tests/test_universe.py tests/test_calendar.py
git commit -m "feat: adapt universe and calendar to platform db schema"
```

---

### Task 3: run_factor 装配升级（复权消费 + total_return 前向收益 + 默认平台库）

**Files:**
- Modify: `src/factorlab/engine/forward.py`
- Modify: `src/factorlab/engine/compute.py`
- Modify: `src/factorlab/config.py`（移除 quant_db、新增 platform_db）
- Test: `tests/test_forward.py`、`tests/test_run_factor.py`、`tests/test_compute.py`（fixture 更新）

**语义**：因子值用复权视图（spec.adjustment 默认 qfq）；前向收益 total_return 口径
（close×adj 序列）；run_factor 默认 db_path = 平台库。

- [x] **Step 1: 更新测试 fixture 并新增**

`tests/test_run_factor.py` 的 `build_db` 改为平台库风格（daily/adj_factor/daily_basic/stock_basic/stock_st/trade_cal）。新增：

```python
def test_run_factor_qfq_adjustment(tmp_path):
    # 除权日（adj 1.0→1.5, close 11→8）：qfq 下因子值连续（用 momentum 类公式验证）
    build_db(tmp_path)  # 构造含除权日的数据
    spec = ...  # adjustment: qfq（默认），公式 signal = close / ts_delay(close, 1) - 1
    result = run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out"))
    # 除权日 qfq 收益 ≈ (8×1.5/11 - 1) 而非 raw 的 (8/11-1)
    ...


def test_run_factor_default_db_is_platform(tmp_path):
    # RunContext 默认 db_path 指向平台库路径（非 quant-data）
    ctx = RunContext()
    assert ctx.db_path == Path("data/factorlab.duckdb")
```

`tests/test_forward.py` 更新：compute_forward_returns 输入含 adj_factor 列（total_return 口径）：

```python
def test_forward_returns_total_return_semantics():
    # close×adj 序列的 h 期收益（含分红再投资）
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3), datetime.date(2024, 1, 4), datetime.date(2024, 1, 5), datetime.date(2024, 1, 8)],
        "code": ["A"] * 5,
        "close": [10.0, 11.0, 8.0, 9.0, 12.0],
        "adj_factor": [1.0, 1.0, 1.5, 1.5, 1.5],
    })
    out = compute_forward_returns(df, horizons=(4,))
    # close[1/8]×adj[1/8] / (close[1/2]×adj[1/2]) - 1 = 12×1.5/10 - 1 = 0.8
    assert out["forward_return_4d"][0] == 0.8
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_forward.py tests/test_run_factor.py -v`
Expected: FAIL — forward 仍 raw close；RunContext 默认 quant_db。

- [x] **Step 3: 实现**

`src/factorlab/config.py`：

```python
    # quant_db 已废弃（quant-data 彻底移除）；平台库为唯一数据源
    platform_db: Path = Path("data/factorlab.duckdb")
```
（删除 `quant_db` 字段；M3b 的 data_dir 保留。）

`src/factorlab/engine/forward.py` 的 `compute_forward_returns` 升级（total_return 口径）：

```python
def compute_forward_returns(
    df: pl.DataFrame,
    horizons: tuple[int, ...] = (5, 20),
    close_col: str = "close",
    adj_col: str = "adj_factor",
) -> pl.DataFrame:
    """前向收益（total_return 口径）：close[t+h]×adj[t+h] / (close[t]×adj[t]) - 1，
    含分红再投资（M3b 复权架构统一收益语义）。"""
    result = df.sort(["code", "date"])
    hfq = pl.col(close_col) * pl.col(adj_col)
    for h in horizons:
        expr = (hfq.shift(-h).over("code", order_by="date") / hfq - 1).alias(f"forward_return_{h}d")
        result = result.with_columns(expr)
    return result
```

`src/factorlab/engine/compute.py` 的 `run_factor` 升级：

```python
@dataclass
class RunContext:
    db_path: Path = _settings.platform_db       # 默认平台库（quant-data 已移除）
    output_dir: Path = Path("results")
    universe_override: str | None = None
    float32: bool = _settings.use_float32
    adjustment: str = "qfq"                      # 复权口径（spec 未声明时默认）

def run_factor(spec: FactorSpec, ctx: RunContext) -> FactorResult:
    con = duckdb.connect(str(ctx.db_path), read_only=True)
    try:
        codes = resolve_codes(spec, con, override=ctx.universe_override)
        cols = _formula_columns(spec.formula) if spec.formula else None
        cols = (cols or []) + ["close"]          # close 恒加载（forward 依赖）
        raw = load_daily(ctx.db_path, codes, date_start=spec.date.start, date_end=spec.date.end,
                         cols=cols, float32=ctx.float32).collect()
        cal = trading_calendar(ctx.db_path, date_start=spec.date.start, date_end=spec.date.end)
        panel = fill_suspensions(raw, cal)
        adjustment = getattr(spec, "adjustment", None) or ctx.adjustment
        panel = view_prices(panel, adjustment)   # 复权视图（因子计算口径）
        panel = compute_formula(panel, spec.formula) if spec.formula else panel
        panel = run_process_chain(panel, spec.process, ctx=con)
        panel = compute_forward_returns(panel)
        if panel.height == 0:
            raise ValueError("日期段无数据，可运行 data refresh")
    finally:
        con.close()
    ...（summary 增加 adjustment 字段；落盘不变）
```

**注意**：`view_prices` 缩放 open/high/low/close——fill_suspensions 补全后 adj_factor 为 null 的行
（停牌日）复权后价格 null——因子计算自然处理。`compute_formula` 的列引用（close 等）在 view_prices
后为复权值 ✓。forward 需要 adj_factor 列（补全面板含 adj ✓）。

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_forward.py tests/test_run_factor.py tests/test_compute.py -v`
Expected: PASS（fixture 更新后）。

- [x] **Step 5: Commit**

```bash
git add src/factorlab/config.py src/factorlab/engine/forward.py src/factorlab/engine/compute.py tests/test_forward.py tests/test_run_factor.py
git commit -m "feat: adjust factor view and total-return forward in run_factor"
```

**Task 3 实现注记（含审查前置项）：**

1. **forward 先于 view_prices**（计划 Step 3 代码的调用顺序偏差——修正为数学正确）：
   total_return = raw close×adj；view_prices(qfq/hfq) 已缩放 close 后再乘 adj 会二次复权
   （比值出现 adj²）。前向收益列在 raw 面板上计算，view_prices 只缩放 OHLC，forward 列不受影响；
   HFQ/QFQ 收益一致（spec §2.3 等比缩放不变量）。`test_run_factor_qfq_adjustment` 断言
   forward_return_5d = 13×1.5/10 - 1 作为二次复权回归。
2. **adj_factor 显式请求**：`cols = formula_cols + ["close", "adj_factor"]`（T1 审查）。
3. **qfq/pit_qfq null-adj 修复**（T1 审查 Important）：`view_prices` 的 latest/asof 基准
   `filter(is_not_null).last()`——fill_suspensions 补全的停牌行 adj 为 null，窗口末行 null
   曾导致整组 None。补测试 test_view_qfq_skips_null_adj_suspension_rows /
   test_view_pit_qfq_skips_null_adj_asof_row。
4. **未来公告日不补全**（T2 审查）：在 run_factor 装配层 `cal.filter(cal <= today)`，
   trading_calendar 保持纯查询（date_end=None 返回全部开市日，含未来公告日到 20261231）。
5. **processors 表名**：fillna/neutralize 的 `stock_basic_tushare` → `stock_basic`（平台库
   M3b 表名）；test_process.py fixture 同步；neutralize size 的 daily_basic 查询与
   'YYYYMMDD' 日期格式处理保持（已对）。
6. **close 必须引用校验**锚点改为公式列（close 恒加载后 panel 恒含 close）：`if "close"
   not in formula_cols: raise`（M3a 契约保留，消息不变）。
7. **RunContext.adjustment** 字段（默认 "qfq"）；`adjustment = getattr(spec, "adjustment",
   None) or ctx.adjustment`（spec.adjustment 字段 Task 4 加）；未知口径由 view_prices 报错
   （"未知价格视图 view"），补测试。summary 增加 adjustment 字段。
8. **align_weekly 移除**：run_factor 不再调用（T5 迁 eval，T7 接评估）；panel 为日频。
9. fixture 的 daily 用平台库 6 位代码（000001.SZ/600519.SH）——substr(ts_code,1,6) 前缀
   匹配在 run_factor 链路要求代码为 6 位（1 字符测试代码会空结果）。

---

### Task 4: operators 宏消费 + default_universe 接线

**Files:**
- Modify: `src/factorlab/ops/platform_ops.py`（宏展开器扩展）
- Modify: `src/factorlab/spec.py`（FactorSpec.adjustment 字段）
- Modify: `src/factorlab/engine/compute.py`（run_factor 接入宏展开）
- Modify: `src/factorlab/cli/main.py`（run 的 --universe 默认，Task 7 实现）
- Test: `tests/test_run_factor.py`、`tests/test_spec.py`、`tests/test_platform_ops.py`、`docs/interface.md`

- [x] **Step 1: 测试**

```python
def test_spec_adjustment_field():
    spec = load_spec(...)  # adjustment: raw
    assert spec.adjustment == "raw"


def test_run_factor_consumes_operators_macros(tmp_path):
    # spec.operators 内联宏：mom_ratio → 公式展开
    build_db(tmp_path)
    spec_path.write_text("""
name: macro_demo
category: custom
direction: 1
universe: {codes: ["000001.SZ"]}
operators:
  mom_ratio: {params: [x, n], formula: "delay(x, n) / delay(x, 2*n) - 1"}
formula: |
  from polars_ta.prefix.wq import ts_delay as delay
  signal = mom_ratio(close, 2)
""")
    result = run_factor(load_spec(spec_path), RunContext(db_path=..., output_dir=...))
    assert result.panel.height > 0
```

- [x] **Step 2: Run test to verify it fails**

Expected: FAIL — adjustment 字段不存在；operators 未消费。

- [x] **Step 3: 实现**

`src/factorlab/spec.py` FactorSpec 增加：

```python
    adjustment: Literal["raw", "qfq", "hfq", "pit_qfq"] = "qfq"
```

`src/factorlab/ops/platform_ops.py` 的宏展开器扩展（用户宏）：

```python
def expand_user_macros(source: str, operators: dict[str, OperatorMacro]) -> str:
    """spec.operators 内联宏：name(args) → formula 展开（params 按位置绑定）。"""
    if not operators:
        return source
    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name, macro in operators.items():
        if name in defined:
            continue  # 公式内 def 优先
        template = macro.formula
        params = macro.params or []
        def replacer(node):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
                if len(node.args) != len(params):
                    raise FactorDSLError(f"宏 {name} 需要 {len(params)} 个参数", node.lineno, node.col_offset)
                mapping = {p: ast.unparse(a) for p, a in zip(params, node.args)}
                expanded = template
                for p, v in mapping.items():
                    expanded = expanded.replace(p, f"({v})")
                return ast.parse(expanded).body[0].value
            return node
        tree = ast.NodeTransformer()...  # 简化：用替换展开
    ...
```

（实现修正：宏展开顺序为用户宏 → validate → 平台宏（用户宏公式可引用平台薄封装
`returns` 等，必须先于平台宏展开；原"平台宏之后、validate 之前"顺序会让宏公式内
的平台薄封装无法展开）。参数绑定用 AST Name 节点替换而非字符串 replace——短参数名
（如 `n`）会误替换 `ts_mean`/`ts_min` 等标识符子串。run_factor 接入：展开后公式用于
`validate_formula`、`_formula_columns`（宏公式内数据列引用纳入加载）与
`compute_formula`。）

`src/factorlab/cli/main.py`：run 命令的 `--universe` 默认 `settings.default_universe`（Task 7 一起实现）。

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_factor.py tests/test_spec.py -v`
Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add src/factorlab/spec.py src/factorlab/ops/platform_ops.py src/factorlab/engine/compute.py tests/test_run_factor.py tests/test_spec.py tests/test_platform_ops.py docs/interface.md docs/superpowers/plans/2026-08-16-factorlab-m4a-engine-eval.md
git commit -m "feat: consume adjustment field and inline operator macros"
```

---

### Task 5: eval/ 周频对齐与轻量指标

**Files:**
- Create: `src/factorlab/eval/__init__.py`、`src/factorlab/eval/alignment.py`、`src/factorlab/eval/metrics.py`
- Modify: `src/factorlab/engine/forward.py`（移除 align_weekly）
- Test: `tests/test_eval_alignment.py`（迁移 test_forward 的 align 测试）

- [ ] **Step 1: 迁移测试**

`tests/test_eval_alignment.py`：`align_weekly` 从 test_forward.py 原样迁移（4 个测试：
最后交易日/跨年 ISO 周/全年首 bar/排序）。`engine/forward.py` 移除 align_weekly。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval_alignment.py -v`
Expected: FAIL — eval.alignment 不存在。

- [ ] **Step 3: 实现**

`src/factorlab/eval/alignment.py`：`align_weekly` 原样迁移（ISO 周语义，含排序守卫）。

`src/factorlab/eval/metrics.py`：

```python
def coverage_report(panel: pl.DataFrame, signal_col: str = "signal") -> dict:
    """覆盖率：有效行比例、股票覆盖数、日期覆盖数。"""
    total = panel.height
    valid = panel[signal_col].drop_nulls().len()
    return {
        "pct_valid": round(valid / total, 4) if total else 0.0,
        "total_rows": total,
        "valid_rows": valid,
        "stocks": panel["code"].n_unique(),
        "weeks": panel["date"].n_unique(),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_eval_alignment.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/eval tests/test_eval_alignment.py src/factorlab/engine/forward.py
git commit -m "feat: add eval package with weekly alignment and coverage metrics"
```

---

### Task 6: eval/rust_ic.py quant_core 桥接

**Files:**
- Create: `src/factorlab/eval/rust_ic.py`
- Test: `tests/test_eval_rust_ic.py`

**Interfaces:** `evaluate_factor_weekly(panel, factor_name, direction, target="forward_return_5d") -> dict`
（输入日频面板，内部周频对齐 + quant_core 评估；factor_name 内部约定 `"_factor"`）。

- [ ] **Step 1: 测试**

```python
def test_evaluate_factor_weekly_returns_full_structure():
    # 真实 quant_core（已装）+ 构造周频面板（多周多股票，IC 可计算）
    panel = ...  # 12 周 × 10 只：signal 与 forward_return_5d 构造正相关
    result = evaluate_factor_weekly(panel, "demo", direction=1)
    assert result["factor"] == "_factor"
    assert result["target"] == "forward_return_5d"
    assert result["n_weeks"] >= 10
    assert set(result["ic"]) >= {"mean", "std", "t_stat", "ir"}
    assert "decile_returns" in result and "turnover" in result and "coverage" in result


def test_evaluate_factor_weekly_direction_flips_decile():
    panel = ...
    up = evaluate_factor_weekly(panel, "demo", direction=1)
    down = evaluate_factor_weekly(panel, "demo", direction=-1)
    assert up["decile_returns"]["spread"]["ret"] == -down["decile_returns"]["spread"]["ret"]


def test_evaluate_factor_weekly_aligns_weekly():
    # 日频输入 → 内部周频对齐（n_weeks ≈ 周数）
    panel = ...  # 60 个交易日 → 12 周
    result = evaluate_factor_weekly(panel, "demo", 1)
    assert result["n_weeks"] == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval_rust_ic.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: 实现**

```python
from __future__ import annotations

import polars as pl

from factorlab.eval.alignment import align_weekly


def evaluate_factor_weekly(
    panel: pl.DataFrame,
    factor_name: str,
    direction: int,
    target: str = "forward_return_5d",
) -> dict:
    """周频评估：日频面板 → 周频对齐 → quant_core.evaluate_factor。

    factor_name 参数必须传 "_factor"（quant_core 内部列名约定，文档未记载）。
    """
    import quant_core

    weekly = align_weekly(panel)
    required = {"date", "code", "signal", target}
    missing = required - set(weekly.columns)
    if missing:
        raise ValueError(f"评估面板缺少列: {sorted(missing)}")
    dates = weekly["date"].dt.strftime("%Y-%m-%d").to_list()
    codes = weekly["code"].to_list()
    signals = weekly["signal"].to_list()
    fwd = weekly[target].to_list()
    result = quant_core.evaluate_factor(dates, codes, signals, fwd, "_factor", int(direction))
    result["factor_name"] = factor_name
    return result
```

**注意**：quant_core 输入为列表（实测兼容 str/float 列表）；`date` 需 `%Y-%m-%d` 格式
（quant_core 内部解析）——转换在桥接层。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_eval_rust_ic.py -v`
Expected: PASS（真实 quant_core）。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/eval/rust_ic.py tests/test_eval_rust_ic.py
git commit -m "feat: bridge quant_core evaluation with weekly alignment"
```

---

### Task 7: `factorlab run` 命令与端到端

**Files:**
- Modify: `src/factorlab/cli/main.py`
- Test: `tests/test_cli_run.py`、`tests/test_e2e_m4.py`

- [ ] **Step 1: 测试**

```python
def test_run_help():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    for opt in ("--universe", "--max-memory"):
        assert opt in result.stdout


def test_run_end_to_end(tmp_path, monkeypatch):
    # 平台库风格 tmp 库 + spec → run 落盘
    ...
    result = runner.invoke(app, ["run", str(spec_path), "--universe", "600519"])
    assert result.exit_code == 0
    assert (tmp_path / "results" / "demo" / "summary.json").exists()
    summary = json.loads(...)
    assert "evaluation" in summary
```

集成测试（真实平台库 + quant_core，integration 标记）：

```python
@pytest.mark.integration
def test_e2e_real_factor_run():
    # 真实平台库 5 只股票 × 2 年：vol_skew 因子 → run → 评估合理
    spec_path.write_text("""...""")
    result = runner.invoke(app, ["run", str(spec_path)])
    assert result.exit_code == 0
    summary = json.loads(open(results_path).read())
    assert summary["evaluation"]["ic"]["n_weeks"] > 50
    assert summary["evaluation"]["coverage"]["pct_valid"] > 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — run 命令不存在。

- [ ] **Step 3: 实现**

`src/factorlab/cli/main.py`：

```python
@data_app  # 不放 data 下——run 是顶层命令
@app.command("run")
def run_factor_cli(spec_path: Path, universe: str | None = None,
                   max_memory: str = "4GB", float32: bool = True) -> None:
    """计算因子并评估（平台库）。"""
    from factorlab.engine.compute import RunContext, run_factor as run_impl
    from factorlab.eval.rust_ic import evaluate_factor_weekly
    import json

    spec = load_spec(spec_path)
    ctx = RunContext(
        db_path=settings.platform_db,
        output_dir=settings.data_dir.parent / "results" / spec.name,
        universe_override=universe or settings.default_universe,
        float32=float32,
    )
    result = run_impl(spec, ctx)
    evaluation = evaluate_factor_weekly(result.panel, spec.name, spec.direction)
    result.summary["evaluation"] = evaluation
    result.panel.write_parquet(ctx.output_dir / "weekly.parquet")  # 评估输入
    (ctx.output_dir / "summary.json").write_text(
        json.dumps(result.summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"{spec.name}: n_weeks={evaluation.get('n_weeks')} "
                  f"ic_mean={evaluation.get('ic', {}).get('mean')}")
```

（注意 `run_factor` 落盘逻辑（M3a 的 panel.parquet/summary.json）保留；CLI 追加 weekly.parquet
与 evaluation 字段。落盘路径 `results/<name>/`。）

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_run.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/cli/main.py tests/test_cli_run.py tests/test_e2e_m4.py
git commit -m "feat: add factorlab run command with evaluation"
```

---

### Task 8: quant-data 清理与文档汇总

**Files:**
- Modify: `src/factorlab/config.py`（确认 quant_db 已移除）
- Modify: `docs/interface.md`、`docs/data-ops-playbook.md`、`CLAUDE.md`
- Test: 全量验证

- [ ] **Step 1: 清理残留**

grep 全库确认无 `quant-data` / `quant_db` 引用（代码）：

```bash
grep -rn "quant-data\|quant_db" src/ tests/ docs/interface.md 2>/dev/null | grep -v "playbook" | grep -v "m3b" || echo "无残留"
```

`CLAUDE.md` 环境事实更新：quant-data 描述移除，改为平台库。

- [ ] **Step 2: 文档汇总**

`docs/interface.md`：M4a 新 API（load_daily 平台库语义、view_prices 装配、evaluate_factor_weekly、
run 命令、eval 包）；`docs/data-ops-playbook.md` 更新链路（run 加入运维闭环）。

- [ ] **Step 3: 全量验证 + 集成**

Run: `python -m pytest -q`（含 integration——真实平台库 run e2e）
Expected: 全部 PASS。

- [ ] **Step 4: 验收报告**

真实因子 run（平台库 5 只 × 2 年）→ 输出评估摘要（IC/十分位/换手/覆盖）→
与 quant-data 对比摘要（可选）→ **提交验收报告给用户，确认后清理 quant-data**。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: document M4a engine and evaluation; clean up legacy references"
```

---

## Self-Review

**1. Spec coverage（对照 M4a spec）：**
- §2.2 source 平台库加载 → Task 1 ✓；§2.3 复权消费/前向收益 → Task 3 ✓；
- §2.4 universe/calendar 适配 → Task 2 ✓；§2.5 operators 宏/default_universe → Task 4 ✓；
- §3 eval 结构/alignment/桥接/metrics → Task 5/6 ✓；§4 run 命令 → Task 7 ✓；
- §5 清理流程 → Task 8 ✓；§6 测试策略 → 各任务 + Task 7 集成 ✓；
- §7 明确不做 → 计划不含 ✓
- **缺口**：spec §2.2 的 `include_adj` 参数——实现为恒 join adj_factor（close 恒加载）——
  Task 1 实现注记已说明；`pit_qfq` spec 级不支持（M4a 范围）——Task 3 的 adjustment
  校验：pit_qfq 声明时报错或按 qfq 处理？**明确**：spec.adjustment=pit_qfq 时报错
  （"M4a 支持 raw|qfq|hfq"），记录在 Task 3 实现。

**2. Placeholder scan：** 无 TBD/TODO；Task 4 的宏展开器给了结构说明（实现时按现有
expand_platform_macros 模式完成）；Task 7 的集成测试给了骨架（实现时补全）——均有明确方向。

**3. Type consistency：** `load_daily(db_path, codes, date_start, date_end, cols, float32)`、
`view_prices(panel, view)`、`compute_forward_returns(df, horizons, close_col, adj_col)`、
`evaluate_factor_weekly(panel, factor_name, direction, target)`、`RunContext(db_path=platform_db)` 任务间一致 ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-16-factorlab-m4a-engine-eval.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks.
2. Inline Execution - execute tasks in this session using executing-plans with checkpoints.

Which approach?
