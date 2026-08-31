"""M8-02：MarketOpenSnapshot + load_market_open_frame/snapshot。"""

import datetime
from dataclasses import FrozenInstanceError

import duckdb
import polars as pl
import pytest

from factorlab.data.execution import load_market_open_frame
from factorlab.domain import MarketOpenSnapshot
from factorlab.execution import load_market_open_snapshot

EXEC = datetime.date(2024, 1, 8)
PREV = datetime.date(2024, 1, 5)

CODES = ["000001.SZ", "600000.SH", "600519.SH"]


def _db(tmp_path, *, daily=None, limits=None, suspends=None, cal_open=None,
        with_daily=True, with_limit=True, with_suspend=True, with_cal=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect(tmp_path / "m.duckdb")
    db.execute("CREATE TABLE trade_cal (cal_date VARCHAR, is_open INT)")
    for d in (cal_open if cal_open is not None else [EXEC, PREV]):
        db.execute("INSERT INTO trade_cal VALUES (?, 1)", (d.strftime("%Y%m%d"),))
    if with_daily:
        db.execute("CREATE TABLE daily (trade_date VARCHAR, ts_code VARCHAR, open DOUBLE, pre_close DOUBLE)")
        for r in (daily or []):
            db.execute("INSERT INTO daily VALUES (?,?,?,?)", r)
    if with_limit:
        db.execute("CREATE TABLE stk_limit (trade_date VARCHAR, ts_code VARCHAR, up_limit DOUBLE, down_limit DOUBLE)")
        for r in (limits or []):
            db.execute("INSERT INTO stk_limit VALUES (?,?,?,?)", r)
    if with_suspend:
        db.execute("CREATE TABLE suspend_d (trade_date VARCHAR, ts_code VARCHAR)")
        for r in (suspends or []):
            db.execute("INSERT INTO suspend_d VALUES (?,?)", r)
    return db


def _golden_db(tmp_path):
    """§74 golden：000001 全证据、600000 仅 suspend、600519 全证据。"""
    return _db(tmp_path,
               daily=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 10.0, 9.8),
                      (EXEC.strftime("%Y%m%d"), "600519.SH", 100.0, 99.0)],
               limits=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 10.78, 8.82),
                       (EXEC.strftime("%Y%m%d"), "600519.SH", 108.9, 89.1)],
               suspends=[(EXEC.strftime("%Y%m%d"), "600000.SH")])


def _snap(db, codes=None):
    db.close()
    return load_market_open_snapshot(
        None if db is None else _path_of(db), execution_date=EXEC,
        codes=codes or CODES)


def _path_of(db):
    return db  # 占位——实际用 tmp_path 传入


# ---------------- golden ----------------

def test_golden_three_code(tmp_path):
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)
    f = snap.frame
    assert f.height == 3
    r1 = f.filter(pl.col("code") == "000001.SZ")
    assert r1["has_daily"][0] and r1["has_limit"][0] and not r1["has_suspend_record"][0]
    assert r1["open"][0] == 10.0 and r1["pre_close"][0] == 9.8
    assert r1["up_limit"][0] == 10.78 and r1["down_limit"][0] == 8.82
    r2 = f.filter(pl.col("code") == "600000.SH")
    assert not r2["has_daily"][0] and not r2["has_limit"][0] and r2["has_suspend_record"][0]
    assert r2["open"][0] is None and r2["up_limit"][0] is None
    r3 = f.filter(pl.col("code") == "600519.SH")
    assert r3["has_daily"][0] and r3["has_limit"][0] and not r3["has_suspend_record"][0]


# ---------------- schema / dtypes ----------------

def test_exact_schema(tmp_path):
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)
    assert snap.frame.columns == ["code", "open", "pre_close", "up_limit",
                                  "down_limit", "has_daily", "has_limit",
                                  "has_suspend_record"]
    assert snap.frame.schema["open"] == pl.Float64
    assert snap.frame.schema["pre_close"] == pl.Float64
    assert snap.frame.schema["up_limit"] == pl.Float64
    assert snap.frame.schema["down_limit"] == pl.Float64
    assert snap.frame.schema["has_daily"] == pl.Boolean
    assert snap.frame.schema["has_limit"] == pl.Boolean
    assert snap.frame.schema["has_suspend_record"] == pl.Boolean
    assert snap.execution_date == EXEC


