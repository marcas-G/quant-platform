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
    client = _FakeClient(pl.DataFrame([_l_row()]),
                         pl.DataFrame([_l_row(ts_code="600001.SH", symbol="600001",
                                              list_status="D", delist_date="20240601")]))
    out = fetch_stock_basic_all(client)
    assert out.height == 2
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
    client = _FakeClient(pl.DataFrame([_l_row(), _l_row()]),   # L 内重复
                         pl.DataFrame([_l_row(ts_code="600001.SH", symbol="600001",
                                              list_status="D", delist_date="20240601")]))
    with pytest.raises(ValueError, match="重复"):
        fetch_stock_basic_all(client)


def test_fetch_bad_date_format_fails():
    client = _FakeClient(
        pl.DataFrame([_l_row()]),
        pl.DataFrame([_l_row(ts_code="600001.SH", symbol="600001", list_status="D",
                             delist_date="2024-06-01")]))   # 非 YYYYMMDD
    with pytest.raises(ValueError, match="delist_date 非合法日历日期"):
        fetch_stock_basic_all(client)


def test_fetch_missing_required_field_fails():
    client = _FakeClient(pl.DataFrame([{"ts_code": "A.SZ"}]),
                         pl.DataFrame([{"ts_code": "D.SZ", "list_status": "D"}]))
    with pytest.raises(ValueError, match="缺少字段"):
        fetch_stock_basic_all(client)


def test_fetch_l_empty_fails():
    client = _FakeClient(pl.DataFrame())
    with pytest.raises(ValueError, match="L .*返回空"):
        fetch_stock_basic_all(client)


def test_fetch_d_empty_fails():
    client = _FakeClient(pl.DataFrame([_l_row()]))
    with pytest.raises(ValueError, match="D .*返回空"):
        fetch_stock_basic_all(client)


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


# ================================================================
# M6-07B1：two-phase migration 语义
# ================================================================

def _db_full(tmp_path):
    """带非 PIT 字段的 stock_basic（name/industry 应被保留）。"""
    db = PlatformDB(tmp_path / "t.duckdb")
    db.upsert("stock_basic", pl.DataFrame({
        "ts_code": ["A.SZ"],
        "symbol": ["A"],
        "name": ["old-name"],
        "industry": ["old-industry"],
        "list_date": ["19910403"],
        "act_name": ["old-act"],
    }), keys=["ts_code"])
    return db


def _incoming():
    return pl.DataFrame([
        {"ts_code": "A.SZ", "symbol": "A", "name": "new-name", "industry": "new-industry",
         "list_status": "L", "list_date": "19910403", "delist_date": None,
         "act_name": "old-act", "act_ent_type": None, "area": None, "cnspell": None},
        {"ts_code": "B.SZ", "symbol": "B", "name": "乙", "industry": "银行",
         "list_status": "L", "list_date": "20200101", "delist_date": None,
         "act_name": None, "act_ent_type": None, "area": None, "cnspell": None},
        {"ts_code": "C.SZ", "symbol": "C", "name": "丙", "industry": "地产",
         "list_status": "D", "list_date": "20190101", "delist_date": "20240601",
         "act_name": None, "act_ent_type": None, "area": None, "cnspell": None},
    ])


def test_migration_updates_only_pit_fields(tmp_path):
    """已有行只更新 list_status/delist_date——name/industry 等不被 source 覆盖。"""
    db = _db_full(tmp_path)
    migrate_stock_basic_pit_fields(db, _incoming())
    row = db.query("SELECT * FROM stock_basic WHERE ts_code='A.SZ'")
    assert row["name"][0] == "old-name"
    assert row["industry"][0] == "old-industry"
    assert row["list_status"][0] == "L"
    assert row["delist_date"][0] is None


