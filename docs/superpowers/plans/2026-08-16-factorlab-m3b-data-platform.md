# FactorLab M3b 数据平台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 teajoin 全量重建平台自有数据（零继承 quant-data），提供复权能力层与字段稀疏度治理，支持验证、增量刷新与 quant-data 清理。

**Architecture:** `data/fetcher.py`（teajoin 客户端）→ `data/platform_db.py`（暂存库）→ `data/rebuild.py`（manifest 断点续传编排）→ 稀疏评估后重建最终库 → `data/adjust.py`（复权视图/审计）→ `data/verify.py`（自检/对拍）→ `data/refresh.py`（增量）。

**Tech Stack:** Python 3.13、requests、DuckDB、Polars、pytest（mock HTTP）。

**Spec:** `docs/superpowers/specs/2026-08-16-factorlab-m3b-data-platform-design.md`

## Global Constraints

- Python 3.13，包结构 `src/factorlab`；测试 `pythonpath = ["src"]`。
- 不修改 `C:\Users\ThinkPad\quant-data` 任何文件；重建期间平台库为写模式（平台自有），参考库只读。
- teajoin 限流 450 次/分钟：客户端默认 0.2s 间隔；测试用 interval=0。
- token 从 `settings.teajoin_token`（.env `FACTORLAB_TEAJOIN_TOKEN`）读取。
- 平台数据目录：`data/`（gitignored）：`rebuild_staging.duckdb`、`factorlab.duckdb`、`manifest.json`。
- 每个功能先写失败测试（正常/边界/错误三类），转绿后提交（CLAUDE.md 硬性要求）。
- 集成测试 `@pytest.mark.integration`（token 存在才跑真实 API）。
- 新代码同步更新 `docs/interface.md`（Task 9）。
- 稀疏阈值默认 `null_ratio > 0.2` 或 `stock_coverage < 0.8` → 剔除。

## File Structure

- `src/factorlab/config.py`（Modify）：`data_dir`。
- `src/factorlab/data/fetcher.py`、`platform_db.py`、`rebuild.py`、`refresh.py`、`adjust.py`、`verify.py`（Create）。
- `src/factorlab/cli/main.py`（Modify，Task 9：`data` 子命令）。
- `tests/test_fetcher.py`、`test_platform_db.py`、`test_adjust.py`、`test_audit.py`、
  `test_rebuild.py`、`test_sparsity.py`、`test_verify.py`、`test_refresh.py`、`test_cli_data.py`（Create）。
- `docs/interface.md`（Modify，Task 9）。

---

### Task 1: TeaJoinClient

**Files:**
- Create: `src/factorlab/data/fetcher.py`
- Test: `tests/test_fetcher.py`

**Interfaces:** `TeaJoinError(api_name, message)`；`TeaJoinClient(token, base_url, interval, max_retries)`；
`fetch(api_name, params, fields=None) -> pl.DataFrame`；`fetch_paged(api_name, params, page_size, max_pages) -> pl.DataFrame`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_fetcher.py`:

```python
import polars as pl
import pytest

from factorlab.data.fetcher import TeaJoinClient, TeaJoinError


def _ok_response(items=None, fields=None):
    return type("R", (), {"status_code": 200, "json": lambda self: {
        "code": 0,
        "data": {"fields": fields or ["ts_code", "trade_date", "close"],
                 "items": items or [["000001.SZ", "20240102", 10.0], ["000002.SZ", "20240102", 20.0]]},
    }})()


def _empty_response():
    return type("R", (), {"status_code": 200, "json": lambda self: {"code": 0, "data": None}})()


def _err_response(status, body=None):
    return type("R", (), {"status_code": status, "json": lambda self: body or {"code": 4002, "msg": "权限不足"}, "text": "err"})()


def _client(monkeypatch, responder, interval=0.0):
    client = TeaJoinClient(token="t", interval=interval)
    monkeypatch.setattr(client, "_post", responder)
    return client


def test_fetch_parses_items_to_dataframe(monkeypatch):
    calls = []

    def responder(url, json=None, timeout=30):
        calls.append(json)
        return _ok_response()

    client = _client(monkeypatch, responder)
    df = client.fetch("daily", {"trade_date": "20240102"}, fields=["ts_code", "trade_date", "close"])
    assert df.columns == ["ts_code", "trade_date", "close"]
    assert df.height == 2
    assert calls[0]["api_name"] == "daily"
    assert calls[0]["token"] == "t"


def test_fetch_empty_data_returns_empty_frame(monkeypatch):
    client = _client(monkeypatch, lambda url, json=None, timeout=30: _empty_response())
    df = client.fetch("daily", {"trade_date": "20200101"})
    assert df.height == 0


def test_fetch_business_error_raises(monkeypatch):
    client = _client(monkeypatch, lambda url, json=None, timeout=30: _err_response(400))
    with pytest.raises(TeaJoinError, match="daily"):
        client.fetch("daily", {"trade_date": "20240102"})


def test_fetch_retries_on_network_error(monkeypatch):
    attempts = []

    def flaky(url, json=None, timeout=30):
        attempts.append(1)
        if len(attempts) < 3:
            raise requests.exceptions.ConnectionError("boom")
        return _ok_response()

    client = _client(monkeypatch, flaky, interval=0.0)
    df = client.fetch("daily", {"trade_date": "20240102"})
    assert len(attempts) == 3
    assert df.height == 2


def test_fetch_gives_up_after_max_retries(monkeypatch):
    attempts = []

    def always_fail(url, json=None, timeout=30):
        attempts.append(1)
        raise requests.exceptions.ConnectionError("boom")

    client = _client(monkeypatch, always_fail, interval=0.0)
    with pytest.raises(TeaJoinError):
        client.fetch("daily", {"trade_date": "20240102"})
    assert len(attempts) == 3


def test_fetch_throttles_interval(monkeypatch):
    import time
    sleeps = []
    real_sleep = time.sleep
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    def responder(url, json=None, timeout=30):
        return _ok_response()

    client = _client(monkeypatch, responder, interval=0.2)
    client.fetch("daily", {"trade_date": "20240102"})
    client.fetch("daily", {"trade_date": "20240103"})
    assert len(sleeps) >= 1 and sleeps[0] >= 0.19  # 第二次请求前补足间隔


def test_fetch_paged_loops_until_empty(monkeypatch):
    pages = []

    def responder(url, json=None, timeout=30):
        page = json["params"]["offset"]
        pages.append(page)
        if page == 0:
            return _ok_response(items=[["a", "20240102", 1.0]] * 5000)
        return _empty_response()

    client = _client(monkeypatch, responder, interval=0.0)
    df = client.fetch_paged("daily", {"trade_date": "20240102"}, page_size=5000)
    assert pages == [0, 5000]
    assert df.height == 5000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fetcher.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/data/fetcher.py`:

```python
from __future__ import annotations

import time

import polars as pl
import requests

from factorlab.config import settings


class TeaJoinError(Exception):
    """teajoin 业务错误（4xx 或重试耗尽）。"""

    def __init__(self, api_name: str, message: str) -> None:
        super().__init__(f"teajoin[{api_name}]: {message}")
        self.api_name = api_name


