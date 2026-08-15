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
                db.upsert(table, df, keys=["trade_date", "ts_code"])  # 默认 dedup=True（refresh 可能重拉）
                completed.add(d)
                rows += df.height
            except Exception:
                continue  # 单日失败跳过，不阻塞其他日期/表
        manifest.setdefault(table, {})["completed"] = sorted(completed)
        report["tables"][table] = {"rows": rows}
    manifest["last_updated"] = new_dates[-1]
    save_manifest(manifest_path, manifest)
    return report
