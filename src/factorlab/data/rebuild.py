from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl

from factorlab.config import settings
from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB

DAILY_TABLES = ("daily", "daily_basic", "adj_factor", "stock_st", "stk_limit", "suspend_d", "moneyflow")
# M3b+ 按 ts_code 分批拉取（真实 API 强制 ts_code，全市场按报告期不可行）
FINANCIAL_TABLES = ("income", "balancesheet", "cashflow")
INDEX_CODES = ("000300.SH", "000905.SH", "000852.SH", "000016.SH")
DEFAULT_END = "20261231"


def load_manifest(path: Path) -> dict:
    """读取断点续传 manifest；文件不存在时返回空 dict。"""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, manifest: dict) -> None:
    """落盘 manifest（每批调用，供中断后断点续传）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class RebuildScope:
    start: str = "20000104"
    end: str | None = None


def _month_last_trading_days(dates: list[str]) -> list[str]:
    """每月最后一个交易日（dates 为升序交易日列表，按 YYYYMM 分组取末位）。"""
    result: list[str] = []
    for d in dates:
        if result and d[:6] == result[-1][:6]:
            result[-1] = d
        else:
            result.append(d)
    return result


def _table_rows(db: PlatformDB, table: str) -> int:
    if table not in db.list_tables():
        return 0
    return db.query(f'SELECT count(*) AS n FROM "{table}"')["n"][0]


def _rebuild_daily_table(
    db: PlatformDB,
    con: duckdb.DuckDBPyConnection,
    client: TeaJoinClient,
    table: str,
    dates: list[str],
    manifest: dict,
    manifest_path: Path,
) -> dict:
    """按交易日拉取单张行情表：跳过 completed、重试 failed、每批落盘。

    con 为复用写连接（避免每批重开 ~24ms）；单日批按 trade_date 唯一（manifest
    保证无重复），upsert 传 dedup=False 纯 INSERT，省去全表扫描 DELETE。
    client 内部已重试 3 次，此处 catch 仅记录 failed，不阻塞其他日期/表。
    """
    completed = set(manifest.get(table, {}).get("completed", []))
    failed = set(manifest.get(table, {}).get("failed", []))
    fetched: list[str] = []
    total_rows = 0
    for d in dates:
        if d in completed:
            continue
        try:
            df = client.fetch(table, {"trade_date": d})
            db.upsert_on(con, table, df, keys=["trade_date", "ts_code"], dedup=False)
            completed.add(d)
            failed.discard(d)  # 重试成功后从 failed 移除
            fetched.append(d)
            total_rows += df.height
        except Exception:
            failed.add(d)
        manifest[table] = {"completed": sorted(completed), "failed": sorted(failed)}
        save_manifest(manifest_path, manifest)
    return {"dates_fetched": fetched, "rows": total_rows, "failed": sorted(failed)}


def rebuild_all(
    db: PlatformDB,
    client: TeaJoinClient,
    scope: RebuildScope = RebuildScope(),
    resume: bool = True,
    manifest_path: Path | None = None,
) -> dict:
    """全量重建编排：交易日历 → 静态表 → 行情 7 表按日 → 指数。

    断点续传：manifest 记录每表 completed/failed 并每批落盘；resume=True 跳过
    completed、重试 failed（成功后移除）；resume=False 忽略既有 manifest 全量重拉。
    返回 report：{"tables": {table: {...}}}，每表含 fetched/failed 与行数。
    """
    if not client.token:
        raise ValueError("teajoin token 未配置（FACTORLAB_TEAJOIN_TOKEN）")
    manifest_path = manifest_path or (settings.data_dir / "manifest.json")
    manifest = load_manifest(manifest_path)
    if not resume:
        manifest = {}

    # 1. 交易日历（重建骨架）
    cal = client.fetch("trade_cal", {"exchange": "SSE", "start_date": scope.start,
                                     "end_date": scope.end or DEFAULT_END})
    if cal.height == 0 or "is_open" not in cal.columns:
        raise ValueError("trade_cal 无交易日，检查 token/日期范围")
    cal = cal.filter(pl.col("is_open") == 1)
    dates = sorted(cal["cal_date"].to_list())
    if not dates:
        raise ValueError("trade_cal 无交易日，检查 token/日期范围")
    # trade_cal 会返回未来公告日（实测最大 20261231）：截断到 today，避免为未来日白拉请求
    today = datetime.date.today().strftime("%Y%m%d")
    dates = [d for d in dates if d <= today]
    if not dates:
        raise ValueError("trade_cal 无交易日（全部为未来公告日），检查 token/日期范围")
    db.upsert("trade_cal", cal, keys=["exchange", "cal_date"])

    # 2. 静态表（上市 L + 退市 D，分页）
    for status in ("L", "D"):
        df = client.fetch_paged("stock_basic", {"list_status": status})
        if df.height:
            db.upsert("stock_basic", df, keys=["ts_code"])

    report: dict = {"tables": {}}

    # 3. 行情 7 表按日（单连接复用，避免每批重开连接）
    with db.connect() as con:
        for table in DAILY_TABLES:
            report["tables"][table] = _rebuild_daily_table(
                db, con, client, table, dates, manifest, manifest_path
            )

    # 4. 指数：index_daily 全历史 + index_weight 每月最后一个交易日
    #    （M3b v1 不含财报三表：真实 API 强制 ts_code，全市场按报告期拉取不可行）
    index_failed: list[str] = []
    for code in INDEX_CODES:
        try:
            idx = client.fetch("index_daily", {"ts_code": code, "start_date": scope.start,
                                               "end_date": scope.end or DEFAULT_END})
            if idx.height:
                db.upsert("index_daily", idx, keys=["trade_date", "ts_code"])
        except Exception:
            index_failed.append(f"index_daily:{code}")
    report["tables"]["index_daily"] = {"rows": _table_rows(db, "index_daily"), "failed": index_failed}

    month_dates = _month_last_trading_days(dates)
    iw_completed = set(manifest.get("index_weight", {}).get("completed", []))
    iw_failed = set(manifest.get("index_weight", {}).get("failed", []))
    iw_fetched: list[str] = []
    for d in month_dates:
        if d in iw_completed:
            continue
        try:
            for code in INDEX_CODES:
                w = client.fetch("index_weight", {"index_code": code, "trade_date": d})
                if w.height:
                    db.upsert("index_weight", w, keys=["index_code", "trade_date"])
            iw_completed.add(d)
            iw_failed.discard(d)
            iw_fetched.append(d)
        except Exception:
            iw_failed.add(d)
        manifest["index_weight"] = {"completed": sorted(iw_completed), "failed": sorted(iw_failed)}
        save_manifest(manifest_path, manifest)
    report["tables"]["index_weight"] = {"month_dates": iw_fetched, "failed": sorted(iw_failed)}

    manifest["last_updated"] = dates[-1]
    save_manifest(manifest_path, manifest)
    return report


def assess_sparsity(db: PlatformDB) -> dict[str, dict[str, dict]]:
    """每表每字段稀疏度：null_ratio / stock_coverage / first_date。

    trade_cal 与键列（trade_date/cal_date/ts_code/exchange/index_code）不参与评估；
    stock_basic 等无日期列的表 first_date 为 None；空表（total=0）字段 null_ratio 记 1.0。
    """
    report: dict[str, dict[str, dict]] = {}
    for table in db.list_tables():
        if table in {"trade_cal"}:
            continue
        cols = [c for c in db.describe(table)
                if c not in {"trade_date", "cal_date", "ts_code", "exchange", "index_code"}]
        code_col = "ts_code" if "ts_code" in db.describe(table) else None
        date_col = "trade_date" if "trade_date" in db.describe(table) else "cal_date"
        total = db.query(f'SELECT count(*) AS n FROM "{table}"')["n"][0]
        table_report: dict[str, dict] = {}
        for col in cols:
            non_null = db.query(f'SELECT count(*) AS n FROM "{table}" WHERE "{col}" IS NOT NULL')["n"][0]
            null_ratio = 1.0 - (non_null / total) if total else 1.0
            stock_coverage = 1.0
            if code_col and total:
                with_stock = db.query(
                    f'SELECT count(DISTINCT "{code_col}") AS n FROM "{table}" WHERE "{col}" IS NOT NULL'
                )["n"][0]
                all_stock = db.query(f'SELECT count(DISTINCT "{code_col}") AS n FROM "{table}"')["n"][0]
                stock_coverage = with_stock / all_stock if all_stock else 1.0
            first_date = None
            if date_col in db.describe(table):
                first = db.query(
                    f'SELECT min("{date_col}") AS d FROM "{table}" WHERE "{col}" IS NOT NULL'
                )["d"][0]
                first_date = str(first) if first is not None else None
            table_report[col] = {
                "null_ratio": round(null_ratio, 4),
                "stock_coverage": round(stock_coverage, 4),
                "first_date": first_date,
            }
        report[table] = table_report
    return report


def build_final_db(
    staging: PlatformDB,
    final_path: Path,
    null_threshold: float = 0.2,
    coverage_threshold: float = 0.8,
) -> dict:
    """评估稀疏度 → 剔除超限字段 → 重建最终库（物理排除）。

    任一超限（null_ratio > null_threshold 或 stock_coverage < coverage_threshold）即剔除；
    无保留列的表跳过建表；最终库已存在时整体替换（CREATE OR REPLACE，schema 收缩生效）。
    返回 {"excluded_fields": {table: [cols]}, "tables": [最终库表]}。
    """
    if not staging.path.exists():
        raise ValueError(f"暂存库不存在: {staging.path}")
    sparsity = assess_sparsity(staging)
    excluded: dict[str, list[str]] = {}
    for table, fields in sparsity.items():
        excluded[table] = [
            col for col, m in fields.items()
            if m["null_ratio"] > null_threshold or m["stock_coverage"] < coverage_threshold
        ]
    staging_path = str(staging.path).replace("\\", "/")  # Windows 反斜杠在 ATTACH 字符串中需转义
    with duckdb.connect(str(final_path)) as con:
        con.execute(f"ATTACH '{staging_path}' AS staging (READ_ONLY)")
        for table in staging.list_tables():
            keep = [c for c in staging.describe(table) if c not in excluded.get(table, [])]
            if not keep:
                continue
            cols_sql = ", ".join(f'"{c}"' for c in keep)
            con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT {cols_sql} FROM staging."{table}"')
        con.execute("DETACH staging")
    return {"excluded_fields": excluded, "tables": PlatformDB(final_path).list_tables()}