def test_migration_inserts_new_codes(tmp_path):
    db = _db_full(tmp_path)
    migrate_stock_basic_pit_fields(db, _incoming())
    codes = db.query("SELECT ts_code FROM stock_basic ORDER BY ts_code")["ts_code"].to_list()
    assert codes == ["A.SZ", "B.SZ", "C.SZ"]
    b = db.query("SELECT * FROM stock_basic WHERE ts_code='B.SZ'")
    assert b["symbol"][0] == "B" and b["list_date"][0] == "20200101"
    c = db.query("SELECT * FROM stock_basic WHERE ts_code='C.SZ'")
    assert c["list_status"][0] == "D" and c["delist_date"][0] == "20240601"


def test_migration_preserves_codes_not_in_source(tmp_path):
    """DB 中 source 未包含的旧 code 必须保留（enrichment 非 destructive）。"""
    db = _db_full(tmp_path)
    db.upsert("stock_basic", pl.DataFrame({
        "ts_code": ["Z.SZ"], "symbol": ["Z"], "name": ["老股"], "list_date": ["20000101"],
    }), keys=["ts_code"])
    migrate_stock_basic_pit_fields(db, _incoming())
    codes = db.query("SELECT ts_code FROM stock_basic ORDER BY ts_code")["ts_code"].to_list()
    assert "Z.SZ" in codes   # 保留


def test_migration_rollback_on_validation_failure(tmp_path):
    """Phase 2 uniqueness validation 失败 → ROLLBACK——非 PIT 字段不被半更新。"""
    db = _db_full(tmp_path)
    with db.connect() as con:
        con.execute("INSERT INTO stock_basic (ts_code, symbol, name, industry, list_date, act_name)"
                    " VALUES ('A.SZ', 'A-dup', 'dup-name', 'dup-ind', '19910403', 'dup-act')")
        # 手工制造重复 ts_code（绕过 upsert 的唯一性保护）
    with pytest.raises(ValueError, match="ts_code 不唯一"):
        migrate_stock_basic_pit_fields(db, _incoming())
    # rollback 后非 PIT 字段未被半更新（A 的第一行仍是 original）
    rows = db.query("SELECT * FROM stock_basic WHERE ts_code='A.SZ' ORDER BY symbol")
    assert rows["name"][0] == "old-name" and rows["industry"][0] == "old-industry"
    assert "list_status" in db.describe("stock_basic")   # Phase-1 列已存在（幂等）




# ================================================================
# M6-07B2：validate_stock_basic_source 纯 validator（A-L）
# ================================================================

from factorlab.data.rebuild import validate_stock_basic_source


def _vl(**over):
    row = {"ts_code": "000001.SZ", "symbol": "000001", "name": "甲",
           "list_status": "L", "list_date": "19910403", "delist_date": None,
           "industry": "银行", "market": "主板", "act_name": None,
           "act_ent_type": None, "area": None, "cnspell": None}
    row.update(over)
    return row


def _vd(**over):
    row = _vl(ts_code="600001.SH", symbol="600001", name="丁",
              list_status="D", delist_date="20240601")
    row.update(over)
    return row


def _valid_pair(l_rows=None, d_rows=None):
    return (pl.DataFrame(l_rows or [_vl()]),
            pl.DataFrame(d_rows or [_vd()]))


# A. null list_date
def test_null_list_date_fails():
    l, d = _valid_pair(l_rows=[_vl(list_date=None)])
    with pytest.raises(ValueError, match="空 list_date"):
        validate_stock_basic_source(l, d)


# B/C. endpoint status partition
def test_l_endpoint_returns_d_row_fails():
    l, d = _valid_pair(l_rows=[_vl(list_status="D")])
    with pytest.raises(ValueError, match="L endpoint 返回非 L row"):
        validate_stock_basic_source(l, d)


def test_d_endpoint_returns_l_row_fails():
    l, d = _valid_pair(d_rows=[_vd(list_status="L")])
    with pytest.raises(ValueError, match="D endpoint 返回非 D row"):
        validate_stock_basic_source(l, d)


