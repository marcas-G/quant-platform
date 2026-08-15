from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl

from factorlab.config import settings
from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB

DAILY_TABLES = ("daily", "daily_basic", "adj_factor", "stock_st", "stk_limit", "suspend_d", "moneyflow")
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


def _quarter_ends(year: int) -> list[str]:
    return [f"{year}0331", f"{year}0630", f"{year}0930", f"{year}1231"]


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
    """全量重建编排：交易日历 → 静态表 → 行情 7 表按日 → 财报按报告期 → 指数。

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

    # 4. 财报按报告期（每季末拉全市场；无数据期空返回正常，单期失败不阻塞）
    years = range(int(scope.start[:4]), int((scope.end or DEFAULT_END)[:4]) + 1)
    report_dates = [d for y in years for d in _quarter_ends(y)]
    for table in FINANCIAL_TABLES:
        fetched: list[str] = []
        failed: list[str] = []
        for rd in report_dates:
            try:
                df = client.fetch(table, {"report_date": rd})
                if df.height:
                    db.upsert(table, df, keys=["ts_code", "report_date"])
                    fetched.append(rd)
            except Exception:
                failed.append(rd)
        report["tables"][table] = {
            "report_dates": fetched, "failed": failed, "rows": _table_rows(db, table),
        }

    # 5. 指数：index_daily 全历史 + index_weight 每月最后一个交易日
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
                w = client.fetch("index_weight", {"ts_code": code, "trade_date": d})
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