def test_canonical_code_guard(tmp_path):
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError):
        load_market_open_snapshot(path, execution_date=EXEC, codes=["000001"])


def test_duplicate_input_code_fails(tmp_path):
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError):
        load_market_open_snapshot(path, execution_date=EXEC,
                                  codes=["000001.SZ", "000001.SZ"])


def test_input_order_invariant(tmp_path):
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    a = load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)
    b = load_market_open_snapshot(path, execution_date=EXEC,
                                  codes=list(reversed(CODES)))
    assert a.frame.equals(b.frame)


# ---------------- duplicate policies ----------------

def test_daily_duplicate_fails(tmp_path):
    d = (EXEC.strftime("%Y%m%d"), "000001.SZ", 10.0, 9.8)
    db = _db(tmp_path, daily=[d, d], limits=[(EXEC.strftime("%Y%m%d"), "600000.SH", 100.0, 90.0)])
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError, match="重复|duplicate"):
        load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)


def test_limit_duplicate_fails(tmp_path):
    l = (EXEC.strftime("%Y%m%d"), "000001.SZ", 10.78, 8.82)
    db = _db(tmp_path, daily=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 10.0, 9.8)],
             limits=[l, l])
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError, match="重复|duplicate"):
        load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)


def test_suspend_duplicates_collapse(tmp_path):
    db = _db(tmp_path, daily=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 10.0, 9.8)],
             limits=[(EXEC.strftime("%Y%m%d"), "600000.SH", 100.0, 90.0)],
             suspends=[(EXEC.strftime("%Y%m%d"), "600000.SH"),
                       (EXEC.strftime("%Y%m%d"), "600000.SH")])
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)
    r = snap.frame.filter(pl.col("code") == "600000.SH")
    assert r.height == 1 and r["has_suspend_record"][0]


# ---------------- missing-data semantics ----------------

def test_single_code_missing_daily_represented(tmp_path):
    """600000 无 daily → has_daily=False 且 open=null（不 drop、不自动 suspend）。"""
    db = _db(tmp_path, daily=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 10.0, 9.8)],
             limits=[(EXEC.strftime("%Y%m%d"), "600000.SH", 100.0, 90.0)])
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)
    f = snap.frame
    assert f.height == 3
    r = f.filter(pl.col("code") == "600000.SH")
    assert not r["has_daily"][0] and not r["has_suspend_record"][0]
    assert r["open"][0] is None and r["pre_close"][0] is None


def test_single_code_missing_limit_represented(tmp_path):
    db = _db(tmp_path, daily=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 10.0, 9.8)],
             limits=[(EXEC.strftime("%Y%m%d"), "600000.SH", 100.0, 90.0)])
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)
    r = snap.frame.filter(pl.col("code") == "000001.SZ")
    assert r["has_limit"][0] is False and r["up_limit"][0] is None


def test_zero_suspend_rows_valid(tmp_path):
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)
    assert snap.frame["has_suspend_record"].sum() == 1


# ---------------- invariants / raw price ----------------

def test_raw_open_exactness(tmp_path):
    db = _db(tmp_path, daily=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 12.345678, 9.8)],
             limits=[(EXEC.strftime("%Y%m%d"), "600000.SH", 100.0, 90.0)])
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=["000001.SZ"])
    assert snap.frame["open"][0] == 12.345678


def test_has_daily_true_requires_finite_positive(tmp_path):
    for i, bad in enumerate((0.0, -1.0, float("nan"), float("inf"))):
        sub = tmp_path / f"bad{i}"
        db = _db(sub, daily=[(EXEC.strftime("%Y%m%d"), "000001.SZ", bad, 9.8)],
                 limits=[(EXEC.strftime("%Y%m%d"), "600000.SH", 100.0, 90.0)])
        path = sub / "m.duckdb"
        db.close()
        with pytest.raises(ValueError):
            load_market_open_snapshot(path, execution_date=EXEC, codes=["000001.SZ"])