# D. unknown status
def test_unknown_status_fails():
    """P 状态被拒绝（endpoint 分区检查先拦——语义一致）。"""
    l, d = _valid_pair(l_rows=[_vl(list_status="P")])
    with pytest.raises(ValueError, match="非 L row|仅允许 L/D"):
        validate_stock_basic_source(l, d)


# E/F. invalid calendar dates
@pytest.mark.parametrize("bad_date", ["20240230", "20241301", "00000000"])
def test_invalid_list_date_fails(bad_date):
    l, d = _valid_pair(l_rows=[_vl(list_date=bad_date)])
    with pytest.raises(ValueError, match="list_date 非合法日历日期"):
        validate_stock_basic_source(l, d)


def test_invalid_delist_date_fails():
    l, d = _valid_pair(d_rows=[_vd(delist_date="20241301")])
    with pytest.raises(ValueError, match="delist_date 非合法日历日期"):
        validate_stock_basic_source(l, d)


# G. delist before list
def test_delist_before_list_fails():
    l, d = _valid_pair(d_rows=[_vd(list_date="20200101", delist_date="20191231")])
    with pytest.raises(ValueError, match="delist_date < list_date"):
        validate_stock_basic_source(l, d)


# H. invalid ts_code
@pytest.mark.parametrize("bad_code", ["000001", "1.SZ", "000001.XX", "abc.SZ"])
def test_invalid_ts_code_fails(bad_code):
    l, d = _valid_pair(l_rows=[_vl(ts_code=bad_code)])
    with pytest.raises(ValueError, match="ts_code 必须匹配"):
        validate_stock_basic_source(l, d)


# I. symbol mismatch
def test_symbol_mismatch_fails():
    l, d = _valid_pair(l_rows=[_vl(symbol="000002")])
    with pytest.raises(ValueError, match="symbol 必须匹配 ts_code 前六位"):
        validate_stock_basic_source(l, d)


# J. valid L row with delist=null → PASS
def test_valid_l_with_null_delist_passes():
    out = validate_stock_basic_source(*_valid_pair())
    assert out.height == 2


# K. valid D row (list < delist) → PASS
def test_valid_d_row_passes():
    out = validate_stock_basic_source(*_valid_pair())
    d = out.filter(pl.col("list_status") == "D")
    assert d["delist_date"][0] == "20240601" and d["list_date"][0] == "19910403"


# L. normal merge sorted unique
def test_normal_merge_sorted_unique():
    l, d = _valid_pair(l_rows=[_vl(), _vl(ts_code="000002.SZ", symbol="000002")])
    out = validate_stock_basic_source(l, d)
    assert out["ts_code"].is_sorted()
    assert out["ts_code"].n_unique() == out.height == 3


# ================================================================
# M6-07B3：null/空串/空白 list_status 显式拒绝
# ================================================================

def test_l_null_status_fails():
    l, d = _valid_pair(l_rows=[_vl(list_status=None)])
    with pytest.raises(ValueError, match="L endpoint 返回非 L row"):
        validate_stock_basic_source(l, d)


def test_d_null_status_fails():
    l, d = _valid_pair(d_rows=[_vd(list_status=None)])
    with pytest.raises(ValueError, match="D endpoint 返回非 D row"):
        validate_stock_basic_source(l, d)


def test_l_empty_string_status_fails():
    l, d = _valid_pair(l_rows=[_vl(list_status="")])
    with pytest.raises(ValueError, match="L endpoint 返回非 L row"):
        validate_stock_basic_source(l, d)


def test_l_whitespace_status_fails():
    """' L'（带前导空格）拒绝——不自动 strip。"""
    l, d = _valid_pair(l_rows=[_vl(list_status=" L")])
    with pytest.raises(ValueError, match="L endpoint 返回非 L row"):
        validate_stock_basic_source(l, d)


def test_merged_status_null_cannot_penetrate():
    """正常 valid source 的 merged 输出 list_status 无 null（防御检查生效）。"""
    out = validate_stock_basic_source(*_valid_pair())
    assert out["list_status"].null_count() == 0
    assert set(out["list_status"].unique().to_list()) == {"L", "D"}
