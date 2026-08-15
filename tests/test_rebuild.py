from pathlib import Path

import polars as pl
import pytest

from factorlab.config import Settings
from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import INDEX_CODES, RebuildScope, load_manifest, rebuild_all, save_manifest


def _fake_client(monkeypatch, tables, fail=None, calls=None) -> TeaJoinClient:
    """fake client：按 (api_name, 日期参数) 精确匹配返回；未注册接口返回空 DataFrame。

    fail 为接口名集合，命中即抛错（模拟拉取失败）；calls 收集 (api_name, params)。
    rebuild 同时使用 client.fetch（行情/日历/指数）与 fetch_paged（stock_basic），都替换。
    """
    client = TeaJoinClient(token="t", interval=0.0)

    def responder(api_name, params, fields=None):
        if calls is not None:
            calls.append((api_name, dict(params)))
        if fail and api_name in fail:
            raise RuntimeError(f"{api_name} 拉取失败")
        key = params.get("trade_date") or params.get("report_date") or params.get("cal_date") or ""
        df = tables.get((api_name, key))
        if df is None:
            df = tables.get((api_name, ""))
        return df if df is not None else pl.DataFrame()

    monkeypatch.setattr(client, "fetch", responder)
    monkeypatch.setattr(client, "fetch_paged", responder)
    return client


def _tables():
    return {
        ("trade_cal", ""): pl.DataFrame({
            "exchange": ["SSE", "SSE"],
            "cal_date": ["20240102", "20240103"],
            "is_open": [1, 1],
        }),
        ("stock_basic", ""): pl.DataFrame({"ts_code": ["A.SZ"], "symbol": ["A"], "name": ["甲"]}),
        ("daily", "20240102"): pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A.SZ"], "close": [10.0]}),
        ("daily", "20240103"): pl.DataFrame({"trade_date": ["20240103"], "ts_code": ["A.SZ"], "close": [11.0]}),
        ("daily_basic", "20240102"): pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A.SZ"], "total_mv": [100.0]}),
        ("daily_basic", "20240103"): pl.DataFrame({"trade_date": ["20240103"], "ts_code": ["A.SZ"], "total_mv": [110.0]}),
        ("adj_factor", "20240102"): pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A.SZ"], "adj_factor": [1.0]}),
        ("adj_factor", "20240103"): pl.DataFrame({"trade_date": ["20240103"], "ts_code": ["A.SZ"], "adj_factor": [1.0]}),
    }


def test_manifest_roundtrip(tmp_path):
    path = tmp_path / "nested" / "manifest.json"
    save_manifest(path, {"daily": {"completed": ["20240102"]}})
    assert load_manifest(path) == {"daily": {"completed": ["20240102"]}}


def test_manifest_missing_defaults(tmp_path):
    assert load_manifest(tmp_path / "nope.json") == {}


def test_rebuild_all_populates_tables(tmp_path, monkeypatch):
    db = PlatformDB(tmp_path / "staging.duckdb")
    client = _fake_client(monkeypatch, _tables())
    report = rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240103"),
                         manifest_path=tmp_path / "manifest.json")
    assert set(db.list_tables()) >= {"trade_cal", "stock_basic", "daily", "daily_basic", "adj_factor"}
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
    manifest = load_manifest(manifest_path)
    assert manifest["daily"]["completed"] == ["20240102", "20240103"]
    assert manifest["last_updated"] == "20240103"


def test_rebuild_requires_token():
    settings = Settings(teajoin_token="")
    with pytest.raises(ValueError, match="token"):
        rebuild_all(PlatformDB(Path("x.duckdb")), TeaJoinClient(token=settings.teajoin_token),
                    scope=RebuildScope(), manifest_path=None)


def test_rebuild_empty_calendar_raises(tmp_path, monkeypatch):
    db = PlatformDB(tmp_path / "staging.duckdb")
    client = _fake_client(monkeypatch, {})
    with pytest.raises(ValueError, match="无交易日"):
        rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240103"),
                    manifest_path=tmp_path / "manifest.json")
    assert db.list_tables() == []


def test_rebuild_stock_basic_empty_is_ok(tmp_path, monkeypatch):
    db = PlatformDB(tmp_path / "staging.duckdb")
    tables = {("trade_cal", ""): _tables()[("trade_cal", "")],
              ("daily", "20240102"): _tables()[("daily", "20240102")]}
    client = _fake_client(monkeypatch, tables)
    rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240103"),
                manifest_path=tmp_path / "manifest.json")
    assert "stock_basic" not in db.list_tables()  # 空返回不建表、不阻塞
    assert db.query("SELECT count(*) AS n FROM daily")["n"][0] == 1