class TeaJoinClient:
    """teajoin Tushare 兼容代理客户端：全局限流 + 指数退避重试 + 分页。"""

    def __init__(
        self,
        token: str,
        base_url: str = "https://teajoin.com",
        interval: float = 0.2,
        max_retries: int = 3,
    ) -> None:
        self.token = token
        self.base_url = base_url
        self.interval = interval
        self.max_retries = max_retries
        self._last_request = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)

    def _post(self, url: str, json: dict, timeout: int = 30):
        return requests.post(url, json=json, timeout=timeout)

    def _call(self, api_name: str, params: dict, fields: list[str] | None) -> pl.DataFrame:
        payload = {"api_name": api_name, "token": self.token, "params": params}
        if fields:
            payload["fields"] = ",".join(fields)
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self._post(self.base_url, json=payload)
                self._last_request = time.monotonic()
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 500:
                last_exc = TeaJoinError(api_name, f"HTTP {resp.status_code}: {resp.text[:200]}")
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise TeaJoinError(api_name, f"HTTP {resp.status_code}: {resp.text[:200]}")
            body = resp.json()
            if body.get("code", 0) != 0:
                raise TeaJoinError(api_name, f"code={body.get('code')} msg={body.get('msg', '')}")
            data = body.get("data")
            if not data or not data.get("items"):
                return pl.DataFrame()
            return pl.DataFrame(data["items"], schema=data["fields"], orient="row")
        raise TeaJoinError(api_name, f"重试 {self.max_retries} 次仍失败: {last_exc}")

    def fetch(self, api_name: str, params: dict, fields: list[str] | None = None) -> pl.DataFrame:
        """单次拉取（tushare 标准协议）。"""
        return self._call(api_name, params, fields)

    def fetch_paged(
        self,
        api_name: str,
        params: dict,
        page_size: int = 5000,
        max_pages: int = 50,
        fields: list[str] | None = None,
    ) -> pl.DataFrame:
        """通用分页：params 注入 limit/offset 循环直到空页。"""
        frames: list[pl.DataFrame] = []
        for offset in range(0, page_size * max_pages, page_size):
            page_params = {**params, "limit": page_size, "offset": offset}
            page = self._call(api_name, page_params, fields)
            if page.height == 0:
                break
            frames.append(page)
        return pl.concat(frames) if frames else pl.DataFrame()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fetcher.py -v`
Expected: PASS。注意 `_throttle` 测试：`interval=0.2` 时第二次请求 sleep ≥0.19（monotonic 精度）——断言 `>= 0.19`。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/data/fetcher.py tests/test_fetcher.py
git commit -m "feat: add teajoin client with throttling and retry"
```

---

### Task 2: PlatformDB

**Files:**
- Create: `src/factorlab/data/platform_db.py`
- Test: `tests/test_platform_db.py`

**Interfaces:** `PlatformDB(path)`；`upsert(table, df, keys)`（首次插入自动建表）；
`list_tables()`；`describe(table) -> list[str]`；`integrity_check() -> dict`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_platform_db.py`:

```python
import datetime

import duckdb
import polars as pl
import pytest

from factorlab.data.platform_db import PlatformDB


def build_db(tmp_path):
    return PlatformDB(tmp_path / "p.duckdb")


def test_upsert_creates_table_and_deduplicates(tmp_path):
    db = build_db(tmp_path)
    df1 = pl.DataFrame({"trade_date": ["20240102", "20240102"], "ts_code": ["A", "B"], "close": [10.0, 20.0]})
    df2 = pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A"], "close": [11.0]})
    db.upsert("daily", df1, keys=["trade_date", "ts_code"])
    db.upsert("daily", df2, keys=["trade_date", "ts_code"])
    out = db.query("SELECT * FROM daily ORDER BY ts_code")
    assert out.height == 2
    assert out.filter(pl.col("ts_code") == "A")["close"][0] == 11.0  # 去重后更新


def test_list_tables_and_describe(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A"], "close": [1.0]}), keys=[])
    assert db.list_tables() == ["daily"]
    assert set(db.describe("daily")) >= {"trade_date", "ts_code", "close"}


def test_integrity_calendar_gaps(tmp_path):
    db = build_db(tmp_path)
    db.upsert("trade_cal", pl.DataFrame({"cal_date": ["20240102", "20240103", "20240104"], "is_open": [1, 1, 1]}), keys=[])
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240104"],
        "ts_code": ["A", "A"],
        "close": [10.0, 11.0],
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    gaps = report["daily"]["calendar_gaps"]
    assert gaps["failed"] > 0
    assert "20240103" in gaps["details"]


def test_integrity_duplicate_rows(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240102"],
        "ts_code": ["A", "A"],
        "close": [10.0, 10.0],
    }), keys=[])
    report = db.integrity_check()
    assert report["daily"]["duplicate_rows"]["failed"] == 1