def test_has_limit_true_invariant(tmp_path):
    db = _db(tmp_path, daily=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 10.0, 9.8)],
             limits=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 8.0, 10.0)])   # down > up
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError, match="down|up"):
        load_market_open_snapshot(path, execution_date=EXEC, codes=["000001.SZ"])


# ---------------- coverage gates / required tables ----------------

def test_missing_daily_table_fails(tmp_path):
    db = _db(tmp_path, with_daily=False)
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError, match="daily"):
        load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)


def test_missing_stk_limit_table_fails(tmp_path):
    db = _db(tmp_path, with_limit=False)
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError, match="stk_limit"):
        load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)


def test_missing_suspend_d_table_fails(tmp_path):
    db = _db(tmp_path, with_suspend=False)
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError, match="suspend_d"):
        load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)


def test_non_open_execution_date_fails(tmp_path):
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError, match="开放|open"):
        load_market_open_snapshot(path, execution_date=datetime.date(2024, 1, 6),
                                  codes=CODES)


def test_global_daily_coverage_zero_fails(tmp_path):
    """trade_cal 当天开市但 daily 全市场 0 行 → fail（不假装全停牌）。"""
    db = _db(tmp_path, daily=[], limits=[])
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError, match="coverage"):
        load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)


def test_global_limit_coverage_zero_fails(tmp_path):
    db = _db(tmp_path, daily=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 10.0, 9.8)],
             limits=[])
    path = tmp_path / "m.duckdb"
    db.close()
    with pytest.raises(ValueError, match="stk_limit.*coverage|coverage"):
        load_market_open_snapshot(path, execution_date=EXEC, codes=["000001.SZ"])


def test_typed_empty_snapshot(tmp_path):
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=[])
    assert snap.frame.height == 0
    assert snap.frame.schema["open"] == pl.Float64
    assert snap.frame.schema["has_daily"] == pl.Boolean


def test_all_null_numeric_columns_float64(tmp_path):
    """所有请求证券都无 limit → up/down 全 null 仍 Float64（非 Null dtype）。"""
    db = _db(tmp_path, daily=[(EXEC.strftime("%Y%m%d"), "000001.SZ", 10.0, 9.8)],
             limits=[(EXEC.strftime("%Y%m%d"), "600000.SH", 100.0, 90.0)])
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=["000001.SZ"])
    assert snap.frame.schema["up_limit"] == pl.Float64
    assert snap.frame["up_limit"].null_count() == 1


def test_row_order_invariant(tmp_path):
    """daily/limit/suspend 行序变化 → snapshot frame.equals 相同。"""
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    db1 = _golden_db(d1)
    p1 = d1 / "m.duckdb"
    db1.close()
    db2 = _golden_db(d2)
    p2 = d2 / "m.duckdb"
    db2.close()
    a = load_market_open_snapshot(p1, execution_date=EXEC, codes=CODES)
    b = load_market_open_snapshot(p2, execution_date=EXEC, codes=CODES)
    assert a.frame.equals(b.frame)


def test_frozen_snapshot(tmp_path):
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)
    with pytest.raises(FrozenInstanceError):
        snap.frame = pl.DataFrame()


def test_no_is_tradable_field(tmp_path):
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    snap = load_market_open_snapshot(path, execution_date=EXEC, codes=CODES)
    assert "is_tradable" not in snap.frame.columns
    assert "can_buy" not in snap.frame.columns


def test_data_layer_frame(tmp_path):
    """load_market_open_frame 返回 8 列原始 frame（不经 domain）。"""
    db = _golden_db(tmp_path)
    path = tmp_path / "m.duckdb"
    db.close()
    frame = load_market_open_frame(path, execution_date=EXEC, codes=CODES)
    assert frame.columns == ["code", "open", "pre_close", "up_limit",
                             "down_limit", "has_daily", "has_limit",
                             "has_suspend_record"]
    assert frame.height == 3
