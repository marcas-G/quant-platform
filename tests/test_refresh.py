import polars as pl
import pytest

from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import load_manifest, save_manifest
from factorlab.data.refresh import refresh


def _client(monkeypatch, table_df: pl.DataFrame, fail_dates: set[str] | None = None) -> TeaJoinClient:
    client = TeaJoinClient(token="t", interval=0.0)

    def responder(api_name, params, fields=None):
        if api_name == "trade_cal":
            return pl.DataFrame({"exchange": ["SSE", "SSE"], "cal_date": ["20240103", "20240104"], "is_open": [1, 1]})
        if api_name == "daily":
            if fail_dates and params.get("trade_date") in fail_dates:
                raise RuntimeError(f"daily {params['trade_date']} 拉取失败")
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


def test_refresh_requires_last_updated(tmp_path, monkeypatch):
    """错误路径：manifest 无 last_updated（未 rebuild）时报错，不拉取、不改写 manifest。"""
    db = PlatformDB(tmp_path / "p.duckdb")
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"daily": {"completed": ["20240102"], "failed": []}})
    client = _client(monkeypatch, pl.DataFrame({
        "trade_date": ["20240104"], "ts_code": ["A.SZ"], "close": [12.0],
    }))
    with pytest.raises(ValueError, match="last_updated"):
        refresh(db, client, manifest_path=manifest_path)
    assert db.list_tables() == []
    assert load_manifest(manifest_path) == {"daily": {"completed": ["20240102"], "failed": []}}


def test_refresh_upsert_dedup_replaces_existing(tmp_path, monkeypatch):
    """崩溃窗口：重拉已存在日期时按 (trade_date, ts_code) 去重替换，不产生重复行。"""
    db = PlatformDB(tmp_path / "p.duckdb")
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"last_updated": "20240103"})
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240104"], "ts_code": ["A.SZ"], "close": [11.0],
    }), keys=["trade_date", "ts_code"])  # 模拟上次已拉过 20240104（旧值）
    client = _client(monkeypatch, pl.DataFrame({
        "trade_date": ["20240104"], "ts_code": ["A.SZ"], "close": [12.0],
    }))
    report = refresh(db, client, manifest_path=manifest_path)
    assert report["new_dates"] == ["20240104"]
    assert db.query("SELECT count(*) AS n FROM daily")["n"][0] == 1  # 去重：仍为 1 行
    assert db.query("SELECT close FROM daily")["close"][0] == 12.0   # 旧行被替换


def test_refresh_retries_failed_dates(tmp_path, monkeypatch):
    """failed 日期重试：manifest 中 failed 日（即使 ≤ last_updated）被重拉，成功后移出 failed。"""
    db = PlatformDB(tmp_path / "p.duckdb")
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"daily": {"completed": ["20240102"], "failed": ["20240103"]},
                                  "last_updated": "20240103"})
    client = _client(monkeypatch, pl.DataFrame({
        "trade_date": ["20240103"], "ts_code": ["A.SZ"], "close": [12.0],
    }))
    report = refresh(db, client, manifest_path=manifest_path)
    assert report["new_dates"] == ["20240103", "20240104"]  # failed 日重试 + 新日
    manifest = load_manifest(manifest_path)
    assert manifest["daily"]["failed"] == []               # 重试成功后移除
    assert "20240103" in manifest["daily"]["completed"]
    assert manifest["last_updated"] == "20240104"


def test_refresh_records_failed(tmp_path, monkeypatch):
    """失败记录：单日拉取异常记入 manifest failed，不阻塞其他日期；last_updated 仍推进。"""
    db = PlatformDB(tmp_path / "p.duckdb")
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"last_updated": "20240103"})
    client = _client(monkeypatch, pl.DataFrame({
        "trade_date": ["20240104"], "ts_code": ["A.SZ"], "close": [12.0],
    }), fail_dates={"20240104"})
    report = refresh(db, client, manifest_path=manifest_path)
    manifest = load_manifest(manifest_path)
    assert manifest["daily"]["failed"] == ["20240104"]     # 失败日被记录
    assert "20240104" not in manifest["daily"]["completed"]
    assert report["tables"]["daily"]["failed"] == ["20240104"]
    assert manifest["last_updated"] == "20240104"          # 已处理范围末端，推进避免重复拉
