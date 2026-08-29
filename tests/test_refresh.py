import polars as pl
import pytest

from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import RebuildScope, load_manifest, rebuild_all, save_manifest
from factorlab.data.refresh import refresh


def _sb_l():
    return pl.DataFrame({
        "ts_code": ["000001.SZ"], "symbol": ["000001"], "name": ["甲"], "list_status": ["L"],
        "list_date": ["20240101"], "delist_date": [None], "industry": [None],
        "market": [None], "act_name": [None], "act_ent_type": [None],
        "area": [None], "cnspell": [None]})


def _sb_d():
    return pl.DataFrame({
        "ts_code": ["600001.SH"], "symbol": ["600001"], "name": ["丁"], "list_status": ["D"],
        "list_date": ["20200101"], "delist_date": ["20240601"], "industry": [None],
        "market": [None], "act_name": [None], "act_ent_type": [None],
        "area": [None], "cnspell": [None]})


def _client(monkeypatch, table_df: pl.DataFrame, fail_dates: set[str] | None = None) -> TeaJoinClient:
    client = TeaJoinClient(token="t", interval=0.0)

    def responder(api_name, params, fields=None):
        if api_name == "stock_basic":
            return _sb_l() if params.get("list_status") == "L" else _sb_d()
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


def test_refresh_after_rebuild_no_deadlock(tmp_path, monkeypatch):
    """rebuild 截断未来公告日后 last_updated=最近交易日（< today），refresh 正常续拉新日。
    回归：旧版 last_updated 可能是未来日（trade_cal 返回未来公告日），refresh 从此
    日拉到 today 无新日、永远不推进——死锁。"""
    db = PlatformDB(tmp_path / "p.duckdb")
    manifest_path = tmp_path / "manifest.json"
    # 先 rebuild：trade_cal 含未来公告日 20991231
    tables = {
        ("trade_cal", ""): pl.DataFrame({
            "exchange": ["SSE", "SSE", "SSE"],
            "cal_date": ["20240102", "20240103", "20991231"],
            "is_open": [1, 1, 1],
        }),
        ("stock_basic", ""): pl.DataFrame({
            "ts_code": ["000001.SZ", "600001.SH"], "symbol": ["000001", "600001"], "name": ["甲", "丁"],
            "list_status": ["L", "D"], "list_date": ["20240101", "20200101"],
            "delist_date": [None, "20240601"], "industry": [None, None],
            "market": [None, None], "act_name": [None, None], "act_ent_type": [None, None],
            "area": [None, None], "cnspell": [None, None]}),
        ("daily", "20240102"): pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A.SZ"], "close": [10.0]}),
        ("daily", "20240103"): pl.DataFrame({"trade_date": ["20240103"], "ts_code": ["A.SZ"], "close": [11.0]}),
    }
    rebuild_client = TeaJoinClient(token="t", interval=0.0)

    def responder(api_name, params, fields=None):
        if api_name == "stock_basic":
            return _sb_l() if params.get("list_status") == "L" else _sb_d()
        if api_name == "stock_basic" and params.get("list_status") == "D":
            return tables.get(("stock_basic", ""))
        key = params.get("trade_date") or params.get("cal_date") or ""
        df = tables.get((api_name, key))
        return df if df is not None else pl.DataFrame()

    monkeypatch.setattr(rebuild_client, "fetch", responder)
    monkeypatch.setattr(rebuild_client, "fetch_paged", responder)
    rebuild_all(db, rebuild_client, scope=RebuildScope(start="20240102", end="20240103"),
                manifest_path=manifest_path)
    assert load_manifest(manifest_path)["last_updated"] == "20240103"  # 未来日被截断

    # 再 refresh：下一个交易日正常拉取（last_updated < today，无死锁）
    client = _client(monkeypatch, pl.DataFrame({
        "trade_date": ["20240104"], "ts_code": ["A.SZ"], "close": [12.0],
    }))
    report = refresh(db, client, manifest_path=manifest_path)
    assert report["new_dates"] == ["20240104"]
    assert load_manifest(manifest_path)["last_updated"] == "20240104"


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


def test_refresh_indexes_pulls_new_daily_and_month(tmp_path, monkeypatch):
    """指数增量：index_daily 从 last_updated 到 today；index_weight 补新月份。"""
    from factorlab.data.refresh import refresh_indexes
    db = PlatformDB(tmp_path / "p.duckdb")
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, {"index_weight": {"completed": ["20260731"], "failed": []},
                                  "last_updated": "20260814"})

    calls = []

    def responder(api_name, params, fields=None):
        if api_name == "stock_basic":
            return _sb_l() if params.get("list_status") == "L" else _sb_d()
        calls.append((api_name, dict(params)))
        if api_name == "trade_cal":
            return pl.DataFrame({"exchange": ["SSE", "SSE"], "cal_date": ["20260814", "20260817"], "is_open": [1, 1]})
        if api_name == "index_daily":
            return pl.DataFrame({"trade_date": [params["start_date"]], "ts_code": [params["ts_code"]], "close": [100.0]})
        if api_name == "index_weight":
            return pl.DataFrame({"trade_date": [params["trade_date"]], "index_code": [params["index_code"]], "weight": [1.0]})
        return pl.DataFrame()

    client = TeaJoinClient(token="t", interval=0.0)
    monkeypatch.setattr(client, "fetch", responder)

    report = refresh_indexes(db, client, manifest_path=manifest_path)
    assert report["index_daily"]["rows"] > 0
    assert "index_weight" in report
    # index_weight 的 completed 应含新月份
    manifest = load_manifest(manifest_path)
    assert len(manifest["index_weight"]["completed"]) >= 1
