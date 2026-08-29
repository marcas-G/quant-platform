"""M6-07B：stock_basic 显式字段 fetch + targeted migration（delist_date PIT 修复）。"""

import polars as pl
import pytest

from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import (STOCK_BASIC_FIELDS, fetch_stock_basic_all,
                                    migrate_stock_basic_pit_fields)


class _FakeClient:
    """模拟 TeaJoin stock_basic（记录 fields 请求；L/D 可配置返回）。"""

    def __init__(self, l_df, d_df=None):
        self.l_df = l_df
        self.d_df = d_df if d_df is not None else pl.DataFrame()
        self.fields_seen = []

    def fetch_paged(self, api_name, params, fields=None):
        assert api_name == "stock_basic"
        self.fields_seen.append(list(fields or []))
        df = self.l_df if params.get("list_status") == "L" else self.d_df
        if df.height and "delist_date" in df.columns:
            df = df.with_columns(pl.col("delist_date").cast(pl.String))
        return df


def _l_row(**over):
    base = {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行",
            "list_status": "L", "list_date": "19910403", "delist_date": None,
            "industry": "银行", "market": "主板", "act_name": None,
            "act_ent_type": None, "area": "深圳", "cnspell": "PAYH"}
    base.update(over)
    return base


# ================================================================
# fetch_stock_basic_all
# ================================================================

def test_fetch_requests_explicit_fields():
    client = _FakeClient(pl.DataFrame([_l_row()]))
    out = fetch_stock_basic_all(client)
    assert out.height == 1
    for fields in client.fields_seen:
        assert "delist_date" in fields and "list_status" in fields and "list_date" in fields


def test_fetch_merges_l_and_d():
    client = _FakeClient(
        pl.DataFrame([_l_row(), _l_row(ts_code="600000.SH", symbol="600000")]),
        pl.DataFrame([_l_row(ts_code="600001.SH", symbol="600001", list_status="D",
                             delist_date="20240601")]))
    out = fetch_stock_basic_all(client)
    assert out.height == 3
    assert out["ts_code"].n_unique() == 3


def test_fetch_d_without_delist_date_fails():
    client = _FakeClient(
        pl.DataFrame([_l_row()]),
        pl.DataFrame([_l_row(ts_code="600001.SH", symbol="600001", list_status="D",
                             delist_date=None)]))
    with pytest.raises(ValueError, match="delist_date 为空"):
        fetch_stock_basic_all(client)


def test_fetch_duplicate_ts_code_fails():
    client = _FakeClient(pl.DataFrame([_l_row(), _l_row()]))   # L/D 返回同一表
    with pytest.raises(ValueError, match="重复"):
        fetch_stock_basic_all(client)


def test_fetch_missing_required_field_fails():
    client = _FakeClient(pl.DataFrame([{"ts_code": "A.SZ"}]))
    with pytest.raises(ValueError, match="缺少字段"):
        fetch_stock_basic_all(client)


def test_fetch_empty_returns_empty():
    client = _FakeClient(pl.DataFrame())
    assert fetch_stock_basic_all(client).height == 0


# ================================================================
# migrate_stock_basic_pit_fields
# ================================================================

def _db(tmp_path):
    db = PlatformDB(tmp_path / "t.duckdb")
    db.upsert("stock_basic", pl.DataFrame({
        "ts_code": ["000001.SZ", "600000.SH"],
        "symbol": ["000001", "600000"],
        "name": ["甲", "乙"],
        "industry": ["银行", "银行"],
        "list_date": ["19910403", "20010827"],
        "act_name": ["A", "B"],
    }), keys=["ts_code"])
    return db


def test_migration_preserves_existing_columns(tmp_path):
    db = _db(tmp_path)
    fetched = pl.DataFrame([_l_row(), _l_row(ts_code="600000.SH", symbol="600000",
                                             name="乙", industry="银行",
                                             list_date="20010827", act_name="B")])
    migrate_stock_basic_pit_fields(db, fetched)
    cols = db.describe("stock_basic")
    for c in ("ts_code", "symbol", "name", "industry", "list_date", "act_name", "delist_date"):
        assert c in cols, f"迁移后列丢失: {c}"
    rows = db.query("SELECT COUNT(*) FROM stock_basic")[0, 0]
    distinct = db.query("SELECT COUNT(DISTINCT ts_code) FROM stock_basic")[0, 0]
    assert rows == distinct == 2
    assert "delist_date" in cols


def test_migration_idempotent(tmp_path):
    db = _db(tmp_path)
    fetched = pl.DataFrame([_l_row(), _l_row(ts_code="600000.SH", symbol="600000",
                                             name="乙", industry="银行",
                                             list_date="20010827", act_name="B")])
    migrate_stock_basic_pit_fields(db, fetched)
    r1 = db.query("SELECT COUNT(*) FROM stock_basic")[0, 0]
    migrate_stock_basic_pit_fields(db, fetched)
    r2 = db.query("SELECT COUNT(*) FROM stock_basic")[0, 0]
    assert r1 == r2 == 2                      # 不增加行
    assert db.query("SELECT COUNT(DISTINCT ts_code) FROM stock_basic")[0, 0] == 2


def test_migration_adds_delist_date_when_missing(tmp_path):
    db = _db(tmp_path)
    assert "delist_date" not in db.describe("stock_basic")
    fetched = pl.DataFrame([_l_row()])
    migrate_stock_basic_pit_fields(db, fetched)
    assert "delist_date" in db.describe("stock_basic")
    assert db.query("SELECT COUNT(*) FROM stock_basic WHERE delist_date IS NULL")[0, 0] == 2
