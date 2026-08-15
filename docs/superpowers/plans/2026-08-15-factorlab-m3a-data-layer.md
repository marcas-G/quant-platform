# FactorLab M3a 数据层（本地核心）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 DuckDB 只读数据加载、universe 三层解析、停牌补全、process 处理管线、前向收益与周频对齐，并用 `run_factor` 装配出真实数据小样本端到端链路。

**Architecture:** 函数式薄层（延续 M1/M2 风格）：`data/` 管取数与 universe、`process/` 管截面处理器（Polars 表达式 `.over("date")`）、`engine/forward.py` 管前向收益与周频对齐、`engine/compute.py` 新增 `run_factor` 装配。

**Tech Stack:** Python 3.13、Polars、DuckDB（只读）、PyYAML、pytest。

**Spec:** `docs/superpowers/specs/2026-08-15-factorlab-m3a-data-layer-design.md`

## Global Constraints

- Python 3.13，包结构 `src/factorlab`；测试 `pythonpath = ["src"]`。
- 不修改 `C:\Users\ThinkPad\quant-data` 任何文件；DuckDB 一律只读打开。
- 目标机器 16GB 内存无页面文件：SQL-first、float32、`memory_limit` 为硬约束。
- 每个功能先写失败测试（覆盖正常/边界/错误三类），转绿后才提交（CLAUDE.md 硬性要求）。
- `daily.code` 为纯数字（`000001`）；`stock_basic_tushare.symbol` 是 ts_code↔daily.code 桥梁。
- `daily.date` 为 VARCHAR `YYYY-MM-DD`；加载时 cast `pl.Date`（周频对齐需要）。
- 集成测试用 `@pytest.mark.integration`；`C:/Users/ThinkPad/quant-data/quant.duckdb` 不存在时 skip。
- 新代码同步更新 `docs/interface.md`（CLAUDE.md 硬性要求）。

## File Structure

- `src/factorlab/config.py`（Modify）：`universes_dir`、`default_universe`。
- `src/factorlab/spec.py`（Modify）：`UniverseSpec` 支持 `ref` 命名引用，三选一互斥。
- `src/factorlab/data/__init__.py`、`universe.py`、`source.py`、`calendar.py`（Create）。
- `src/factorlab/process/__init__.py`、`registry.py`、`processors.py`（Create）。
- `src/factorlab/engine/forward.py`（Create）；`src/factorlab/engine/compute.py`（Modify，加 `run_factor`）。
- `tests/conftest.py`（Create：integration marker + tmp DuckDB 构建 fixture）。
- `tests/test_spec.py`（Modify）、`tests/test_universe.py`、`tests/test_source.py`、`tests/test_calendar.py`、
  `tests/test_process.py`、`tests/test_forward.py`、`tests/test_run_factor.py`、`tests/test_e2e.py`（Create/Modify）。
- `docs/interface.md`（Modify，Task 10）。

---

### Task 1: UniverseSpec 命名引用

**Files:**
- Modify: `src/factorlab/spec.py:16-24`
- Test: `tests/test_spec.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spec.py`:

```python
def test_universe_accepts_string_reference(tmp_path):
    path = make_spec(tmp_path, universe="research_50")
    spec = load_spec(path)
    assert spec.universe.ref == "research_50"
    assert spec.universe.codes is None


def test_universe_rejects_multiple_sources(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(tmp_path, universe={"ref": "a", "codes": ["000001.SZ"]}))


def test_universe_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(tmp_path, universe={}))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_spec.py -v`
Expected: FAIL — `UniverseSpec` 无 `ref` 字段 / 未拒绝多源。

- [ ] **Step 3: Write minimal implementation**

Replace `UniverseSpec` in `src/factorlab/spec.py`:

```python
class UniverseSpec(BaseModel):
    ref: str | None = None          # 命名引用或文件路径（查 universes_dir）
    codes: list[str] | None = None
    rules: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"ref": value}
        return value

    @model_validator(mode="after")
    def _exactly_one_universe(self) -> "UniverseSpec":
        chosen = sum(x is not None for x in (self.ref, self.codes, self.rules))
        if chosen != 1:
            raise ValueError("universe 必须且只能提供 ref / codes / rules 之一")
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_spec.py -v`
Expected: PASS（含原有 4 个用例）。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/spec.py tests/test_spec.py
git commit -m "feat: support named universe reference in spec"
```

---

### Task 2: config 扩展 + universe 解析

**Files:**
- Modify: `src/factorlab/config.py`
- Create: `src/factorlab/data/__init__.py`
- Create: `src/factorlab/data/universe.py`
- Test: `tests/test_universe.py`

**Interfaces:** `normalize_code(code) -> str`；`load_universe_file(path) -> dict`；
`resolve_codes(spec, db, override=None, settings=None) -> list[str]`（返回纯数字代码列表）。

- [ ] **Step 1: Write the failing test**

Create `tests/test_universe.py`:

```python
import duckdb
import pytest

from factorlab.data.universe import normalize_code, resolve_codes
from factorlab.spec import FactorSpec


