from __future__ import annotations

from pathlib import Path
from typing import Callable

import duckdb
import polars as pl


class PlatformDB:
    """平台数据库（duckdb）：自动建表、按 keys upsert 去重、完整性自检。

    列名沿用 tushare API 原始命名（trade_date/ts_code），与 API 零转换；
    M4 引擎接入时再映射到平台列名（date/code）。
    批量写入（rebuild/refresh）用 connect() 复用连接 + upsert_on()，避免每批重开连接。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path), read_only=read_only)

    def connect(self) -> duckdb.DuckDBPyConnection:
        """打开写连接；rebuild/refresh 批量场景复用，调用方负责 close（或 with）。"""
        return self._connect()

    def query(self, sql: str, params: list | None = None) -> pl.DataFrame:
        """执行 SQL 返回 polars DataFrame；params 为 ? 位置参数绑定。"""
        with self._connect(read_only=True) as con:
            return con.execute(sql, params or []).pl()

    def upsert(self, table: str, df: pl.DataFrame, keys: list[str]) -> None:
        """插入或替换：按 keys 去重（先删后插）；表不存在时按 df schema 自动建表。

        keys 为空时普通 INSERT（保留重复行，供 duplicate 检测）；空 df 为 no-op。
        建表与插入在同一事务内，失败整体回滚并抛出带 table/keys 上下文的错误。
        """
        if df.height == 0:
            return
        with self.connect() as con:
            self.upsert_on(con, table, df, keys)

    def upsert_on(
        self,
        con: duckdb.DuckDBPyConnection,
        table: str,
        df: pl.DataFrame,
        keys: list[str],
        dedup: bool = True,
    ) -> None:
        """在给定连接上 upsert（与 upsert() 同语义，复用连接；调用方负责 close）。

        dedup=True 按 keys 先删后插（默认）；dedup=False 纯 INSERT——调用方保证批内
        无重复（如 rebuild 单日批按 trade_date 唯一），省去全表扫描 DELETE。
        空 df 为 no-op；失败回滚并抛出带 table/keys 上下文的错误，连接仍可继续使用。
        """
        if df.height == 0:
            return
        try:
            con.execute("BEGIN TRANSACTION")
            exists = con.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_name = ?",
                [table],
            ).fetchone()
            con.register("df", df.to_arrow())
            if not exists:
                con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM df LIMIT 0')
            cols = ", ".join(f'"{c}"' for c in df.columns)
            if keys and dedup:
                key_cols = ", ".join(f'"{k}"' for k in keys)
                con.execute(
                    f'DELETE FROM "{table}" WHERE ({key_cols}) IN (SELECT {key_cols} FROM df)'
                )
            con.execute(f'INSERT INTO "{table}" ({cols}) SELECT {cols} FROM df')
            con.execute("COMMIT")
        except duckdb.Error as exc:
            try:
                con.execute("ROLLBACK")
            except duckdb.Error:
                pass
            raise ValueError(f"upsert {table} 失败（keys={keys}）: {exc}") from exc

    def list_tables(self) -> list[str]:
        if not self.path.exists():
            return []
        with self._connect(read_only=True) as con:
            rows = con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
        return [r[0] for r in rows]

    def describe(self, table: str) -> list[str]:
        with self._connect(read_only=True) as con:
            rows = con.execute(f'DESCRIBE "{table}"').fetchall()
        return [r[0] for r in rows]

    def _rules(self) -> list[tuple[str, str, tuple[str, ...], Callable[[dict], None]]]:
        """(rule_name, 报告键, 依赖表, 检查函数)；任一依赖表缺失则跳过。"""
        return [
            ("calendar_gaps", "daily", ("trade_cal", "daily"), self._check_calendar_gaps),
            ("duplicate_rows", "daily", ("daily",), self._check_duplicates),
            ("pct_chg_consistency", "daily", ("daily",), self._check_pct_chg),
            ("adj_factor_valid", "adj_factor", ("adj_factor",), self._check_adj_factor),
            ("stk_limit_boundary", "daily", ("daily", "stk_limit"), self._check_stk_limit),
            ("market_cap_valid", "daily_basic", ("daily_basic",), self._check_market_cap),
        ]

    def integrity_check(self) -> dict[str, dict]:
        """完整性自检：每规则 {passed, failed, details, skipped}；缺依赖表或结构不匹配时 skipped=True。

        规则：日历缺日/重复行/pct_chg 自洽/adj_factor 有效/stk_limit 边界/市值有效。
        """
        tables = set(self.list_tables())
        report: dict[str, dict] = {}
        for rule_name, report_key, deps, fn in self._rules():
            entry = {"passed": True, "failed": 0, "details": [], "skipped": False}
            missing = [d for d in deps if d not in tables]
            if missing:
                entry["skipped"] = True
                entry["details"] = [f"依赖表 {'、'.join(missing)} 不存在，跳过"]
                report.setdefault(report_key, {})[rule_name] = entry
                continue
            try:
                fn(entry)
            except duckdb.Error:
                entry["skipped"] = True
                entry["details"] = [f"{rule_name} 检查失败（表结构或数据不兼容），跳过"]
            report.setdefault(report_key, {})[rule_name] = entry
        return report

    def _check_calendar_gaps(self, entry: dict) -> None:
        """日历缺日：trade_cal 开盘日不在 daily 的日期即为缺日。"""
        with self._connect(read_only=True) as con:
            rows = con.execute("""
                SELECT DISTINCT c.cal_date FROM trade_cal c
                WHERE c.is_open = 1 AND c.cal_date NOT IN (SELECT DISTINCT trade_date FROM daily)
            """).fetchall()
        entry["failed"] = len(rows)
        entry["passed"] = len(rows) == 0
        entry["details"] = [r[0] for r in rows[:20]]

    def _check_duplicates(self, entry: dict) -> None:
        """重复行：同一 (trade_date, ts_code) 出现多次的组数。"""
        with self._connect(read_only=True) as con:
            n = con.execute("""
                SELECT count(*) FROM (
                    SELECT trade_date, ts_code, count(*) c FROM daily GROUP BY 1, 2 HAVING c > 1
                )
            """).fetchone()[0]
        entry["failed"] = n
        entry["passed"] = n == 0
        entry["details"] = [f"{n} 个 (trade_date, ts_code) 重复"] if n else []

    def _check_pct_chg(self, entry: dict) -> None:
        """pct_chg 自洽：close 环比（前收口径）与 pct_chg 误差 ≤ 0.01%。"""
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
        """adj_factor 有效：必须 > 0。"""
        with self._connect(read_only=True) as con:
            n = con.execute("SELECT count(*) FROM adj_factor WHERE adj_factor <= 0").fetchone()[0]
        entry["failed"] = n
        entry["passed"] = n == 0
        entry["details"] = [f"{n} 行 adj_factor <= 0"] if n else []

    def _check_stk_limit(self, entry: dict) -> None:
        """stk_limit 边界：close 不超当日涨跌停价（±0.01% 容差）。"""
        with self._connect(read_only=True) as con:
            n = con.execute("""
                SELECT count(*) FROM daily d
                JOIN stk_limit s ON d.trade_date = s.trade_date AND d.ts_code = s.ts_code
                WHERE d.close > s.up_limit * 1.0001 OR d.close < s.down_limit * 0.9999
            """).fetchone()[0]
        entry["failed"] = n
        entry["passed"] = n == 0
        entry["details"] = [f"{n} 行 close 超涨跌停边界"] if n else []

    def _check_market_cap(self, entry: dict) -> None:
        """市值有效：total_mv 必须 > 0。"""
        with self._connect(read_only=True) as con:
            n = con.execute("SELECT count(*) FROM daily_basic WHERE total_mv <= 0").fetchone()[0]
        entry["failed"] = n
        entry["passed"] = n == 0
        entry["details"] = [f"{n} 行 total_mv <= 0"] if n else []
