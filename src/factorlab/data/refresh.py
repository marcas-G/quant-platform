from __future__ import annotations

import datetime
from pathlib import Path

import polars as pl

from factorlab.config import settings
from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import DAILY_TABLES, load_manifest, save_manifest


def refresh(db: PlatformDB, client: TeaJoinClient, manifest_path: Path | None = None) -> dict:
    """增量续拉行情表：重试 manifest 中 failed 日期，并从 last_updated 续拉到最新交易日。

    起始日期取最早 failed 日（若有）——failed 旧日期即使 ≤ last_updated 也重拉；
    单日失败记入该表 failed（与 rebuild 同语义），成功则从 failed 移除。
    """
    manifest_path = manifest_path or (settings.data_dir / "manifest.json")
    manifest = load_manifest(manifest_path)
    last = manifest.get("last_updated")
    if not last:
        raise ValueError("manifest 无 last_updated，请先 rebuild")

    # 重试窗口：起始取最早的 failed 日（若早于 last_updated 也要覆盖到）
    failed_all = [d for t in DAILY_TABLES for d in manifest.get(t, {}).get("failed", [])]
    start_from = min(failed_all) if failed_all else last

    today = datetime.date.today().strftime("%Y%m%d")
    cal = client.fetch("trade_cal", {"exchange": "SSE", "start_date": start_from, "end_date": today})
    new_dates = sorted(d for d in cal.filter(pl.col("is_open") == 1)["cal_date"].to_list()
                       if d > last or d in failed_all)
    if not new_dates:
        return {"new_dates": [], "tables": {}}

    report: dict = {"new_dates": new_dates, "tables": {}}
    for table in DAILY_TABLES:
        completed = set(manifest.get(table, {}).get("completed", []))
        failed = set(manifest.get(table, {}).get("failed", []))
        rows = 0
        for d in new_dates:
            try:
                df = client.fetch(table, {"trade_date": d})
                db.upsert(table, df, keys=["trade_date", "ts_code"])  # 默认 dedup=True（refresh 可能重拉）
                completed.add(d)
                failed.discard(d)
                rows += df.height
            except Exception:
                failed.add(d)  # 失败日记入 failed，下次 refresh 重试
        manifest.setdefault(table, {})["completed"] = sorted(completed)
        manifest.setdefault(table, {})["failed"] = sorted(failed)
        report["tables"][table] = {"rows": rows, "failed": sorted(failed)}
    manifest["last_updated"] = new_dates[-1]  # failed 日也算已处理，推进避免重复拉
    save_manifest(manifest_path, manifest)
    return report