def build_db(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE stock_basic_tushare (symbol VARCHAR, ts_code VARCHAR, exchange VARCHAR, list_date VARCHAR, industry VARCHAR)")
    db.execute("""INSERT INTO stock_basic_tushare VALUES
        ('000001', '000001.SZ', 'SZSE', '1991-04-03', '银行'),
        ('600519', '600519.SH', 'SSE', '2001-08-27', '白酒'),
        ('830001', '830001.BJ', 'BSE', '2020-01-01', '其他')""")
    db.execute("CREATE TABLE st_status (code VARCHAR, date DATE, is_st BOOLEAN)")
    db.execute("""INSERT INTO st_status VALUES
        ('000001', DATE '2026-01-05', FALSE),
        ('000001', DATE '2026-03-10', TRUE),
        ('600519', DATE '2026-03-10', FALSE)""")
    db.execute("CREATE TABLE daily (date VARCHAR, code VARCHAR, close DOUBLE)")
    return db


def spec_with(**universe_kwargs):
    return FactorSpec.model_validate({
        "name": "demo", "category": "custom", "direction": 1,
        "universe": universe_kwargs, "formula": "signal = close",
    })


def test_normalize_code():
    assert normalize_code("000001.SZ") == "000001"
    assert normalize_code("600519") == "600519"
    with pytest.raises(ValueError):
        normalize_code("abc")


def test_resolve_codes_inline(tmp_path):
    db = build_db(tmp_path)
    spec = spec_with(codes=["000001.SZ", "600519"])
    assert resolve_codes(spec, db) == ["000001", "600519"]


def test_resolve_codes_rules_exclude_st(tmp_path):
    db = build_db(tmp_path)
    spec = spec_with(rules={"exclude_st": True})
    assert resolve_codes(spec, db) == ["600519"]  # 000001 最新 st 标记为 TRUE


def test_resolve_codes_rules_exchanges_rejects_bse(tmp_path):
    db = build_db(tmp_path)
    with pytest.raises(ValueError, match="BSE"):
        resolve_codes(spec_with(rules={"exchanges": ["BSE"]}), db)


def test_resolve_codes_reference_file(tmp_path, monkeypatch):
    db = build_db(tmp_path)
    uni_dir = tmp_path / "universes"
    uni_dir.mkdir()
    (uni_dir / "research_50.yaml").write_text("codes: ['000001.SZ']", encoding="utf-8")
    from factorlab.config import Settings
    settings = Settings(universes_dir=uni_dir)
    spec = spec_with(ref="research_50")
    assert resolve_codes(spec, db, settings=settings) == ["000001"]


def test_resolve_codes_override_beats_spec(tmp_path):
    db = build_db(tmp_path)
    spec = spec_with(codes=["000001.SZ"])
    assert resolve_codes(spec, db, override="600519") == ["600519"]


def test_resolve_codes_missing_reference_file(tmp_path):
    db = build_db(tmp_path)
    from factorlab.config import Settings
    settings = Settings(universes_dir=tmp_path / "nope")
    with pytest.raises(FileNotFoundError):
        resolve_codes(spec_with(ref="ghost"), db, settings=settings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_universe.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Add to `src/factorlab/config.py`:

```python
    universes_dir: Path = Path.home() / ".factorlab" / "universes"
    default_universe: str | None = None
```

Create `src/factorlab/data/__init__.py`（空文件）。

Create `src/factorlab/data/universe.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import yaml

from factorlab.config import settings
from factorlab.spec import FactorSpec

VALID_EXCHANGES = ("SSE", "SZSE")


def normalize_code(code: str) -> str:
    """'000001.SZ' -> '000001'；纯数字直通；非法格式报错。"""
    base = code.split(".")[0].strip()
    if not base.isdigit() or len(base) != 6:
        raise ValueError(f"非法股票代码: {code}（期望 6 位数字或 ts_code 格式）")
    return base


def load_universe_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"universe 文件不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"universe 文件必须是映射: {path}")
    return data


def _resolve_source(name: str, universes_dir: Path) -> dict[str, Any]:
    path = Path(name)
    if path.is_file():
        return load_universe_file(path)
    candidate = universes_dir / f"{name}.yaml"
    return load_universe_file(candidate)


def _codes_from_rules(rules: dict[str, Any], db: duckdb.DuckDBPyConnection, date_start: str | None) -> list[str]:
    sql = "SELECT symbol FROM stock_basic_tushare WHERE 1=1"
    params: list[Any] = []
    if rules.get("exclude_st"):
        sql += " AND symbol NOT IN (SELECT code FROM st_status WHERE is_st AND date = (SELECT max(date) FROM st_status))"
    exchanges = rules.get("exchanges")
    if exchanges:
        bad = [e for e in exchanges if e not in VALID_EXCHANGES]
        if bad:
            raise ValueError(f"不支持的交易所: {bad}（v1 支持 {VALID_EXCHANGES}，含 BSE）")
        sql += " AND exchange IN (SELECT unnest(?))"
        params.append(list(exchanges))
    min_days = rules.get("min_list_days")
    if min_days:
        if date_start is None:
            date_start = db.execute("SELECT min(date) FROM daily").fetchone()[0]
        sql += " AND list_date <= CAST(? AS DATE) - INTERVAL (?) DAY"
        params.extend([date_start, int(min_days)])
    rows = db.execute(sql, params).fetchall()
    return sorted(r[0] for r in rows)


def resolve_codes(
    spec: FactorSpec,
    db: duckdb.DuckDBPyConnection,
    override: str | None = None,
    settings=settings,
) -> list[str]:
    """universe 三层解析：override > spec 内联/引用 > 全局默认。返回纯数字代码列表。"""
    if override is not None:
        data = _resolve_source(override, settings.universes_dir)
    elif spec.universe.ref is not None:
        data = _resolve_source(spec.universe.ref, settings.universes_dir)
    elif spec.universe.codes is not None:
        data = {"codes": spec.universe.codes}
    else:
        assert spec.universe.rules is not None
        data = {"rules": spec.universe.rules}

    if "codes" in data:
        codes = [normalize_code(c) for c in data["codes"]]
    elif "rules" in data:
        codes = _codes_from_rules(data["rules"], db, spec.date.start)
    else:
        raise ValueError(f"universe 数据必须包含 codes 或 rules: {data}")

    if not codes:
        raise ValueError("universe 无有效股票，请检查 codes/rules/引用文件")
    return codes
```

**实现修正记录（2026-08-15，实现期发现计划代码缺陷）：**
1. `resolve_codes` 的 `override` 先尝试 `normalize_code`：合法 6 位代码视为内联 codes（`--universe 600519` 调试便利）；否则按名称/路径解析。计划原代码对纯代码 override 会查 `universes/600519.yaml` 而失败。
2. rules base 查询默认过滤 `exchange IN (SSE, SZSE)`：否则 BSE 股票混入 universe，违反 M3a spec「BSE 明确不在 v1 集合」。
3. `min_list_days` SQL 改为 `CAST(list_date AS DATE) <= CAST(? AS DATE) - INTERVAL (?) DAY`：计划原代码对 VARCHAR list_date 直接比较报 DuckDB BinderError。
4. BSE 错误消息改为「v1 仅支持 SSE、SZSE，不含 BSE」：计划原文自相矛盾。

**追加修正记录（2026-08-15，代码审查修复）：**
5. `_codes_from_rules` 对未知规则键（如 `min_list_day` 拼写错误）抛错，避免拼写错误导致无过滤 universe 的静默错误。
6. `codes` 分支与 `stock_basic_tushare.symbol` 取交集：库中不存在的内联代码被过滤，空结果报「universe 无有效股票」——符合 M3a spec §5「空 universe 报错 + 检查 codes 拼写」。
7. `min_list_days` 拒绝负值；`_resolve_source` 兼容尾部 `.yaml`；`normalize_code` 拒绝多段代码（`000001.SZ.X`）；内联 codes 去重排序。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_universe.py -v`
Expected: PASS。注意 `Settings(universes_dir=...)` 会触发 `settings.plugin_dir.mkdir`？不会——那是模块级 `settings = Settings()` 的行为；测试内新建 Settings 实例只创建实例。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/config.py src/factorlab/data tests/test_universe.py
git commit -m "feat: add universe resolution with three-tier priority"
```

---

### Task 3: DuckDB 只读数据加载

**Files:**
- Create: `src/factorlab/data/source.py`
- Test: `tests/test_source.py`

**Interfaces:** `load_daily(db_path, codes, date_start=None, date_end=None, cols=None, float32=True) -> pl.LazyFrame`
（`date` 列 cast `pl.Date`；`code` 列保持字符串）。

- [ ] **Step 1: Write the failing test**

Create `tests/test_source.py`:

```python
import duckdb
import polars as pl
import pytest

from factorlab.data.source import load_daily


def build_db(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE daily (date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, amount DOUBLE, turnover DOUBLE, pct_chg DOUBLE, code VARCHAR)")
    db.execute("""INSERT INTO daily VALUES
        ('2024-01-02', 10.0, 11.0, 9.5, 10.5, 1000.0, 1e6, 0.01, 0.5, '000001'),
        ('2024-01-03', 10.5, 11.5, 10.0, 11.0, 1100.0, 1.1e6, 0.02, 0.4, '000001'),
        ('2024-01-02', 20.0, 21.0, 19.0, 20.5, 2000.0, 2e6, 0.01, 0.3, '600519')""")
    return db


def test_load_daily_filters_codes_and_dates(tmp_path):
    db = build_db(tmp_path)
    df = load_daily(db, ["000001"], date_start="2024-01-03").collect()
    assert df["code"].to_list() == ["000001"]
    assert df["date"].to_list() == [pl.Date(2024, 1, 3)]


def test_load_daily_float32_cast(tmp_path):
    db = build_db(tmp_path)
    df = load_daily(db, ["000001"]).collect()
    assert df.schema["close"] == pl.Float32


def test_load_daily_column_pruning(tmp_path):
    db = build_db(tmp_path)
    df = load_daily(db, ["000001"], cols=["close"]).collect()
    assert df.columns == ["date", "code", "close"]


def test_load_daily_rejects_empty_codes(tmp_path):
    db = build_db(tmp_path)
    with pytest.raises(ValueError, match="universe"):
        load_daily(db, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_source.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/data/source.py`:

```python
from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from factorlab.config import settings

BASE_COLS = ("open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg")


def load_daily(
    db_path: Path,
    codes: list[str],
    date_start: str | None = None,
    date_end: str | None = None,
    cols: list[str] | None = None,
    float32: bool = settings.use_float32,
) -> pl.LazyFrame:
    """DuckDB 只读加载 daily 面板：SQL-first 过滤 → float32 cast → LazyFrame。"""
    if not codes:
        raise ValueError("universe 为空，无法加载数据")
    cols = cols or list(BASE_COLS)

    con = duckdb.connect(str(db_path), read_only=True)
    con.execute(f"SET memory_limit='{settings.default_max_memory}'")
    con.execute("SET threads=2")

    where = ["code IN (SELECT unnest(?))"]
    params: list = [codes]
    if date_start is not None:
        where.append("date >= ?")
        params.append(date_start)
    if date_end is not None:
        where.append("date <= ?")
        params.append(date_end)

    query = (
        f"SELECT date, code, {', '.join(cols)} FROM daily"
        f" WHERE {' AND '.join(where)} ORDER BY code, date"
    )
    df = con.execute(query, params).pl()
    con.close()
    df = df.with_columns(pl.col("date").str.strptime(pl.Date, "%Y-%m-%d"))
    if float32:
        df = df.with_columns([pl.col(c).cast(pl.Float32) for c in cols])
    return df.lazy()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_source.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/data/source.py tests/test_source.py
git commit -m "feat: add read-only DuckDB daily loader"
```

---

### Task 4: 交易日历与停牌补全

**Files:**
- Create: `src/factorlab/data/calendar.py`
- Test: `tests/test_calendar.py`

**Interfaces:** `trading_calendar(db_path, date_start=None, date_end=None) -> pl.Series`（`pl.Date`）；
`fill_suspensions(df, calendar) -> pl.DataFrame`（补全后数值列 null）。

- [ ] **Step 1: Write the failing test**

Create `tests/test_calendar.py`:

```python
import polars as pl

from factorlab.data.calendar import fill_suspensions, trading_calendar


def test_trading_calendar_deduplicates(tmp_path):
    import duckdb
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE daily (date VARCHAR, code VARCHAR)")
    db.execute("INSERT INTO daily VALUES ('2024-01-02','A'), ('2024-01-03','A'), ('2024-01-03','B')")
    cal = trading_calendar(db)
    assert cal.to_list() == [pl.Date(2024, 1, 2), pl.Date(2024, 1, 3)]


def test_fill_suspensions_adds_missing_rows():
    calendar = pl.Series("date", [pl.Date(2024, 1, 2), pl.Date(2024, 1, 3)], dtype=pl.Date)
    df = pl.DataFrame({
        "date": [pl.Date(2024, 1, 3)],
        "code": ["A"],
        "close": [10.0],
    })
    out = fill_suspensions(df, calendar).sort(["code", "date"])
    assert out.height == 2
    assert out["close"].to_list() == [None, 10.0]   # 停牌日 close 为 null


def test_fill_suspensions_keeps_existing_data():
    calendar = pl.Series("date", [pl.Date(2024, 1, 2), pl.Date(2024, 1, 3)], dtype=pl.Date)
    df = pl.DataFrame({
        "date": [pl.Date(2024, 1, 2), pl.Date(2024, 1, 3)],
        "code": ["A", "A"],
        "close": [9.0, 10.0],
    })
    out = fill_suspensions(df, calendar).sort(["date"])
    assert out["close"].to_list() == [9.0, 10.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_calendar.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/data/calendar.py`:

```python
from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl


def trading_calendar(db_path: Path, date_start: str | None = None, date_end: str | None = None) -> pl.Series:
    """交易日历：daily 表 distinct date（范围内），返回 pl.Date Series。"""
    con = duckdb.connect(str(db_path), read_only=True)
    where, params = [], []
    if date_start is not None:
        where.append("date >= ?")
        params.append(date_start)
    if date_end is not None:
        where.append("date <= ?")
        params.append(date_end)
    sql = "SELECT DISTINCT date FROM daily" + (f" WHERE {' AND '.join(where)}" if where else "")
    dates = [r[0] for r in con.execute(sql, params).fetchall()]
    con.close()
    return pl.Series("date", dates, dtype=pl.Date)


def fill_suspensions(df: pl.DataFrame, calendar: pl.Series) -> pl.DataFrame:
    """按交易日历补全停牌行：日历 × 代码全连接，缺失数值列 null。"""
    codes = pl.DataFrame({"code": df["code"].unique()})
    grid = pl.DataFrame({"date": calendar}).join(codes, how="cross")
    return grid.join(df, on=["date", "code"], how="left")
```

**实现修正记录（2026-08-15，Task 4 实现期）：**
1. SQL 增加 `ORDER BY date`：DuckDB 不保证 `SELECT DISTINCT` 输出顺序，而本任务测试断言日历升序、且下游对齐语义需要确定性顺序。计划原代码无 ORDER BY。
2. 连接改用 `with duckdb.connect(..., read_only=True) as con` 上下文管理器（沿用 Task 3 审查修复的 source.py 模式，连接错误路径不残留）。
3. 测试改用 `datetime.date` 构造日期（polars 1.38 的 `pl.Date` 是 datatype 类，`pl.Date(2024,1,3)` 抛 TypeError）。

**追加修正记录（2026-08-15，代码审查）：**
4. `fill_suspensions` 全市场规模（5000 代码 × 5000 交易日 ≈ 2500 万行）峰值约 4-5GB（grid + 加载 df + join 哈希 + 输出），Polars 侧不受 DuckDB `memory_limit` 覆盖，且审查实测更大变体触发过段错误。M3a 的 e2e 规模（≤50 代码 ≈ 25 万行）安全；M3b 缓解：grid 的 code 列 cast Categorical（内存约 4-5x）或按代码流式 full join。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_calendar.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/data/calendar.py tests/test_calendar.py
git commit -m "feat: add trading calendar and suspension filling"
```

---

### Task 5: process 注册表与参数解析

**Files:**
- Create: `src/factorlab/process/__init__.py`
- Create: `src/factorlab/process/registry.py`
- Test: `tests/test_process.py`

**Interfaces:** `parse_chain_item(item) -> (name, kwargs)`；`register_processor(name)`；
`get_processor(name)`；`run_process_chain(df, chain, ctx) -> pl.DataFrame`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_process.py`:

```python
import polars as pl
import pytest

from factorlab.process.registry import get_processor, parse_chain_item, run_process_chain
from factorlab.process import processors  # noqa: F401  # 注册副作用


def test_parse_chain_item_keyword():
    assert parse_chain_item("winsorize(quantile=0.99)") == ("winsorize", {"quantile": 0.99})


def test_parse_chain_item_no_args():
    assert parse_chain_item("standardize()") == ("standardize", {})


def test_parse_chain_item_positional_and_types():
    name, kwargs = parse_chain_item("clip(-3, 3)")
    assert name == "clip" and kwargs["lower"] == -3.0 and kwargs["upper"] == 3.0


def test_parse_chain_item_invalid():
    with pytest.raises(ValueError):
        parse_chain_item("winsorize(quantile=")


def test_unknown_processor_rejected():
    with pytest.raises(KeyError, match="nope"):
        get_processor("nope")


def test_run_chain_applies_sequentially():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
        "code": ["A", "B", "A", "B"],
        "signal": [1.0, 1000.0, 2.0, 3.0],
    })
    out = run_process_chain(df, ["winsorize(quantile=0.5)", "standardize()"], ctx=None)
    assert out.columns == ["date", "code", "signal"]
    assert out["signal"].abs().max() < 5  # 去极值后 z-score 有界
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_process.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/process/__init__.py`（空文件）。

Create `src/factorlab/process/registry.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import polars as pl

_ITEM_RE = re.compile(r"^([a-z_][a-z0-9_]*)(?:\((.*)\))?$")


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def parse_chain_item(item: str) -> tuple[str, dict[str, Any]]:
    """'winsorize(quantile=0.99)' -> ('winsorize', {'quantile': 0.99})；
    'clip(-3, 3)' -> ('clip', {'lower': -3.0, 'upper': 3.0})（位置参数按序命名）。"""
    match = _ITEM_RE.match(item.strip())
    if not match:
        raise ValueError(f"非法 process 项: {item}")
    name, args_raw = match.group(1), match.group(2)
    kwargs: dict[str, Any] = {}
    if args_raw:
        for i, part in enumerate(args_raw.split(",")):
            part = part.strip()
            if not part:
                raise ValueError(f"非法 process 参数: {item}")
            if "=" in part:
                key, _, value = part.partition("=")
                kwargs[key.strip()] = _parse_value(value)
            else:
                kwargs[["lower", "upper", "value"][i] if i < 3 else f"arg{i}"] = _parse_value(part)
    return name, kwargs


@dataclass(frozen=True)
class ProcessorDef:
    name: str
    func: Callable[..., pl.DataFrame]


@dataclass
class ProcessCtx:
    """处理器上下文：db 为只读 duckdb 连接（neutralize/fillna 取行业/市值用）。"""
    db: duckdb.DuckDBPyConnection | None = None


_PROCESSORS: dict[str, ProcessorDef] = {}


def register_processor(name: str | None = None) -> Callable:
    def decorator(func: Callable[..., pl.DataFrame]) -> Callable[..., pl.DataFrame]:
        key = name or func.__name__
        _PROCESSORS[key] = ProcessorDef(name=key, func=func)
        return func

    return decorator


def get_processor(name: str) -> ProcessorDef:
    try:
        return _PROCESSORS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_PROCESSORS))
        raise KeyError(f"未知处理器: {name}（可用: {known}）") from exc


def run_process_chain(df: pl.DataFrame, chain: list[str], ctx=None) -> pl.DataFrame:
    """顺序执行 process 链；处理对象为 signal 列。ctx 为 ProcessCtx 或裸 duckdb 连接。"""
    pctx = ctx if isinstance(ctx, ProcessCtx) else ProcessCtx(db=ctx)
    result = df
    for item in chain:
        name, kwargs = parse_chain_item(item)
        result = get_processor(name).func(result, ctx=pctx, **kwargs)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_process.py -v`
Expected: FAIL — 部分用例失败：`winsorize/standardize` 处理器尚未实现（`processors` 导入不存在）。先创建 `processors.py` 的最小占位（Task 6 实现完整语义）：

```python
# src/factorlab/process/processors.py（Task 6 之前的最小占位）
from factorlab.process.registry import register_processor


@register_processor
def winsorize(df, ctx, quantile=0.99):
    return df


@register_processor
def standardize(df, ctx):
    return df
```

重跑 `pytest tests/test_process.py -v`：参数解析与错误用例 PASS，`test_run_chain_applies_sequentially` 仍 FAIL（占位不处理）——预期如此，Task 6 完成。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/process tests/test_process.py
git commit -m "feat: add process registry and chain item parser"
```

---

### Task 6: process 基础处理器

**Files:**
- Modify: `src/factorlab/process/processors.py`（完整实现）
- Test: `tests/test_process.py`

**Interfaces:** `winsorize(df, ctx, quantile=0.99)`、`standardize(df, ctx)`（别名 `zscore`）、
`csranknorm(df, ctx)`、`robustzscore(df, ctx)`、`clip(df, ctx, lower, upper)`、
`fillna(df, ctx, method="value", value=0.0)`（`industry_mean` 在 Task 7）。全部返回含处理后的 `signal` 列的 DataFrame。

- [ ] **Step 1: Write the failing test**

Append to `tests/test_process.py`:

```python
def _panel():
    return pl.DataFrame({
        "date": ["2024-01-02"] * 4 + ["2024-01-03"] * 4,
        "code": ["A", "B", "C", "D"] * 2,
        "signal": [1.0, 2.0, 3.0, 100.0, 1.0, 2.0, 3.0, 4.0],
    })


def test_winsorize_clips_extremes():
    out = run_process_chain(_panel(), ["winsorize(quantile=0.5)"], ctx=None)
    assert out["signal"].max() < 100.0


def test_standardize_cross_section():
    out = run_process_chain(_panel(), ["standardize()"], ctx=None)
    per_date = out.group_by("date").agg(
        mean=pl.col("signal").mean(),
        std=pl.col("signal").std(),
    )
    assert per_date["mean"].abs().max() < 1e-9
    assert per_date["std"].abs().max() > 0.9


def test_csranknorm_in_unit_interval():
    out = run_process_chain(_panel(), ["csranknorm()"], ctx=None)
    assert out["signal"].min() > 0.0 and out["signal"].max() <= 1.0


def test_robustzscore_bounds_extremes():
    out = run_process_chain(_panel(), ["robustzscore()"], ctx=None)
    assert out["signal"].abs().max() < 10.0


def test_clip_bounds():
    out = run_process_chain(_panel(), ["clip(-1, 1)"], ctx=None)
    assert out["signal"].min() >= -1.0 and out["signal"].max() <= 1.0


def test_fillna_value():
    df = _panel().with_columns(pl.when(pl.col("code") == "D").then(None).otherwise(pl.col("signal")).alias("signal"))
    out = run_process_chain(df, ["fillna(method=value, value=0.0)"], ctx=None)
    assert out["signal"].null_count() == 0
    assert out.filter(pl.col("code") == "D")["signal"].to_list() == [0.0, 0.0]


def test_fillna_forward_within_asset():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        "code": ["A", "A", "A", "A"],
        "signal": [1.0, None, 3.0, None],
    })
    out = run_process_chain(df, ["fillna(method=forward)"], ctx=None)
    assert out["signal"].to_list() == [1.0, 1.0, 3.0, 3.0]