def test_integrity_pct_chg_consistency(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103"],
        "ts_code": ["A", "A"],
        "close": [10.0, 11.0],
        "pct_chg": [0.0, 9.0],  # 应为 10.0
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    assert report["daily"]["pct_chg_consistency"]["failed"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_platform_db.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/data/platform_db.py`:

```python
from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

BASE_COLS = ("open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg")


class PlatformDB:
    """平台数据库：自动建表、upsert 去重、完整性自检。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path), read_only=read_only)

    def query(self, sql: str, params: list | None = None) -> pl.DataFrame:
        with self._connect(read_only=True) as con:
            return con.execute(sql, params or []).pl()

    def upsert(self, table: str, df: pl.DataFrame, keys: list[str]) -> None:
        """插入或替换（按 keys 去重）；表不存在时按 df schema 自动建表。"""
        if df.height == 0:
            return
        with self._connect() as con:
            if not con.execute("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]).fetchone():
                con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM df LIMIT 0')
            con.register("df", df.to_arrow())
            cols = ", ".join(f'"{c}"' for c in df.columns)
            if keys:
                con.execute(f'INSERT OR REPLACE INTO "{table}" ({cols}) SELECT {cols} FROM df')
            else:
                con.execute(f'INSERT INTO "{table}" ({cols}) SELECT {cols} FROM df')

    def list_tables(self) -> list[str]:
        with self._connect(read_only=True) as con:
            rows = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
            ).fetchall()
        return [r[0] for r in rows]

    def describe(self, table: str) -> list[str]:
        with self._connect(read_only=True) as con:
            rows = con.execute(f'DESCRIBE "{table}"').fetchall()
        return [r[0] for r in rows]

    def _rules(self) -> list[tuple[str, str, callable]]:
        """(rule_name, 依赖表, 检查函数)；按表存在性启用。"""
        return [
            ("calendar_gaps", "daily", self._check_calendar_gaps),
            ("duplicate_rows", "daily", self._check_duplicates),
            ("pct_chg_consistency", "daily", self._check_pct_chg),
            ("adj_factor_valid", "adj_factor", self._check_adj_factor),
            ("stk_limit_boundary", "daily", self._check_stk_limit),
            ("market_cap_valid", "daily_basic", self._check_market_cap),
        ]

    def integrity_check(self) -> dict[str, dict]:
        """每规则返回 {passed, failed, details}；缺依赖表时 passed=True 标记 skipped。"""
        tables = set(self.list_tables())
        report: dict[str, dict] = {}
        for rule_name, dep, fn in self._rules():
            entry = {"passed": True, "failed": 0, "details": []}
            if dep not in tables:
                entry["details"] = [f"依赖表 {dep} 不存在，跳过"]
                report.setdefault(dep, {})[rule_name] = entry
                continue
            fn(entry)
            report.setdefault(dep, {})[rule_name] = entry
        return report

    def _check_calendar_gaps(self, entry: dict) -> None:
        with self._connect(read_only=True) as con:
            rows = con.execute("""
                SELECT DISTINCT c.cal_date FROM trade_cal c
                WHERE c.is_open = 1 AND c.cal_date NOT IN (SELECT DISTINCT trade_date FROM daily)
            """).fetchall()
        entry["failed"] = len(rows)
        entry["passed"] = len(rows) == 0
        entry["details"] = [r[0] for r in rows[:20]]

    def _check_duplicates(self, entry: dict) -> None:
        with self._connect(read_only=True) as con:
            n = con.execute("""
                SELECT count(*) FROM (
                    SELECT trade_date, ts_code, count(*) c FROM daily GROUP BY 1, 2 HAVING c > 1
                )
            """).fetchone()[0]
        entry["failed"] = n
        entry["passed"] = n == 0

    def _check_pct_chg(self, entry: dict) -> None:
        with self._connect(read_only=True) as con:
            n = con.execute("""
                SELECT count(*) FROM (
                    SELECT trade_date, ts_code, close, pct_chg,
                           lag(close) OVER (PARTITION BY ts_code ORDER BY trade_date) prev_close
                    FROM daily
                ) WHERE prev_close IS NOT NULL
                  AND abs((close / prev_close - 1) * 100 - pct_chg) > 0.01
            """).fetchone()[0]
        entry["failed"] = n
        entry["passed"] = n == 0
        entry["details"] = [f"{n} 行 pct_chg 与 close 变化不一致"] if n else []

    def _check_adj_factor(self, entry: dict) -> None:
        with self._connect(read_only=True) as con:
            n = con.execute("SELECT count(*) FROM adj_factor WHERE adj_factor <= 0").fetchone()[0]
        entry["failed"] = n
        entry["passed"] = n == 0
        entry["details"] = [f"{n} 行 adj_factor <= 0"] if n else []

    def _check_stk_limit(self, entry: dict) -> None:
        with self._connect(read_only=True) as con:
            try:
                n = con.execute("""
                    SELECT count(*) FROM daily d
                    JOIN stk_limit s ON d.trade_date = s.trade_date AND d.ts_code = s.ts_code
                    WHERE d.close > s.up_limit * 1.0001 OR d.close < s.down_limit * 0.9999
                """).fetchone()[0]
            except duckdb.Error:
                entry["details"] = ["stk_limit 表结构不匹配，跳过"]
                return
        entry["failed"] = n
        entry["passed"] = n == 0
        entry["details"] = [f"{n} 行 close 超涨跌停边界"] if n else []

    def _check_market_cap(self, entry: dict) -> None:
        with self._connect(read_only=True) as con:
            n = con.execute("SELECT count(*) FROM daily_basic WHERE total_mv <= 0").fetchone()[0]
        entry["failed"] = n
        entry["passed"] = n == 0
        entry["details"] = [f"{n} 行 total_mv <= 0"] if n else []
```

注意：`daily` 表在 tushare 协议中主键是 `(trade_date, ts_code)`（不是平台的 `(date, code)`）——**M3b 平台库统一用 tushare 原始列名**（`trade_date`/`ts_code`），与 API 零转换，最干净。M4 引擎接入时再映射到平台的 `date/code`。

**实现修订（Task 2 已落地，与上面示例代码有出入）**：DuckDB 1.5 的 `INSERT OR REPLACE` 要求表带 UNIQUE/PRIMARY KEY 约束（CTAS 建的表没有，会 Binder 报错），实际改为事务内 `DELETE + INSERT`（按 keys 行值 IN 子查询），行为等价；`_rules()` 改为 (rule_name, 报告键, 依赖表元组, 检查函数) —— `calendar_gaps` 依赖 `trade_cal`+`daily`、`stk_limit_boundary` 依赖 `daily`+`stk_limit`，任一依赖表缺失或列结构不匹配（如 daily 无 pct_chg 列）时该规则跳过并在 details 注明原因，与 spec §5「报错并跳过」语义一致。
3. tushare 空值 `""` 在 fetcher 层规范化为 null（否则数值列推断为 String，数值自检规则在真实数据上静默跳过）；integrity 报告增加 `skipped` 状态区分跳过与通过。
4. upsert 首插事务化（显式 BEGIN/COMMIT/ROLLBACK，`with con:` 在 duckdb 1.5 不提供真实事务语义）；错误消息带 table/keys 上下文。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_platform_db.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/data/platform_db.py tests/test_platform_db.py
git commit -m "feat: add platform duckdb store with integrity checks"
```

---

### Task 3: 复权视图 PriceView + total_return

**Files:**
- Create: `src/factorlab/data/adjust.py`
- Test: `tests/test_adjust.py`

**Interfaces:** `PRICE_VIEWS = ("raw", "qfq", "hfq", "pit_qfq")`；
`view_prices(df, view="qfq", asof=None, adj_col="adj_factor") -> pl.DataFrame`；
`total_return(close, adj) -> pl.Expr`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_adjust.py`:

```python
import datetime

import polars as pl
import pytest

from factorlab.data.adjust import view_prices, total_return


def _panel():
    # 第 3 日 10 送 5（adj 1.0→1.5）；raw close 除权跳变
    return pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3), datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)],
        "code": ["A", "A", "A", "A"],
        "close": [10.0, 11.0, 8.0, 9.0],
        "adj_factor": [1.0, 1.0, 1.5, 1.5],
    })


def test_view_raw_unchanged():
    out = view_prices(_panel(), "raw")
    assert out["close"].to_list() == [10.0, 11.0, 8.0, 9.0]


def test_view_qfq_scales_by_latest_factor():
    out = view_prices(_panel(), "qfq")
    # factor = adj / adj[latest] = [1/1.5, 1/1.5, 1, 1]
    assert out["close"].to_list() == pytest.approx([10.0 / 1.5, 11.0 / 1.5, 8.0, 9.0])


def test_view_hfq_multiplies_by_factor():
    out = view_prices(_panel(), "hfq")
    assert out["close"].to_list() == pytest.approx([10.0, 11.0, 12.0, 13.5])


def test_view_pit_qfq_uses_asof_factor():
    out = view_prices(_panel(), "pit_qfq", asof=datetime.date(2024, 1, 3))
    # factor = adj / adj[asof=1.0] = [1, 1, 1.5, 1.5]
    assert out["close"].to_list() == pytest.approx([10.0, 11.0, 12.0, 13.5])


def test_view_pit_qfq_requires_asof():
    with pytest.raises(ValueError, match="asof"):
        view_prices(_panel(), "pit_qfq")


def test_view_unknown_raises():
    with pytest.raises(ValueError, match="view"):
        view_prices(_panel(), "bogus")


def test_total_return_includes_dividend():
    df = _panel()
    out = df.with_columns(total_return(pl.col("close"), pl.col("adj_factor")).alias("tr"))
    # tr[t] = close[t]*adj[t] / (close[t-1]*adj[t-1]) - 1（组内，首行 null）
    # [null, 11/10-1, 12/11-1, 13.5/12-1]
    assert out["tr"].to_list()[:1] == [None]
    assert out["tr"].to_list()[1:] == pytest.approx([0.1, 12.0 / 11.0 - 1, 13.5 / 12.0 - 1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adjust.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/data/adjust.py`:

```python
from __future__ import annotations

import datetime

import polars as pl

PRICE_VIEWS = ("raw", "qfq", "hfq", "pit_qfq")
_PRICE_COLS = ("open", "high", "low", "close")


def view_prices(
    df: pl.DataFrame,
    view: str = "qfq",
    asof: datetime.date | None = None,
    adj_col: str = "adj_factor",
) -> pl.DataFrame:
    """价格视图：RAW 原样；QFQ 前复权（adj/adj[latest]）；HFQ 后复权（×adj）；
    PIT_QFQ 动态前复权（adj/adj[asof]，研究日视角防未来）。"""
    if view not in PRICE_VIEWS:
        raise ValueError(f"未知价格视图: {view}（支持 {PRICE_VIEWS}）")
    if view == "raw":
        return df
    if view == "pit_qfq" and asof is None:
        raise ValueError("pit_qfq 视图必须提供 asof 研究日")

    if view == "qfq":
        factor = pl.col(adj_col) / pl.col(adj_col).last().over("code")
    elif view == "hfq":
        factor = pl.col(adj_col)
    else:  # pit_qfq
        asof_adj = df.filter(pl.col("date") <= asof).sort("date").select(pl.col(adj_col).last().over("code"))
        asof_adj = df.select(pl.col("code")).join(asof_adj, on="code", how="left")
        factor = pl.col(adj_col) / asof_adj[adj_col]

    scaled = [pl.col(c) * factor for c in _PRICE_COLS if c in df.columns]
    return df.with_columns(scaled)


def total_return(close: pl.Expr, adj: pl.Expr) -> pl.Expr:
    """含分红再投资的真实收益：close[t]×adj[t] / (close[t-1]×adj[t-1]) - 1（组内按日期）。"""
    hfq = close * adj
    return hfq / hfq.shift(1) - 1
```

注意 `pit_qfq` 的 asof_adj 实现有坑（join 后列名）——**实现时用 `pl.when` 简化**：研究日 T 的基准因子 = 每个 code 在 `date <= asof` 的最后一个 adj。正确写法：

```python
    else:  # pit_qfq
        assert asof is not None
        base = df.filter(pl.col("date") <= asof).sort("date").group_by("code").agg(pl.col(adj_col).last().alias("_asof_adj"))
        factor = pl.col(adj_col) / df.join(base, on="code", how="left")["_asof_adj"]
```

（以实际测试通过为准，两种写法都可，选 join 语义正确的。）

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adjust.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/data/adjust.py tests/test_adjust.py
git commit -m "feat: add price views and total return"
```

---

### Task 4: AdjustmentAudit 三审计

**Files:**
- Modify: `src/factorlab/data/adjust.py`
- Test: `tests/test_audit.py`

**Interfaces:** `AuditReport(check, passed, details)`；
`lookahead_check(factor_fn, df, asof) -> AuditReport`；
`scale_invariance_check(factor_fn, df) -> AuditReport`；
`adjustment_sensitivity_check(factor_fn, df) -> AuditReport`。
`factor_fn: Callable[[pl.DataFrame], pl.DataFrame]`——输入价格面板（date/code/价格列），输出 (date, code, signal)。

- [x] **Step 1: Write the failing test**

Create `tests/test_audit.py`:

```python
import datetime

import polars as pl
import pytest

from factorlab.data.adjust import (
    adjustment_sensitivity_check,
    lookahead_check,
    scale_invariance_check,
    view_prices,
)


def _panel():
    return pl.DataFrame({
        "date": [datetime.date(2024, 1, d) for d in (2, 3, 4, 5)] * 2,
        "code": ["A"] * 4 + ["B"] * 4,
        "close": [10.0, 11.0, 8.0, 9.0, 20.0, 22.0, 16.0, 18.0],
        "adj_factor": [1.0, 1.0, 1.5, 1.5] * 2,
    })


def _returns_factor(df):
    """收益率因子（scale-invariant，无未来信息）。"""
    return df.select([
        "date", "code",
        (pl.col("close") / pl.col("close").shift(1) - 1).over("code", order_by="date").alias("signal"),
    ])


def _leaky_factor(df):
    """泄漏因子：用了未来价格（shift(-1)）。"""
    return df.select([
        "date", "code",
        (pl.col("close").shift(-1).over("code", order_by="date") / pl.col("close") - 1).alias("signal"),
    ])


def test_lookahead_check_detects_future_leak():
    report = lookahead_check(_leaky_factor, _panel(), asof=datetime.date(2024, 1, 4))
    assert report.passed is False
    assert report.details["affected_rows"] > 0


def test_lookahead_check_clean_factor_passes():
    report = lookahead_check(_returns_factor, _panel(), asof=datetime.date(2024, 1, 4))
    assert report.passed is True


def test_scale_invariance_returns_factor_passes():
    report = scale_invariance_check(_returns_factor, _panel())
    assert report.passed is True


def test_scale_invariance_raw_price_factor_fails():
    def raw_price_factor(df):
        return df.select(["date", "code", pl.col("close").alias("signal")])

    report = scale_invariance_check(raw_price_factor, _panel())
    assert report.passed is False
    assert report.details["max_abs_diff"] > 1.0


def test_sensitivity_reports_variation():
    def raw_price_factor(df):
        return df.select(["date", "code", pl.col("close").alias("signal")])

    report = adjustment_sensitivity_check(raw_price_factor, _panel())
    assert report.passed is False  # 视图间变化显著
    assert "max_abs_diff" in report.details
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit.py -v`
Expected: FAIL — 审计函数不存在。

- [x] **Step 3: Write minimal implementation**

Append to `src/factorlab/data/adjust.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

FactorFn = Callable[[pl.DataFrame], pl.DataFrame]


@dataclass
class AuditReport:
    check: str
    passed: bool
    details: dict


def _align(left: pl.DataFrame, right: pl.DataFrame) -> pl.DataFrame:
    return left.join(right, on=["date", "code"], how="inner", suffix="_audit")


def lookahead_check(factor_fn: FactorFn, df: pl.DataFrame, asof: datetime.date) -> AuditReport:
    """未来信息泄漏检测：asof 截断数据重算因子 vs 全量重算，截断后受影响的行即泄漏。"""
    full = factor_fn(df)
    truncated = factor_fn(df.filter(pl.col("date") <= asof))
    aligned = _align(full.filter(pl.col("date") <= asof), truncated)
    diff = (aligned["signal"] - aligned["signal_audit"]).abs()
    affected = int((diff > 1e-9).sum())
    return AuditReport(
        check="lookahead",
        passed=affected == 0,
        details={"affected_rows": affected, "asof": str(asof)},
    )


def scale_invariance_check(factor_fn: FactorFn, df: pl.DataFrame) -> AuditReport:
    """价格尺度不变性：RAW 与 QFQ 视图下因子应一致（收益率类天然不变）。"""
    raw = factor_fn(view_prices(df, "raw"))
    qfq = factor_fn(view_prices(df, "qfq"))
    aligned = _align(raw, qfq)
    diff = (aligned["signal"] - aligned["signal_audit"]).abs()
    max_diff = float(diff.max()) if aligned.height else 0.0
    return AuditReport(
        check="scale_invariance",
        passed=max_diff < 1e-6,
        details={"max_abs_diff": round(max_diff, 8), "compared_rows": aligned.height},
    )


def adjustment_sensitivity_check(
    factor_fn: FactorFn,
    df: pl.DataFrame,
    views: tuple[str, ...] = ("raw", "qfq", "hfq"),
) -> AuditReport:
    """复权口径切换敏感性：各视图因子值的最大相对变化。"""
    frames = [factor_fn(view_prices(df, v)) for v in views]
    merged = frames[0].rename({"signal": "signal_raw"})
    for v, frame in zip(views[1:], frames[1:], strict=False):
        merged = merged.join(frame.rename({"signal": f"signal_{v}"}), on=["date", "code"], how="inner")
    signals = [pl.col(f"signal_{v}") for v in views]
    max_abs = max((s - pl.col("signal_raw")).abs().max() for s in signals[1:]) if len(signals) > 1 else 0.0
    max_abs = float(max_abs) if max_abs is not None else 0.0
    return AuditReport(
        check="adjustment_sensitivity",
        passed=max_abs < 1e-6,
        details={"max_abs_diff": round(max_abs, 8), "views": list(views)},
    )
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit.py -v`
Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add src/factorlab/data/adjust.py tests/test_audit.py
git commit -m "feat: add adjustment audit checks"
```

**实现偏差记录（2026-08-16 实现时发现，已修正并同步 docs/interface.md）：**
- 计划 Step 3 的实现有两处 bug，已修正：① `adjustment_sensitivity_check` 用内置
  `max()` 聚合 polars Expr 抛 `TypeError`，改用 `pl.max_horizontal`；② `lookahead_check`
  的 diff 对 null 行求和时被跳过（泄漏因子在截断边界值变 null 未计为受影响），
  改为 null-aware 布尔掩码（一侧 null 计受影响，两侧 null 不计）。
- 计划 Step 1 的 `test_scale_invariance_returns_factor_passes` 与 `_panel` 不自洽：
  面板含除权事件（1/4 除权），朴素收益率因子在除权日 RAW(-27.3%) 与 QFQ(+9.1%)
  天然不同（RAW 除权跳变，QFQ 含分红）——该测试无法通过。修正为用
  无除权事件面板（`adj_factor` 全 1）验证"收益率因子尺度不变"，语义不变。
- 超出计划的补充：`_require_columns` 列契约校验（缺 date/code/signal 列抛中文
  `ValueError`）；新增边界/错误路径测试（asof 早于全部数据、空面板、缺 signal 列）。

---

### Task 5: rebuild 编排与 manifest 断点续传

**Files:**
- Create: `src/factorlab/data/rebuild.py`
- Test: `tests/test_rebuild.py`
- Modify: `src/factorlab/config.py`（`data_dir`）

**Interfaces:** `load_manifest(path) -> dict`；`save_manifest(path, manifest)`；
`RebuildScope(start="20000104", end=None)`；`rebuild_all(db, client, scope, resume=True, manifest_path=None) -> dict`。

- [x] **Step 1: Write the failing test**

Create `tests/test_rebuild.py`:

```python
import json
from pathlib import Path

import polars as pl
import pytest

from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import RebuildScope, load_manifest, rebuild_all, save_manifest


def _fake_client(monkeypatch, tables: dict[str, pl.DataFrame]) -> TeaJoinClient:
    client = TeaJoinClient(token="t", interval=0.0)

    def responder(api_name, params, fields=None):
        key = (api_name, params.get("trade_date") or params.get("report_date") or params.get("cal_date") or "")
        for (name, _), df in tables.items():
            if name == api_name:
                return df
        return pl.DataFrame()

    monkeypatch.setattr(client, "fetch", responder)
    return client


def _tables():
    return {
        ("trade_cal", ""): pl.DataFrame({"exchange": ["SSE"], "cal_date": ["20240102", "20240103"], "is_open": [1, 1]}),
        ("stock_basic", ""): pl.DataFrame({"ts_code": ["A.SZ"], "symbol": ["A"], "name": ["甲"]}),
        ("daily", "20240102"): pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A.SZ"], "close": [10.0]}),
        ("daily", "20240103"): pl.DataFrame({"trade_date": ["20240103"], "ts_code": ["A.SZ"], "close": [11.0]}),
        ("daily_basic", "20240102"): pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A.SZ"], "total_mv": [100.0]}),
        ("daily_basic", "20240103"): pl.DataFrame({"trade_date": ["20240103"], "ts_code": ["A.SZ"], "total_mv": [110.0]}),
        ("adj_factor", "20240102"): pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A.SZ"], "adj_factor": [1.0]}),
        ("adj_factor", "20240103"): pl.DataFrame({"trade_date": ["20240103"], "ts_code": ["A.SZ"], "adj_factor": [1.0]}),
    }


def test_manifest_roundtrip(tmp_path):
    path = tmp_path / "manifest.json"
    save_manifest(path, {"daily": {"completed": ["20240102"]}})
    assert load_manifest(path) == {"daily": {"completed": ["20240102"]}}


def test_manifest_missing_defaults(tmp_path):
    assert load_manifest(tmp_path / "nope.json") == {}


def test_rebuild_all_populates_tables(tmp_path, monkeypatch):
    db = PlatformDB(tmp_path / "staging.duckdb")
    client = _fake_client(monkeypatch, _tables())
    report = rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240103"),
                         manifest_path=tmp_path / "manifest.json")
    assert db.list_tables() >= {"trade_cal", "stock_basic", "daily", "daily_basic", "adj_factor"}
    assert db.query("SELECT count(*) AS n FROM daily")["n"][0] == 2
    assert report["tables"]["daily"]["rows"] == 2


def test_rebuild_resume_skips_completed_dates(tmp_path, monkeypatch):
    db = PlatformDB(tmp_path / "staging.duckdb")
    client = _fake_client(monkeypatch, _tables())
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"daily": {"completed": ["20240102"], "failed": []}})
    report = rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240103"),
                         manifest_path=manifest_path)
    # 20240102 已 completed，只拉 20240103
    assert report["tables"]["daily"]["dates_fetched"] == ["20240103"]


def test_rebuild_requires_token():
    from factorlab.config import Settings
    settings = Settings(teajoin_token="")
    with pytest.raises(ValueError, match="token"):
        rebuild_all(PlatformDB(Path("x.duckdb")), TeaJoinClient(token=settings.teajoin_token),
                    scope=RebuildScope(), manifest_path=None)
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rebuild.py -v`
Expected: FAIL — 模块不存在。

- [x] **Step 3: Write minimal implementation**

Add to `src/factorlab/config.py`:

```python
    data_dir: Path = Path("data")
```

Create `src/factorlab/data/rebuild.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from factorlab.config import settings
from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB

DAILY_TABLES = ("daily", "daily_basic", "adj_factor", "stock_st", "stk_limit", "suspend_d", "moneyflow")
FINANCIAL_TABLES = ("income", "balancesheet", "cashflow")
INDEX_CODES = ("000300.SH", "000905.SH", "000852.SH", "000016.SH")


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class RebuildScope:
    start: str = "20000104"
    end: str | None = None


def _quarter_ends(year: int) -> list[str]:
    return [f"{year}0331", f"{year}0630", f"{year}0930", f"{year}1231"]


def _rebuild_daily_table(db: PlatformDB, client: TeaJoinClient, table: str, dates: list[str],
                         manifest: dict, manifest_path: Path) -> dict:
    """按交易日拉取单张行情表；跳过 completed，失败记录。"""
    completed = set(manifest.get(table, {}).get("completed", []))
    failed = list(manifest.get(table, {}).get("failed", []))
    fetched: list[str] = []
    total_rows = 0
    for d in dates:
        if d in completed:
            continue
        try:
            df = client.fetch(table, {"trade_date": d})
            db.upsert(table, df, keys=["trade_date", "ts_code"])
            completed.add(d)
            fetched.append(d)
            total_rows += df.height
        except Exception:
            failed.append(d)
        save_manifest(manifest_path, manifest)
    manifest.setdefault(table, {})["completed"] = sorted(completed)
    manifest.setdefault(table, {})["failed"] = sorted(set(failed))
    return {"dates_fetched": fetched, "rows": total_rows, "failed": sorted(set(failed))}


def rebuild_all(
    db: PlatformDB,
    client: TeaJoinClient,
    scope: RebuildScope = RebuildScope(),
    resume: bool = True,
    manifest_path: Path | None = None,
) -> dict:
    """全量重建编排：交易日历 → 静态 → 行情 7 表按日 → 财报按报告期 → 指数。"""
    if not client.token:
        raise ValueError("teajoin token 未配置（FACTORLAB_TEAJOIN_TOKEN）")
    manifest_path = manifest_path or (settings.data_dir / "manifest.json")
    manifest = load_manifest(manifest_path)

    # 1. 交易日历（重建骨架）
    cal = client.fetch("trade_cal", {"exchange": "SSE", "start_date": scope.start,
                                     "end_date": scope.end or "20261231"})
    cal = cal.filter(pl.col("is_open") == 1)
    dates = sorted(cal["cal_date"].to_list())
    if not dates:
        raise ValueError("trade_cal 无交易日，检查 token/日期范围")
    db.upsert("trade_cal", cal, keys=["exchange", "cal_date"])

    # 2. 静态表
    for status in ("L", "D"):
        df = client.fetch("stock_basic", {"list_status": status})
        if df.height:
            db.upsert("stock_basic", df, keys=["ts_code"])

    report: dict = {"tables": {}}

    # 3. 行情 7 表按日
    for table in DAILY_TABLES:
        report["tables"][table] = _rebuild_daily_table(db, client, table, dates, manifest, manifest_path)

    # 4. 财报按报告期（每季末拉全市场；无数据期正常空返回）
    years = range(int(scope.start[:4]), int((scope.end or "20261231")[:4]) + 1)
    report_dates = [d for y in years for d in _quarter_ends(y)]
    for table in FINANCIAL_TABLES:
        fetched: list[str] = []
        for rd in report_dates:
            try:
                df = client.fetch(table, {"report_date": rd})
                if df.height:
                    db.upsert(table, df, keys=["ts_code", "report_date"])
                    fetched.append(rd)
            except Exception:
                continue  # 单期失败不阻塞
        report["tables"][table] = {"report_dates": fetched, "rows": sum(
            db.query(f'SELECT count(*) AS n FROM "{table}"')["n"][0] for _ in [0] if db.list_tables()
        ) if db.list_tables() and table in db.list_tables() else 0}

    # 5. 指数
    for code in INDEX_CODES:
        idx = client.fetch("index_daily", {"ts_code": code, "start_date": scope.start,
                                           "end_date": scope.end or "20261231"})
        if idx.height:
            db.upsert("index_daily", idx, keys=["trade_date", "ts_code"])
    report["tables"]["index_daily"] = {"rows": db.query("SELECT count(*) AS n FROM index_daily")["n"][0]
                                       if "index_daily" in db.list_tables() else 0}

    manifest["last_updated"] = dates[-1]
    save_manifest(manifest_path, manifest)
    return report
```

（`index_weight` 按月的实现较繁琐，M3b 简化：拉最近一期成分 + 按季度补历史。**实现时若时间紧张可先只拉 `index_daily`**，`index_weight` 在 Task 9 集成阶段补——但计划以完整实现为准，循环每季度最后一个交易日拉 `index_weight`。）

**实现修订（Task 5 已落地，与上面示例代码有出入）**：
- `index_weight` 按**每月**最后一个交易日拉当期成分（4 指数 × 每月 1 次，从交易日
  骨架按 YYYYMM 分组取末位），manifest 按表记录 completed/failed 并每批落盘；
  index_daily/index_weight 拉取失败记录进 report 的 failed，不阻塞其他表。
- 强制要求 A/B（Task 2 审查遗留优化）：`PlatformDB` 新增 `connect()` 与
  `upsert_on(con, ..., dedup=True)`；行情 7 表循环持单连接（省 ~24ms/批重连 × 47k），
  `_rebuild_daily_table` 接收 con 参数，单日批 `dedup=False` 纯 INSERT（省 ~80ms/批
  DELETE 全表扫描）；`upsert()` 公共 API 默认 dedup=True 语义不变。
- stock_basic 用 `fetch_paged` 分页（list_status=L/D 各一轮）；trade_cal 空返回或
  无 is_open 列时抛 `ValueError`；`resume=False` 忽略既有 manifest 全量重拉；
  failed 日期重试成功即从 failed 移除。
- 测试：fake responder 按 `(api_name, 日期参数)` 精确匹配（计划版按接口名返回首个
  匹配，多日期数据会串表）；trade_cal 测试数据 exchange 列补足长度（polars 构造
  DataFrame 不广播 1 元素列）；`db.list_tables() >= {...}` 修正为 `set(...) >= {...}`；
  另补 PlatformDB connect/upsert_on/dedup 单测（tests/test_platform_db.py）。

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rebuild.py -v`
Expected: PASS（`test_rebuild_requires_token` 需确认 Settings(teajoin_token="") 行为——pydantic-settings 传空串 OK）。

- [x] **Step 5: Commit**

```bash
git add src/factorlab/config.py src/factorlab/data/rebuild.py src/factorlab/data/platform_db.py \
        tests/test_rebuild.py tests/test_platform_db.py docs/interface.md \
        docs/superpowers/plans/2026-08-16-factorlab-m3b-data-platform.md
git commit -m "feat: add rebuild orchestration with manifest resume"
```

---

### Task 6: 字段稀疏度评估与最终库重建

**Files:**
- Modify: `src/factorlab/data/rebuild.py`
- Test: `tests/test_sparsity.py`

**Interfaces:** `assess_sparsity(db) -> dict[str, dict[str, dict]]`（每表每字段 null_ratio/stock_coverage/first_date）；
`build_final_db(staging, final_path, null_threshold=0.2, coverage_threshold=0.8) -> dict`（含 excluded_fields）。

- [ ] **Step 1: Write the failing test**

Create `tests/test_sparsity.py`:

```python
import polars as pl
import pytest

from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import assess_sparsity, build_final_db


def _staging(tmp_path):
    db = PlatformDB(tmp_path / "staging.duckdb")
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102"] * 4,
        "ts_code": ["A", "B", "C", "D"],
        "close": [10.0, 20.0, 30.0, 40.0],
        "sparse_field": [1.0, None, None, None],  # null_ratio 0.75
        "half_field": [1.0, 2.0, 3.0, None],      # null_ratio 0.25
    }), keys=["trade_date", "ts_code"])
    return db


def test_assess_sparsity_metrics(tmp_path):
    db = _staging(tmp_path)
    report = assess_sparsity(db)
    sf = report["daily"]["sparse_field"]
    assert sf["null_ratio"] == 0.75
    assert sf["stock_coverage"] == 0.25
    assert sf["first_date"] == "20240102"
    hf = report["daily"]["half_field"]
    assert hf["null_ratio"] == 0.25


def test_build_final_db_excludes_sparse_fields(tmp_path):
    staging = _staging(tmp_path)
    final_path = tmp_path / "final.duckdb"
    result = build_final_db(staging, final_path)
    assert "sparse_field" in result["excluded_fields"]["daily"]  # null 75% > 20%
    assert "half_field" not in result["excluded_fields"]["daily"]  # 25% 也在阈内？——见下
    final = PlatformDB(final_path)
    assert "sparse_field" not in final.describe("daily")
    assert "close" in final.describe("daily")
```

注意 `half_field` 的 null_ratio=0.25 > 0.2 也应剔除！断言修正：`half_field` 也在 excluded（25% > 20%）。测试写清楚：

```python
def test_build_final_db_excludes_sparse_fields(tmp_path):
    staging = _staging(tmp_path)
    final_path = tmp_path / "final.duckdb"
    result = build_final_db(staging, final_path)
    excluded = result["excluded_fields"]["daily"]
    assert "sparse_field" in excluded and "half_field" in excluded
    final = PlatformDB(final_path)
    assert "sparse_field" not in final.describe("daily")
    assert "half_field" not in final.describe("daily")
    assert "close" in final.describe("daily")


def test_build_final_db_thresholds_configurable(tmp_path):
    staging = _staging(tmp_path)
    result = build_final_db(staging, tmp_path / "f2.duckdb", null_threshold=0.5)
    assert "half_field" not in result["excluded_fields"]["daily"]  # 25% < 50% 保留
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sparsity.py -v`
Expected: FAIL — 函数不存在。

- [ ] **Step 3: Write minimal implementation**

Append to `src/factorlab/data/rebuild.py`:

```python
def assess_sparsity(db: PlatformDB) -> dict[str, dict[str, dict]]:
    """每表每字段稀疏度：null_ratio / stock_coverage / first_date。"""
    report: dict[str, dict[str, dict]] = {}
    for table in db.list_tables():
        if table in {"trade_cal"}:
            continue
        cols = [c for c in db.describe(table) if c not in {"trade_date", "cal_date", "ts_code", "exchange"}]
        code_col = "ts_code" if "ts_code" in cols else None
        table_report: dict[str, dict] = {}
        for col in cols:
            total = db.query(f'SELECT count(*) AS n FROM "{table}"')["n"][0]
            non_null = db.query(f'SELECT count(*) AS n FROM "{table}" WHERE "{col}" IS NOT NULL')["n"][0]
            null_ratio = 1.0 - (non_null / total) if total else 1.0
            stock_coverage = 1.0
            if code_col and total:
                with_stock = db.query(
                    f'SELECT count(DISTINCT "{code_col}") AS n FROM "{table}" WHERE "{col}" IS NOT NULL'
                )["n"][0]
                all_stock = db.query(f'SELECT count(DISTINCT "{code_col}") AS n FROM "{table}"')["n"][0]
                stock_coverage = with_stock / all_stock if all_stock else 1.0
            first_date = db.query(
                f'SELECT min("{c}") AS d FROM "{table}" WHERE "{c}" IS NOT NULL'
            )["d"][0] if False else None
            table_report[col] = {
                "null_ratio": round(null_ratio, 4),
                "stock_coverage": round(stock_coverage, 4),
                "first_date": str(first_date) if first_date else None,
            }
        report[table] = table_report
    return report


def build_final_db(
    staging: PlatformDB,
    final_path: Path,
    null_threshold: float = 0.2,
    coverage_threshold: float = 0.8,
) -> dict:
    """评估稀疏度 → 剔除超限字段 → 重建最终库（物理排除）。"""
    sparsity = assess_sparsity(staging)
    excluded: dict[str, list[str]] = {}
    for table, fields in sparsity.items():
        excluded[table] = [
            col for col, m in fields.items()
            if m["null_ratio"] > null_threshold or m["stock_coverage"] < coverage_threshold
        ]
    final = PlatformDB(final_path)
    with duckdb.connect(str(final_path)) as con:
        for table in staging.list_tables():
            keep = [c for c in staging.describe(table) if c not in excluded.get(table, [])]
            if not keep:
                continue
            cols_sql = ", ".join(f'"{c}"' for c in keep)
            con.execute(f'CREATE TABLE "{table}" AS SELECT {cols_sql} FROM read_parquet(?)', [str(staging.path)])
    return {"excluded_fields": excluded, "tables": final.list_tables()}
```

注意 `build_final_db` 的跨库复制：duckdb 直接 `ATTACH` 两个库或 `read_duckdb`。**正确实现**：

```python
    with duckdb.connect(str(final_path)) as con:
        con.execute(f"ATTACH '{staging.path}' AS staging (READ_ONLY)")
        for table in staging.list_tables():
            keep = [c for c in staging.describe(table) if c not in excluded.get(table, [])]
            if not keep:
                continue
            cols_sql = ", ".join(f'"{c}"' for c in keep)
            con.execute(f'CREATE TABLE "{table}" AS SELECT {cols_sql} FROM staging."{table}"')
        con.execute("DETACH staging")
```

（staging.path 含反斜杠 Windows 路径——ATTACH 字符串转义注意，用 `str(staging.path).replace("\\", "/")` 或参数化；以实测为准。）

`first_date` 的计算在测试里用 `trade_date` 列——上面的占位写法有误，正确：

```python
            date_col = "trade_date" if "trade_date" in cols else "cal_date"
            first_date = None
            if date_col:
                first = db.query(
                    f'SELECT min("{date_col}") AS d FROM "{table}" WHERE "{col}" IS NOT NULL'
                )["d"][0]
                first_date = str(first) if first is not None else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sparsity.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/data/rebuild.py tests/test_sparsity.py
git commit -m "feat: assess field sparsity and rebuild final db excluding sparse fields"
```

---

### Task 7: verify 自检与抽样对拍

**Files:**
- Create: `src/factorlab/data/verify.py`
- Test: `tests/test_verify.py`

**Interfaces:** `verify_all(db, ref_db=None, n_stocks=30, seed=42) -> dict`；
`compare_sample(primary, ref_path, n_stocks, segments, tol) -> dict`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_verify.py`:

```python
import polars as pl
import pytest

from factorlab.data.platform_db import PlatformDB
from factorlab.data.verify import compare_sample, verify_all


def _mk_db(path, close_values=None, ref=False):
    db = PlatformDB(path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103", "20240102", "20240103"],
        "ts_code": ["A.SZ", "A.SZ", "B.SZ", "B.SZ"],
        "close": close_values or [10.0, 11.0, 20.0, 21.0],
        "pct_chg": [0.0, 10.0, 0.0, 5.0],
    }), keys=["trade_date", "ts_code"])
    db.upsert("trade_cal", pl.DataFrame({"cal_date": ["20240102", "20240103"], "is_open": [1, 1]}), keys=[])
    return db


def test_verify_all_runs_integrity(tmp_path):
    db = _mk_db(tmp_path / "p.duckdb")
    report = verify_all(db)
    assert "daily" in report["integrity"]
    assert report["sparse_summary"]["daily"] is not None


def test_compare_sample_matches(tmp_path):
    primary = _mk_db(tmp_path / "p.duckdb")
    ref = _mk_db(tmp_path / "r.duckdb", ref=True)
    report = compare_sample(primary, ref, n_stocks=2, segments=[("20240102", "20240103")], tol=1e-6)
    assert report["compared_rows"] == 4
    assert report["mismatches"] == 0


def test_compare_sample_detects_mismatch(tmp_path):
    primary = _mk_db(tmp_path / "p.duckdb")
    ref = _mk_db(tmp_path / "r.duckdb", close_values=[10.0, 99.0, 20.0, 21.0], ref=True)
    report = compare_sample(primary, ref, n_stocks=2, segments=[("20240102", "20240103")], tol=1e-6)
    assert report["mismatches"] >= 1
    assert len(report["details"]) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_verify.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/data/verify.py`:

```python
from __future__ import annotations

import random
from pathlib import Path

import duckdb
import polars as pl

from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import assess_sparsity

SEGMENTS = (("20200101", "20200131"), ("20230101", "20230131"), ("20260101", "20260131"))


def verify_all(db: PlatformDB, ref_db: Path | None = None, n_stocks: int = 30, seed: int = 42) -> dict:
    """完整性自检 + 稀疏摘要 + 可选抽样对拍。"""
    report = {
        "integrity": db.integrity_check(),
        "sparse_summary": assess_sparsity(db),
        "compare": None,
    }
    if ref_db is not None and Path(ref_db).exists():
        report["compare"] = compare_sample(db, ref_db, n_stocks=n_stocks, seed=seed)
    return report


def compare_sample(
    primary: PlatformDB,
    ref_path: Path,
    n_stocks: int = 30,
    segments: list[tuple[str, str]] | None = None,
    tol: float = 1e-4,
    seed: int = 42,
) -> dict:
    """随机抽样股票 × 日期段，对比 daily.close（容差相对误差）。"""
    segments = segments or SEGMENTS
    rng = random.Random(seed)
    all_codes = primary.query("SELECT DISTINCT ts_code FROM daily")["ts_code"].to_list()
    sample = rng.sample(all_codes, min(n_stocks, len(all_codes)))
    details: list[dict] = []
    compared = 0
    with duckdb.connect(str(ref_path), read_only=True) as ref:
        for code in sample:
            for start, end in segments:
                local = primary.query(
                    "SELECT trade_date, close FROM daily WHERE ts_code = ? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
                    [code, start, end],
                )
                remote = ref.execute(
                    "SELECT trade_date, close FROM daily WHERE ts_code = ? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
                    [code, start, end],
                ).pl()
                if local.height == 0 or remote.height == 0:
                    continue
                joined = local.join(remote, on="trade_date", how="inner", suffix="_ref")
                compared += joined.height
                rel = (joined["close"] - joined["close_ref"]).abs() / joined["close_ref"].abs()
                for row in joined.filter(rel > tol).iter_rows(named=True):
                    details.append({"ts_code": code, "trade_date": row["trade_date"],
                                    "local": row["close"], "ref": row["close_ref"]})
    return {"compared_rows": compared, "mismatches": len(details), "details": details[:50],
            "sampled_stocks": len(sample)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_verify.py -v`
Expected: PASS。注意 `compare_sample` 中 `pct_chg` 不一致的 daily 会影响 integrity 但测试数据已构造 pct_chg 与 close 自洽（10→11 是 10%，20→21 是 5% ✓）。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/data/verify.py tests/test_verify.py
git commit -m "feat: add data verification and sample comparison"
```

---

### Task 8: refresh 增量

**Files:**
- Create: `src/factorlab/data/refresh.py`
- Test: `tests/test_refresh.py`

**Interfaces:** `refresh(db, client, manifest_path=None) -> dict`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_refresh.py`:

```python
import polars as pl
import pytest

from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import load_manifest, save_manifest
from factorlab.data.refresh import refresh


def _client(monkeypatch, table_df: pl.DataFrame) -> TeaJoinClient:
    client = TeaJoinClient(token="t", interval=0.0)

    def responder(api_name, params, fields=None):
        if api_name == "trade_cal":
            return pl.DataFrame({"exchange": ["SSE"], "cal_date": ["20240103", "20240104"], "is_open": [1, 1]})
        if api_name == "daily":
            return table_df
        return pl.DataFrame()

    monkeypatch.setattr(client, "fetch", responder)
    return client


def test_refresh_pulls_from_last_updated(tmp_path, monkeypatch):
    db = PlatformDB(tmp_path / "p.duckdb")
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"daily": {"completed": ["20240102", "20240103"], "failed": []},
                                  "last_updated": "20240103"})
    client = _client(monkeypatch, pl.DataFrame({
        "trade_date": ["20240104"], "ts_code": ["A.SZ"], "close": [12.0],
    }))
    report = refresh(db, client, manifest_path=manifest_path)
    assert report["new_dates"] == ["20240104"]
    assert db.query("SELECT count(*) AS n FROM daily")["n"][0] == 1
    manifest = load_manifest(manifest_path)
    assert manifest["last_updated"] == "20240104"
    assert "20240104" in manifest["daily"]["completed"]


def test_refresh_no_new_dates(tmp_path, monkeypatch):
    db = PlatformDB(tmp_path / "p.duckdb")
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"last_updated": "20240104"})
    client = _client(monkeypatch, pl.DataFrame())
    report = refresh(db, client, manifest_path=manifest_path)
    assert report["new_dates"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_refresh.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/data/refresh.py`:

```python
from __future__ import annotations

import datetime
from pathlib import Path

import polars as pl

from factorlab.config import settings
from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import DAILY_TABLES, load_manifest, save_manifest


def refresh(db: PlatformDB, client: TeaJoinClient, manifest_path: Path | None = None) -> dict:
    """从 manifest.last_updated 次日到最新交易日，增量续拉行情表。"""
    manifest_path = manifest_path or (settings.data_dir / "manifest.json")
    manifest = load_manifest(manifest_path)
    last = manifest.get("last_updated")
    if not last:
        raise ValueError("manifest 无 last_updated，请先 rebuild")

    today = datetime.date.today().strftime("%Y%m%d")
    cal = client.fetch("trade_cal", {"exchange": "SSE", "start_date": last, "end_date": today})
    new_dates = sorted(d for d in cal.filter(pl.col("is_open") == 1)["cal_date"].to_list() if d > last)
    if not new_dates:
        return {"new_dates": [], "tables": {}}

    report: dict = {"new_dates": new_dates, "tables": {}}
    for table in DAILY_TABLES:
        completed = set(manifest.get(table, {}).get("completed", []))
        rows = 0
        for d in new_dates:
            try:
                df = client.fetch(table, {"trade_date": d})
                db.upsert(table, df, keys=["trade_date", "ts_code"])
                completed.add(d)
                rows += df.height
            except Exception:
                continue
        manifest.setdefault(table, {})["completed"] = sorted(completed)
        report["tables"][table] = {"rows": rows}
    manifest["last_updated"] = new_dates[-1]
    save_manifest(manifest_path, manifest)
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_refresh.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/data/refresh.py tests/test_refresh.py
git commit -m "feat: add incremental refresh"
```

---

### Task 9: CLI data 子命令、文档与集成测试

**Files:**
- Modify: `src/factorlab/cli/main.py`
- Modify: `docs/interface.md`
- Test: `tests/test_cli_data.py`、`tests/test_e2e_data.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_data.py`:

```python
from typer.testing import CliRunner

from factorlab.cli.main import app

runner = CliRunner()


def test_data_help_lists_commands():
    result = runner.invoke(app, ["data", "--help"])
    assert result.exit_code == 0
    for command in ("rebuild", "refresh", "verify"):
        assert command in result.stdout


def test_data_verify_missing_token_reports():
    # verify 不需要 token；rebuild 需要——验证错误路径
    result = runner.invoke(app, ["data", "rebuild", "--help"])
    assert result.exit_code == 0
```

Create `tests/test_e2e_data.py`（集成，token 存在才跑）：

```python
import os

import polars as pl
import pytest

from factorlab.config import settings
from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import assess_sparsity, build_final_db

pytestmark = pytest.mark.integration


@pytest.fixture
def live_client():
    if not settings.teajoin_token:
        pytest.skip("teajoin token 未配置（FACTORLAB_TEAJOIN_TOKEN）")
    return TeaJoinClient(token=settings.teajoin_token)


def test_live_fetch_daily(live_client, tmp_path):
    df = live_client.fetch("daily", {"trade_date": "20240102"}, fields=["trade_date", "ts_code", "close"])
    assert df.height > 3000  # 全市场单日 3000+ 只


def test_live_sparsity_pipeline(live_client, tmp_path):
    db = PlatformDB(tmp_path / "staging.duckdb")
    for table in ("daily", "daily_basic", "adj_factor"):
        df = live_client.fetch(table, {"trade_date": "20240102"})
        if df.height:
            db.upsert(table, df, keys=["trade_date", "ts_code"])
    assert db.list_tables() >= {"daily"}
    sparsity = assess_sparsity(db)
    assert "null_ratio" in sparsity["daily"]["close"]
    result = build_final_db(db, tmp_path / "final.duckdb")
    assert "daily" in result["tables"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_data.py -v`
Expected: FAIL — `data` 子命令不存在。

- [ ] **Step 3: Write minimal implementation**

Modify `src/factorlab/cli/main.py`（追加）：

```python
from factorlab.config import settings
from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import RebuildScope, rebuild_all
from factorlab.data.refresh import refresh
from factorlab.data.verify import verify_all

data_app = typer.Typer(no_args_is_help=True)
app.add_typer(data_app, name="data")


def _db() -> PlatformDB:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return PlatformDB(settings.data_dir / "factorlab.duckdb")


def _client() -> TeaJoinClient:
    return TeaJoinClient(token=settings.teajoin_token, base_url=settings.teajoin_base_url)


@data_app.command("rebuild")
def data_rebuild(start: str = "20000104", end: str | None = None, resume: bool = True) -> None:
    """teajoin 全量重建平台数据（断点续传）。"""
    if not settings.teajoin_token:
        console.print("错误: 未配置 FACTORLAB_TEAJOIN_TOKEN（.env）")
        raise typer.Exit(code=1)
    report = rebuild_all(_db(), _client(), scope=RebuildScope(start=start, end=end), resume=resume)
    console.print(f"rebuild 完成: {report['tables']}")


@data_app.command("refresh")
def data_refresh() -> None:
    """增量拉取到最新交易日。"""
    report = refresh(_db(), _client())
    console.print(f"refresh 完成: {report}")


@data_app.command("verify")
def data_verify(compare: Path | None = None) -> None:
    """完整性自检 + 稀疏摘要 + 可选对拍。"""
    report = verify_all(_db(), ref_db=compare)
    console.print(report)
```

**注意**：`data verify` 用的是最终库 `factorlab.duckdb`；rebuild 写暂存库并重建最终库。`rebuild_all` 的调用处需确认最终库路径语义——**实现时在 `data_rebuild` 里用 staging 库调用 rebuild_all，然后 build_final_db 到 factorlab.duckdb**（两个库路径都要显式）。计划允许实现时按此细化。

**Step 4: 文档更新**（`docs/interface.md` 追加）：

```markdown
## 6. 数据平台（M3b）

### `factorlab.data.fetcher.TeaJoinClient`

teajoin Tushare 兼容代理客户端：`fetch(api_name, params, fields=None) -> pl.DataFrame`
（全局限流 0.2s、指数退避重试 3 次、4xx 抛 `TeaJoinError`）；`fetch_paged(...)` 通用分页。
token 来自 `FACTORLAB_TEAJOIN_TOKEN`；端点 `https://teajoin.com`（根路径）。

### `factorlab.data.platform_db.PlatformDB`

平台数据库（duckdb）：`upsert(table, df, keys)` 自动建表 + 去重；`integrity_check()`
自检规则（日历缺日/重复/pct_chg 自洽/adj_factor 有效/stk_limit 边界/市值有效）。
**列名沿用 tushare 原始命名**（`trade_date`/`ts_code`）。

### `factorlab.data.rebuild` / `refresh` / `verify`

- `rebuild_all(db, client, scope, resume=True)`：manifest 断点续传编排（交易日历 → 静态 →
  行情 7 表按日 → 财报按报告期 → 指数）；`assess_sparsity`/`build_final_db`：稀疏字段
  （null_ratio>20% 或 stock_coverage<80%）物理剔除后重建最终库。
- `refresh(db, client)`：从 manifest.last_updated 增量续拉。
- `verify_all(db, ref_db=None)`：完整性 + 稀疏摘要 + 抽样对拍（30 只 × 三段 × 容差 0.01%）。

### `factorlab.data.adjust`（复权能力层）

- `view_prices(df, view, asof=None)`：`raw|qfq|hfq|pit_qfq` 价格视图（输入含 `adj_factor` 列）。
- `total_return(close, adj)`：含分红再投资收益（HFQ 收益）。
- `lookahead_check(factor_fn, df, asof)` / `scale_invariance_check(factor_fn, df)` /
  `adjustment_sensitivity_check(factor_fn, df)`：未来信息泄漏、价格尺度不变性、
  复权敏感性审计。`factor_fn: Callable[[pl.DataFrame], pl.DataFrame]`（价格面板 → date/code/signal）。

### CLI

`factorlab data rebuild|refresh|verify`。
```

**Step 5: 全量验证**

Run: `python -m pytest -q`
Expected: 全部 PASS（集成测试在 token 配置时运行真实 API 小拉取）。

- [ ] **Step 6: Commit**

```bash
git add src/factorlab/cli/main.py docs/interface.md tests/test_cli_data.py tests/test_e2e_data.py
git commit -m "docs: document M3b data platform APIs; add data CLI and e2e tests"
```

---

## Self-Review

**1. Spec coverage（对照 M3b spec）：**
- §2 数据范围（13 表）→ Task 5（行情 7 表/财报/指数）+ Task 8（增量）✓；index_weight 按季度在 Task 5 备注 ✓
- §2.1 稀疏治理（20%/80% 物理剔除）→ Task 6 ✓
- §3.1 TeaJoinClient → Task 1 ✓；§3.2 PlatformDB → Task 2 ✓；§3.3 rebuild → Task 5 ✓；
  §3.4 refresh → Task 8 ✓；§3.5 复权能力层 → Task 3/4 ✓；§4 验证 → Task 2（integrity）+ Task 7 ✓；
- §5 错误处理 → Task 1（重试/4xx）+ Task 5（failed 记录）✓
- §6 测试 → 各任务单测 + Task 9 集成 ✓
- §7 明确不做 → 计划不含 ✓
- **缺口**：spec 3.3 的 index_weight 按月拉取在计划中只给了季度简化说明——Task 5 实现时以月度最后交易日拉取为准（实现注记已含）；`FactorSpec.adjustment` 字段声明在 spec 3.5 配套中——M4 消费，M3b 不实现（spec 明确）✓

**2. Placeholder scan：** 无 TBD/TODO；Task 3 的 pit_qfq 实现给了两种写法（以测试通过为准）——可接受（均为完整代码）；Task 9 的 CLI 库路径语义给了实现注记 ✓

**3. Type consistency：** `TeaJoinClient.fetch(api_name, params, fields=None)`、`PlatformDB.upsert(table, df, keys)`、
`view_prices(df, view, asof=None)`、`factor_fn: Callable[[pl.DataFrame], pl.DataFrame]`、
`rebuild_all(db, client, scope, resume, manifest_path)`、`assess_sparsity(db)`、`build_final_db(staging, final_path, ...)`、
`verify_all(db, ref_db=None)`、`compare_sample(primary, ref_path, ...)`、`refresh(db, client, manifest_path)` 在任务间一致 ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-16-factorlab-m3b-data-platform.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks.
2. Inline Execution - execute tasks in this session using executing-plans with checkpoints.

Which approach?