def test_rebuild_failed_table_does_not_block_others(tmp_path, monkeypatch):
    db = PlatformDB(tmp_path / "staging.duckdb")
    manifest_path = tmp_path / "manifest.json"
    client = _fake_client(monkeypatch, _tables(), fail={"adj_factor"})
    report = rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240103"),
                         manifest_path=manifest_path)
    assert report["tables"]["daily"]["rows"] == 2          # 其他表不受影响
    assert report["tables"]["adj_factor"]["failed"] == ["20240102", "20240103"]
    assert "adj_factor" not in db.list_tables()
    assert load_manifest(manifest_path)["adj_factor"]["failed"] == ["20240102", "20240103"]


def test_rebuild_resume_retries_failed_and_removes(tmp_path, monkeypatch):
    db = PlatformDB(tmp_path / "staging.duckdb")
    client = _fake_client(monkeypatch, _tables())
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"daily": {"completed": [], "failed": ["20240102"]}})
    report = rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240103"),
                         manifest_path=manifest_path)
    assert report["tables"]["daily"]["dates_fetched"] == ["20240102", "20240103"]  # failed 日期重试
    manifest = load_manifest(manifest_path)
    assert manifest["daily"]["failed"] == []               # 重试成功后从 failed 移除
    assert manifest["daily"]["completed"] == ["20240102", "20240103"]


def test_rebuild_resume_false_ignores_manifest(tmp_path, monkeypatch):
    db = PlatformDB(tmp_path / "staging.duckdb")
    client = _fake_client(monkeypatch, _tables())
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"daily": {"completed": ["20240102", "20240103"], "failed": []}})
    report = rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240103"),
                         resume=False, manifest_path=manifest_path)
    assert report["tables"]["daily"]["dates_fetched"] == ["20240102", "20240103"]  # 全量重拉
    assert load_manifest(manifest_path)["daily"]["completed"] == ["20240102", "20240103"]


def test_index_weight_fetches_month_last_trading_day(tmp_path, monkeypatch):
    tables = {
        ("trade_cal", ""): pl.DataFrame({
            "exchange": ["SSE"] * 4,
            "cal_date": ["20240102", "20240103", "20240201", "20240202"],
            "is_open": [1, 1, 1, 1],
        }),
        ("stock_basic", ""): pl.DataFrame({"ts_code": ["A.SZ"], "symbol": ["A"], "name": ["甲"]}),
    }
    calls = []
    db = PlatformDB(tmp_path / "staging.duckdb")
    client = _fake_client(monkeypatch, tables, calls=calls)
    rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240202"),
                manifest_path=tmp_path / "manifest.json")
    iw = [params for name, params in calls if name == "index_weight"]
    assert len(iw) == 8  # 2 个月 × 4 指数，每月 1 次
    assert sorted({p["trade_date"] for p in iw}) == ["20240103", "20240202"]  # 每月最后一个交易日
    assert {p["index_code"] for p in iw} == set(INDEX_CODES)  # 真实 API 必填参数是 index_code


def test_rebuild_filters_future_cal_dates(tmp_path, monkeypatch):
    """trade_cal 返回未来公告日（真实 API 实测含未来日）时 dates 截断到 today：
    不为未来日白拉请求，last_updated 取截断后的最近交易日。"""
    tables = _tables()
    tables[("trade_cal", "")] = pl.DataFrame({
        "exchange": ["SSE", "SSE", "SSE"],
        "cal_date": ["20240102", "20240103", "20991231"],
        "is_open": [1, 1, 1],
    })
    calls = []
    db = PlatformDB(tmp_path / "staging.duckdb")
    client = _fake_client(monkeypatch, tables, calls=calls)
    rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240103"),
                manifest_path=tmp_path / "manifest.json")
    daily_dates = {p["trade_date"] for name, p in calls if name == "daily"}
    assert "20991231" not in daily_dates          # 未来日不拉
    assert load_manifest(tmp_path / "manifest.json")["last_updated"] == "20240103"  # 截断后最近交易日


def test_rebuild_default_manifest_path_uses_data_dir(tmp_path, monkeypatch):
    from factorlab.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db = PlatformDB(tmp_path / "staging.duckdb")
    client = _fake_client(monkeypatch, _tables())
    rebuild_all(db, client, scope=RebuildScope(start="20240102", end="20240103"))
    assert (tmp_path / "manifest.json").exists()
    assert load_manifest(tmp_path / "manifest.json")["last_updated"] == "20240103"