def test_fillna_invalid_method():
    with pytest.raises(ValueError, match="fillna"):
        run_process_chain(_panel(), ["fillna(method=bogus)"], ctx=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_process.py -v`
Expected: FAIL — 占位处理器不处理 signal。

- [ ] **Step 3: Write minimal implementation**

Replace `src/factorlab/process/processors.py`:

```python
from __future__ import annotations

import polars as pl

from factorlab.process.registry import register_processor

SIGNAL = "signal"


def _x(df: pl.DataFrame) -> pl.Expr:
    return pl.col(SIGNAL)


@register_processor
def winsorize(df: pl.DataFrame, ctx, quantile: float = 0.99) -> pl.DataFrame:
    """截面分位数去极值：quantile=0.99 → 上下各 (1-q)/2 分位数 clip。"""
    if not 0.5 <= quantile < 1.0:
        raise ValueError(f"winsorize quantile 必须在 [0.5, 1.0): {quantile}")
    q_lo, q_hi = (1 - quantile) / 2, (1 + quantile) / 2
    x = _x(df)
    return df.with_columns(x.clip(x.quantile(q_lo).over("date"), x.quantile(q_hi).over("date")).alias(SIGNAL))


@register_processor
def standardize(df: pl.DataFrame, ctx) -> pl.DataFrame:
    """截面 z-score。"""
    x = _x(df)
    return df.with_columns(((x - x.mean().over("date")) / x.std().over("date")).alias(SIGNAL))


register_processor(name="zscore")(standardize)


@register_processor
def csranknorm(df: pl.DataFrame, ctx) -> pl.DataFrame:
    """截面排名归一化到 (0, 1]。"""
    x = _x(df)
    return df.with_columns((x.rank().over("date") / (x.count().over("date") + 1)).alias(SIGNAL))


@register_processor
def robustzscore(df: pl.DataFrame, ctx) -> pl.DataFrame:
    """中位数/MAD 稳健标准化。"""
    x = _x(df)
    med = x.median().over("date")
    mad = (x - med).abs().median().over("date")
    return df.with_columns(((x - med) / (1.4826 * mad)).alias(SIGNAL))


@register_processor
def clip(df: pl.DataFrame, ctx, lower: float, upper: float) -> pl.DataFrame:
    """常数截断。"""
    return df.with_columns(_x(df).clip(lower, upper).alias(SIGNAL))


@register_processor
def fillna(df: pl.DataFrame, ctx, method: str = "value", value: float = 0.0) -> pl.DataFrame:
    """缺失处理：value（常数）或 forward（组内前向，按 code+date 排序）。"""
    x = _x(df)
    if method == "value":
        expr = x.fill_null(value)
    elif method == "forward":
        expr = x.fill_null(strategy="forward").over("code", order_by="date")
    else:
        raise ValueError(f"fillna 不支持的 method: {method}（value|forward|industry_mean）")
    return df.with_columns(expr.alias(SIGNAL))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_process.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/process/processors.py tests/test_process.py
git commit -m "feat: add base process processors"
```

---

### Task 7: neutralize 处理器

**Files:**
- Modify: `src/factorlab/process/processors.py`
- Modify: `src/factorlab/process/registry.py`（`run_process_chain` 传入 ctx）
- Test: `tests/test_process.py`

**Interfaces:** `neutralize(df, ctx, by="market")`。ctx 为 `ProcessCtx`（含 duckdb 连接）；`by: market|industry|size`。同时补 `fillna(method=industry_mean)`。

- [ ] **Step 1: Write the failing test**

Append to `tests/test_process.py`:

```python
from dataclasses import dataclass
import duckdb

@dataclass
class FakeCtx:
    db: duckdb.DuckDBPyConnection


def build_basic_db(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE stock_basic_tushare (symbol VARCHAR, industry VARCHAR)")
    db.execute("INSERT INTO stock_basic_tushare VALUES ('A', '银行'), ('B', '银行'), ('C', '白酒'), ('D', '白酒')")
    db.execute("CREATE TABLE daily_basic (trade_date VARCHAR, ts_code VARCHAR, total_mv DOUBLE)")
    db.execute("INSERT INTO daily_basic VALUES ('20240102', '000001.SZ', 100.0), ('20240103', '000001.SZ', 120.0)")
    return db


def test_neutralize_market_demean():
    df = _panel()
    out = run_process_chain(df, ["neutralize(by=market)"], ctx=None)
    per_date = out.group_by("date").agg(pl.col("signal").mean())
    assert per_date["signal"].abs().max() < 1e-9


def test_neutralize_industry_group_mean_zero(tmp_path):
    db = build_basic_db(tmp_path)
    df = _panel().with_columns(pl.col("code").cast(pl.String))
    # A/B 同行业（银行）组内均值应为 0
    out = run_process_chain(df, ["neutralize(by=industry)"], ctx=FakeCtx(db))
    group_means = out.join(
        pl.DataFrame({"code": ["A", "B"], "industry": ["银行", "银行"]}),
        on="code",
    ).group_by("date").agg(pl.col("signal").mean())
    assert group_means["signal"].abs().max() < 1e-9


def test_neutralize_unknown_by():
    with pytest.raises(ValueError, match="neutralize"):
        run_process_chain(_panel(), ["neutralize(by=bogus)"], ctx=None)
```

注意 `test_neutralize_industry_group_mean_zero` 中 `daily_basic` 只造了 `000001.SZ`——industry 中性化不依赖 daily_basic，无碍；`size` 分支的 daily_basic 映射在集成 e2e（Task 10）覆盖。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_process.py::test_neutralize_* -v`
Expected: FAIL — `neutralize` 未注册。

- [ ] **Step 3: Write minimal implementation**

Append to `src/factorlab/process/processors.py`（并在文件头加 `import duckdb` 不需要——用 ctx.db 鸭子类型）：

```python
@register_processor
def neutralize(df: pl.DataFrame, ctx, by: str = "market") -> pl.DataFrame:
    """截面中心化：market 全截面 demean；industry 按静态行业组内 demean；
    size 按 daily_basic.total_mv 分组 demean。"""
    if ctx.db is None:
        raise ValueError("neutralize 需要 ProcessCtx(db) 上下文")
    x = _x(df)
    if by == "market":
        expr = x - x.mean().over("date")
    elif by == "industry":
        industry = ctx.db.execute(
            "SELECT symbol, industry FROM stock_basic_tushare WHERE industry IS NOT NULL AND industry != ''"
        ).pl()
        enriched = df.join(industry.rename({"symbol": "code"}), on="code", how="left")
        if enriched["industry"].null_count() > 0:
            raise ValueError(f"{enriched['industry'].null_count()} 只股票缺少行业信息，无法 neutralize(by=industry)")
        expr = x - x.mean().over(["date", "industry"])
        return enriched.with_columns(expr.alias(SIGNAL)).drop("industry")
    elif by == "size":
        mv = ctx.db.execute(
            "SELECT trade_date, ts_code, total_mv FROM daily_basic"
        ).pl().with_columns(
            pl.col("trade_date").str.strptime(pl.Date, "%Y%m%d"),
            pl.col("ts_code").str.split(".").first().alias("code"),
        ).select(["date", "code", "total_mv"])
        enriched = df.join(mv, on=["date", "code"], how="left")
        expr = x - x.mean().over(["date", "total_mv"])
        return enriched.with_columns(expr.alias(SIGNAL)).drop("total_mv")
    else:
        raise ValueError(f"neutralize 不支持的 by: {by}（market|industry|size）")
```

`fillna(method=industry_mean)` 追加：

```python
    elif method == "industry_mean":
        if ctx is None or not hasattr(ctx, "db"):
            raise ValueError("fillna(method=industry_mean) 需要 ProcessCtx(db) 上下文")
        industry = ctx.db.execute(
            "SELECT symbol, industry FROM stock_basic_tushare WHERE industry IS NOT NULL AND industry != ''"
        ).pl()
        enriched = df.join(industry.rename({"symbol": "code"}), on="code", how="left")
        expr = x.fill_null(x.mean().over(["date", "industry"]))
        return enriched.with_columns(expr.alias(SIGNAL)).drop("industry")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_process.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/process/processors.py tests/test_process.py
git commit -m "feat: add neutralize and industry-mean fillna"
```

---

### Task 8: 前向收益与周频对齐

**Files:**
- Create: `src/factorlab/engine/forward.py`
- Test: `tests/test_forward.py`

**Interfaces:** `compute_forward_returns(df, horizons=(5, 20), close_col="close") -> pl.DataFrame`；
`align_weekly(df) -> pl.DataFrame`。输入 df 须含 `date(pl.Date)/code/close` 且已按 code 内日期排序、停牌已补全。

- [ ] **Step 1: Write the failing test**

Create `tests/test_forward.py`:

```python
import polars as pl

from factorlab.engine.forward import align_weekly, compute_forward_returns


def _panel():
    return pl.DataFrame({
        "date": [pl.Date(2024, 1, d) for d in (2, 3, 4, 5)] * 2,
        "code": ["A"] * 4 + ["B"] * 4,
        "close": [10.0, 11.0, 12.0, 13.0, 20.0, 22.0, 24.0, 26.0],
    })


def test_forward_returns_5d():
    df = _panel()
    out = compute_forward_returns(df, horizons=(5,))
    assert "forward_return_5d" in out.columns
    # A: close[0]=10, close[5] 不存在（仅 4 天）→ null；若第 6 天存在则 = 13/10-1
    assert out["forward_return_5d"][0] is None


def test_forward_returns_value():
    df = _panel()
    df = df.vstack(pl.DataFrame({
        "date": [pl.Date(2024, 1, 8), pl.Date(2024, 1, 8)],
        "code": ["A", "B"],
        "close": [15.0, 30.0],
    }))
    out = compute_forward_returns(df, horizons=(5,))
    a = out.filter(pl.col("code") == "A").sort("date")
    assert a["forward_return_5d"][0] == 15.0 / 10.0 - 1  # 第 5 个交易日（1/8）相对 1/2
    assert a["forward_return_5d"][-1] is None


def test_align_weekly_last_trading_day():
    df = pl.DataFrame({
        "date": [pl.Date(2024, 1, 2), pl.Date(2024, 1, 3), pl.Date(2024, 1, 4), pl.Date(2024, 1, 5)],
        "code": ["A"] * 4,
        "signal": [1.0, 2.0, 3.0, 4.0],
    })
    out = align_weekly(df)
    assert out["date"].to_list() == [pl.Date(2024, 1, 5)]  # 周五为该周最后交易日
    assert out["signal"].to_list() == [4.0]


def test_align_weekly_cross_year_iso_week():
    # 2021-01-01 属于 ISO 2020 年第 53 周：不应与 2020 年第 53 周的 2020-12-31 合并
    df = pl.DataFrame({
        "date": [pl.Date(2020, 12, 31), pl.Date(2021, 1, 1)],
        "code": ["A", "A"],
        "signal": [1.0, 2.0],
    })
    out = align_weekly(df)
    assert out.height == 2  # 两个 ISO 周各保留最后交易日
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_forward.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/engine/forward.py`:

```python
from __future__ import annotations

import polars as pl


def compute_forward_returns(
    df: pl.DataFrame,
    horizons: tuple[int, ...] = (5, 20),
    close_col: str = "close",
) -> pl.DataFrame:
    """前向收益 forward_return_h = close[t+h] / close[t] - 1（h 交易日，组内按日期排序）。"""
    result = df.sort(["code", "date"])
    for h in horizons:
        close = pl.col(close_col)
        expr = (close.shift(-h).over("code", order_by="date") / close - 1).alias(f"forward_return_{h}d")
        result = result.with_columns(expr)
    return result


def align_weekly(df: pl.DataFrame) -> pl.DataFrame:
    """对齐到 ISO 周最后一个交易日（周内 date 最大值）。"""
    result = df.sort(["code", "date"]).with_columns(
        pl.col("date").dt.iso_year().alias("_iso_year"),
        pl.col("date").dt.week().alias("_week"),
        pl.col("date").max().over(["code", "_iso_year", "_week"]).alias("_week_end"),
    )
    return (
        result.filter(pl.col("date") == pl.col("_week_end"))
        .drop(["_iso_year", "_week", "_week_end"])
        .sort(["code", "date"])
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_forward.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/engine/forward.py tests/test_forward.py
git commit -m "feat: add forward returns and weekly alignment"
```

---

### Task 9: run_factor 装配

**Files:**
- Modify: `src/factorlab/engine/compute.py`
- Test: `tests/test_run_factor.py`

**Interfaces:** `RunContext(db_path, output_dir, universe_override, float32)`；
`FactorResult(spec, panel, summary)`；`run_factor(spec, ctx) -> FactorResult`（落盘 parquet + JSON）。

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_factor.py`:

```python
import json

import duckdb
import polars as pl
import pytest

from factorlab.engine.compute import RunContext, run_factor
from factorlab.spec import load_spec


def build_db(tmp_path):
    db = duckdb.connect(tmp_path / "q.duckdb")
    db.execute("CREATE TABLE daily (date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, amount DOUBLE, turnover DOUBLE, pct_chg DOUBLE, code VARCHAR)")
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]
    for code, base in (("A", 10.0), ("B", 20.0)):
        for i, d in enumerate(dates):
            db.execute("INSERT INTO daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (d, base + i, base + i + 0.5, base + i - 0.5, base + i + 1, 1000.0, 1e6, 0.01, 0.1, code))
    db.execute("CREATE TABLE stock_basic_tushare (symbol VARCHAR, ts_code VARCHAR, exchange VARCHAR, list_date VARCHAR, industry VARCHAR)")
    db.execute("INSERT INTO stock_basic_tushare VALUES ('A', 'A.SZ', 'SZSE', '1991-01-01', '银行'), ('B', 'B.SH', 'SSE', '2001-01-01', '白酒')")
    db.execute("CREATE TABLE st_status (code VARCHAR, date DATE, is_st BOOLEAN)")
    db.close()


def _spec(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text("""
name: demo
category: custom
direction: 1
universe:
  codes: ["A.SZ", "B.SH"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
process:
  - standardize()
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    return load_spec(path)


def test_run_factor_end_to_end(tmp_path):
    db_path = tmp_path / "q.duckdb"
    build_db(tmp_path)
    out_dir = tmp_path / "out"
    result = run_factor(_spec(tmp_path), RunContext(db_path=db_path, output_dir=out_dir))
    panel = result.panel
    assert "signal" in panel.columns and "forward_return_5d" in panel.columns
    assert panel.height > 0
    assert (out_dir / "panel.parquet").exists()
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["name"] == "demo"
    assert summary["universe_count"] == 2
    assert summary["panel_rows"] == panel.height


def test_run_factor_empty_universe_rejected(tmp_path):
    db_path = tmp_path / "q.duckdb"
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.universe.codes = ["999999.SZ"]  # 不存在
    with pytest.raises(ValueError, match="universe"):
        run_factor(spec, RunContext(db_path=db_path, output_dir=tmp_path / "out2"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_factor.py -v`
Expected: FAIL — `run_factor` 不存在。

- [ ] **Step 3: Write minimal implementation**

Modify `src/factorlab/engine/compute.py` — 追加（保留现有 `compute_formula`）：

```python
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import yaml

from factorlab.config import settings as _settings
from factorlab.data.calendar import fill_suspensions, trading_calendar
from factorlab.data.source import load_daily
from factorlab.data.universe import resolve_codes
from factorlab.process.registry import run_process_chain
from factorlab.engine.forward import align_weekly, compute_forward_returns
from factorlab.spec import FactorSpec

_ELEMENTWISE_COLS = {"abs", "log", "log1p", "sqrt", "exp", "sign", "floor", "if_else"}


def _formula_columns(formula: str) -> list[str]:
    """提取公式实际引用的数据列（排除算子名/函数参数/import 名/中间变量）。"""
    tree = ast.parse(formula)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.arg))}
    imported = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    cols = names - defined - imported - called - _ELEMENTWISE_COLS - {"signal"}
    return sorted(c for c in cols if not c.startswith("_") and c not in {"date", "code"})


@dataclass
class RunContext:
    db_path: Path = _settings.quant_db
    output_dir: Path = Path("results")
    universe_override: str | None = None
    float32: bool = _settings.use_float32


@dataclass
class FactorResult:
    spec: FactorSpec
    panel: pl.DataFrame
    summary: dict = field(default_factory=dict)


def run_factor(spec: FactorSpec, ctx: RunContext) -> FactorResult:
    """装配链路：universe → 加载 → 停牌补全 → 因子 → process → forward → 周频对齐 → 落盘。"""
    con = duckdb.connect(str(ctx.db_path), read_only=True)
    try:
        codes = resolve_codes(spec, con, override=ctx.universe_override)
        cols = _formula_columns(spec.formula) if spec.formula else None
        raw = load_daily(
            ctx.db_path, codes,
            date_start=spec.date.start, date_end=spec.date.end,
            cols=cols, float32=ctx.float32,
        ).collect()
        cal = trading_calendar(ctx.db_path, date_start=spec.date.start, date_end=spec.date.end)
        panel = fill_suspensions(raw, cal)
        panel = compute_formula(panel, spec.formula) if spec.formula else panel
        panel = run_process_chain(panel, spec.process, ctx=con)
        panel = compute_forward_returns(panel)
        panel = align_weekly(panel)
        if panel.height == 0:
            raise ValueError("日期段无数据，可运行 data refresh（M3b）")
    finally:
        con.close()

    summary = {
        "name": spec.name,
        "category": spec.category,
        "direction": spec.direction,
        "universe_count": len(codes),
        "date_start": str(panel["date"].min()) if panel.height else None,
        "date_end": str(panel["date"].max()) if panel.height else None,
        "panel_rows": panel.height,
        "signal_null_ratio": round(panel["signal"].null_count() / panel.height, 4) if panel.height else 1.0,
        "process": spec.process,
        "float32": ctx.float32,
        "spec_yaml": yaml.safe_dump(spec.model_dump(), allow_unicode=True),
    }
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(ctx.output_dir / "panel.parquet")
    (ctx.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return FactorResult(spec=spec, panel=panel, summary=summary)
```

注意：`run_factor` 需在 `compute_formula` 定义之后（文件尾部）追加。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_factor.py -v`
Expected: PASS。若 `compute_forward_returns` 依赖的 `close` 因 float32 精度导致断言敏感，保持 `pytest.approx` 于集成测试处使用。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/engine/compute.py tests/test_run_factor.py
git commit -m "feat: add run_factor pipeline assembly"
```

---

### Task 10: 集成 e2e 与文档

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_e2e.py`
- Modify: `docs/interface.md`
- Modify: `pyproject.toml`（注册 integration marker）

- [ ] **Step 1: Write the failing test**

Create `tests/conftest.py`:

```python
import os

import pytest

REAL_DB = "C:/Users/ThinkPad/quant-data/quant.duckdb"


@pytest.fixture
def real_db_path():
    if not os.path.exists(REAL_DB):
        pytest.skip(f"真实数据库不存在: {REAL_DB}")
    return REAL_DB
```

Register marker in `pyproject.toml`：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
markers = [
    "integration: 依赖真实 quant.duckdb 的集成测试（库缺失时跳过）",
]
```

Create `tests/test_e2e.py`:

```python
import json

import pytest

from factorlab.engine.compute import RunContext, run_factor
from factorlab.spec import load_spec


@pytest.mark.integration
def test_e2e_small_universe(real_db_path, tmp_path):
    spec_path = tmp_path / "e2e.yaml"
    spec_path.write_text("""
name: e2e_vol_skew
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
  - neutralize(by=market)
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_std_dev, ts_delay
  _ret = ts_delay(close, 1)
  _vol = ts_std_dev(_ret, 20)
  _mom = ts_mean(close, 20)
  signal = -_vol + ts_delay(_mom, 1)
""", encoding="utf-8")
    out_dir = tmp_path / "out"
    spec = load_spec(spec_path)
    result = run_factor(spec, RunContext(db_path=real_db_path, output_dir=out_dir))

    panel = result.panel
    assert panel.height > 0
    assert panel.columns == ["date", "code", "signal", "forward_return_5d", "forward_return_20d", "close"]
    assert panel["date"].dtype == pl.Date
    assert (out_dir / "panel.parquet").exists()
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["name"] == "e2e_vol_skew"
    assert summary["universe_count"] == 5
    assert summary["signal_null_ratio"] < 0.5


@pytest.mark.integration
def test_e2e_rules_universe(real_db_path, tmp_path):
    spec_path = tmp_path / "e2e_rules.yaml"
    spec_path.write_text("""
name: e2e_rules
category: custom
direction: -1
universe:
  rules: {exclude_st: true, exchanges: ["SSE"]}
date:
  start: "2024-01-01"
  end: "2024-03-31"
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    spec = load_spec(spec_path)
    result = run_factor(spec, RunContext(db_path=real_db_path, output_dir=tmp_path / "out2"))
    assert result.panel.height > 0
```

- [ ] **Step 2: Run test to verify it fails / 跳过**

Run: `pytest tests/test_e2e.py -v`
Expected: 真实库存在则 FAIL（`run_factor` 尚未完成链路），或 Task 9 后运行则为 PASS；库不存在时 SKIP。

- [ ] **Step 3: 更新文档**

在 `docs/interface.md` 的 `## 4. Python API` 末尾追加：

```markdown
### `factorlab.engine.compute.run_factor(spec, ctx) -> FactorResult`

装配完整链路：universe 解析 → `load_daily` → 停牌补全 → `compute_formula` →
process 链 → 前向收益 → 周频对齐 → 落盘 `panel.parquet` + `summary.json`。

`RunContext` 字段：`db_path`（默认 `settings.quant_db`）、`output_dir`、
`universe_override`（三层优先级最高）、`float32`。

### `factorlab.data.universe.resolve_codes(spec, db, override=None, settings=settings) -> list[str]`

universe 三层解析：`override` > spec 内联（`ref` 命名引用 / `codes` / `rules`）> 全局默认
（`FACTORLAB_DEFAULT_UNIVERSE`）。返回纯数字代码列表（`daily.code` 格式）。

命名引用查 `~/.factorlab/universes/<name>.yaml`（或直接给文件路径）。
**挖掘约定**：同批次因子固定同一 universe（默认池或 `--universe`），同池计算、同池比较。

### `factorlab.data.source.load_daily(db_path, codes, date_start=None, date_end=None, cols=None, float32=True) -> pl.LazyFrame`

DuckDB 只读加载；SQL-first 过滤；`date` cast `pl.Date`；数值列 float32。

### `factorlab.data.calendar.trading_calendar / fill_suspensions`

交易日历（distinct date）与停牌补全（日历×代码全连接，缺失数值 null）。

### process 链

处理器：`winsorize(quantile=0.99)`、`standardize()`（别名 `zscore`）、`csranknorm()`、
`robustzscore()`、`neutralize(by=market|industry|size)`、`clip(lower, upper)`、
`fillna(method=value|forward|industry_mean)`。全部截面语义（`.over("date")`）；
`neutralize/fillna` 的行业依赖 `stock_basic_tushare` 静态行业（v1 近似）。
`run_process_chain(df, chain, ctx)` 顺序执行。

### `factorlab.engine.forward.compute_forward_returns / align_weekly`

前向收益 `close[t+h]/close[t]-1`（h 交易日，输入须停牌补全）；周频对齐取 ISO 周
最后交易日。
```

- [ ] **Step 4: 运行全量测试并验证**

Run:
```powershell
python -m pytest -q
```
Expected: 全部 PASS（M1/M2 54 个 + 新增；e2e 在真实库存在时通过）。

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_e2e.py docs/interface.md pyproject.toml
git commit -m "docs: document M3a data layer APIs; add e2e integration tests"
```

---

## Self-Review

**1. Spec coverage（对照 M3a spec）：**
- 2.1 source.py → Task 3 ✓；2.2 universe 三层解析/引用文件/代码标准化/rules → Task 2 ✓；
- 2.3 calendar/停牌补全 → Task 4 ✓；2.4 registry/参数解析/8 处理器/neutralize 依赖 → Task 5/6/7 ✓；
- 2.5 forward/周频对齐 → Task 8 ✓；2.6 run_factor 装配/落盘 → Task 9 ✓；
- §4 数据流 → Task 9 装配顺序一致 ✓；§5 错误处理（空 universe/文件缺失/日期缺失提示/未知处理器/依赖列缺失）→ Task 2/3/5/6/7 ✓；
- §6 测试（单测 + 集成 e2e + 防回归）→ 各任务 + Task 10 ✓；
- §7 明确不做 → 计划不含 ✓。
- 缺：spec 3 节「日期缺失提示 data refresh（M3b）」——`run_factor` 数据范围为空时 summary 全 null，未显式报错。补：Task 9 的 `run_factor` 中 panel 为空（height==0）时 raise 明确错误。已在 summary 处防御（`if panel.height else`），改为显式：`if panel.height == 0: raise ValueError("日期段无数据，可运行 data refresh（M3b）")`。

**2. Placeholder scan：** 无 TBD/TODO；Task 5 的占位处理器为计划内中间态（明确标注 Task 6 替换）。✓

**3. Type consistency：** `RunContext/FactorResult`、`resolve_codes(spec, db, override, settings)`、
`load_daily(db_path, codes, ...)`、`run_process_chain(df, chain, ctx)`、
`compute_forward_returns(df, horizons, close_col)`、`align_weekly(df)` 在任务间一致；
`ctx` 在 process 链中统一为 duckdb 连接（Task 7 用 `ctx.db`——不一致！registry 的
`run_process_chain(df, chain, ctx)` 直传 `ctx` 给处理器；Task 7 处理器签名 `neutralize(df, ctx, by)`，
用 `ctx.db`；而 Task 9 调用 `run_process_chain(panel, spec.process, ctx=con)` 传的是**连接**。
统一：`run_process_chain` 内部包 `ProcessCtx(db=ctx)`？修正：`run_process_chain` 收到裸连接时
包装为 `ProcessCtx`，处理器统一 `ctx.db`。Task 9 改为传 `con`，registry 内：

```python
@dataclass
class ProcessCtx:
    db: duckdb.DuckDBPyConnection | None = None


def run_process_chain(df, chain, ctx=None):
    ...
    pctx = ctx if isinstance(ctx, ProcessCtx) else ProcessCtx(db=ctx)
    result = get_processor(name).func(result, ctx=pctx, **kwargs)
```

Task 5/6/7 的处理器 `ctx` 参数一律为 `ProcessCtx`（`ctx.db` 取连接）。已按此修订 Task 5 的 registry 代码与 Task 6/7 处理器签名一致。✓
```

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-15-factorlab-m3a-data-layer.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks.
2. Inline Execution - execute tasks in this session using executing-plans with checkpoints.

Which approach?
