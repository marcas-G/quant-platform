"""M8-02B：open suspension evidence integration——loader 行为 + source contract。

Loader 从 suspend_d 读取事件行（ts_code/suspend_type/suspend_timing），
经 factorlab.execution.suspension（唯一 temporal authority）推导
is_suspended_at_open；runtime 重新 enforce production source contract：

- suspend_type ∈ {S, R}（不 strip/不 upper）
- timing absence = NULL only；non-null 必须 parse 成功（ValueError 穿透）
- R + non-null timing = source 未证明组合 → fail
- exact duplicate（type, timing）collapse；dedup 后 >1 distinct event → fail
  （production max distinct = 1；未知结构 fail fast，不发明 precedence）
"""

import datetime
from pathlib import Path

import duckdb
import polars as pl
import pytest

from factorlab.data.execution import load_market_open_frame
from factorlab.domain import MarketOpenSnapshot
from factorlab.execution import load_market_open_snapshot

EXEC = datetime.date(2024, 1, 8)
D = EXEC.strftime("%Y%m%d")
FILLER = "601111.SH"   # 无 suspend 事件的填充证券（保持 requested skeleton）

CODES = ["000001.SZ", "600000.SH", "601111.SH"]


def _path(tmp_path):
    return tmp_path / "s.duckdb"


def _db(tmp_path, *, suspends=None, with_timing_col=True, with_type_col=True):
    """daily/stk_limit 各一行 + 可选 suspend_d rows（返回已连接的 duckdb）。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect(_path(tmp_path))
    db.execute("CREATE TABLE trade_cal (cal_date VARCHAR, is_open INT)")
    db.execute("INSERT INTO trade_cal VALUES (?, 1)", (D,))
    db.execute("CREATE TABLE daily (trade_date VARCHAR, ts_code VARCHAR, open DOUBLE, pre_close DOUBLE)")
    db.execute("INSERT INTO daily VALUES (?,?,?,?)", (D, "601111.SH", 10.0, 9.8))
    db.execute("CREATE TABLE stk_limit (trade_date VARCHAR, ts_code VARCHAR, up_limit DOUBLE, down_limit DOUBLE)")
    db.execute("INSERT INTO stk_limit VALUES (?,?,?,?)", (D, "601111.SH", 11.0, 9.0))
    cols = ["trade_date VARCHAR", "ts_code VARCHAR"]
    if with_type_col:
        cols.append("suspend_type VARCHAR")
    if with_timing_col:
        cols.append("suspend_timing VARCHAR")
    db.execute(f"CREATE TABLE suspend_d ({', '.join(cols)})")
    for r in (suspends or []):
        placeholders = ", ".join(["?"] * len(r))
        db.execute(f"INSERT INTO suspend_d VALUES ({placeholders})", r)
    return db


def _load(tmp_path, *, suspends=None, with_timing_col=True, with_type_col=True,
          codes=None):
    db = _db(tmp_path, suspends=suspends, with_timing_col=with_timing_col,
             with_type_col=with_type_col)
    db.close()
    return load_market_open_snapshot(_path(tmp_path), execution_date=EXEC,
                                     codes=codes or CODES)


def _row(snap, code):
    return snap.frame.filter(pl.col("code") == code).row(0)


# ---------------- no event / basic semantics ----------------

def test_no_event_false_false(tmp_path):
    snap = _load(tmp_path)
    r = _row(snap, "601111.SH")
    assert r[7] is False and r[8] is False      # has_suspend_record / is_suspended_at_open


def test_s_null_true_true(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "S", None)])
    r = _row(snap, "000001.SZ")
    assert r[7] is True and r[8] is True


def test_r_null_true_false(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "R", None)])
    r = _row(snap, "000001.SZ")
    assert r[7] is True and r[8] is False


def test_same_session_covering_open(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "S", "09:30-10:00")])
    r = _row(snap, "000001.SZ")
    assert r[7] is True and r[8] is True


def test_later_intraday(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "S", "10:00-10:30")])
    r = _row(snap, "000001.SZ")
    assert r[7] is True and r[8] is False


def test_full_cycle(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "S", "09:30-09:30")])
    r = _row(snap, "000001.SZ")
    assert r[7] is True and r[8] is True


def test_wrapped_not_covering(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "S", "13:00-9:30")])
    r = _row(snap, "000001.SZ")
    assert r[7] is True and r[8] is False


def test_wrapped_covering_open(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "S", "13:00-10:00")])
    r = _row(snap, "000001.SZ")
    assert r[7] is True and r[8] is True


def test_multi_interval_covering(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "S", "09:30-10:31,10:31-14:57")])
    r = _row(snap, "000001.SZ")
    assert r[7] is True and r[8] is True


def test_multi_interval_not_covering(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "S", "10:00-10:30,13:00-14:00")])
    r = _row(snap, "000001.SZ")
    assert r[7] is True and r[8] is False


# ---------------- duplicate / multiplicity contract ----------------

def test_exact_duplicate_collapse(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "S", "09:30-10:00"),
                                         (D, "000001.SZ", "S", "09:30-10:00")])
    f = snap.frame.filter(pl.col("code") == "000001.SZ")
    assert f.height == 1 and f["has_suspend_record"][0] and f["is_suspended_at_open"][0]


def test_distinct_duplicate_fails(tmp_path):
    with pytest.raises(ValueError, match="distinct|多事件|multi"):
        _load(tmp_path, suspends=[(D, "000001.SZ", "S", None),
                                      (D, "000001.SZ", "R", None)])


def test_two_distinct_s_events_fail(tmp_path):
    with pytest.raises(ValueError, match="distinct|多事件|multi"):
        _load(tmp_path, suspends=[(D, "000001.SZ", "S", "09:30-10:00"),
                                      (D, "000001.SZ", "S", "13:00-14:00")])


def test_r_with_timing_fails(tmp_path):
    with pytest.raises(ValueError, match="R|timing|source"):
        _load(tmp_path, suspends=[(D, "000001.SZ", "R", "09:30-10:00")])


# ---------------- invalid source values ----------------

@pytest.mark.parametrize("bad_type", [None, "", "X", "S ", " R"])
def test_invalid_suspend_type_fails(tmp_path, bad_type):
    with pytest.raises(ValueError, match="suspend_type"):
        _load(tmp_path, suspends=[(D, "000001.SZ", bad_type, None)])


def test_invalid_timing_propagates(tmp_path):
    """S/foo → parser ValueError 向上穿透（不转为 record=True/open=False）。"""
    with pytest.raises(ValueError, match="segment|timing|suspend"):
        _load(tmp_path, suspends=[(D, "000001.SZ", "S", "foo")])


def test_empty_string_timing_fails(tmp_path):
    with pytest.raises(ValueError):
        _load(tmp_path, suspends=[(D, "000001.SZ", "S", "")])


# ---------------- schema contract（M8-02B0 runtime enforcement） ----------------

def test_missing_suspend_timing_column_fails(tmp_path):
    with pytest.raises(ValueError, match="suspend_timing"):
        _load(tmp_path, with_timing_col=False,
              suspends=[(D, "000001.SZ", "S")])


def test_missing_suspend_type_column_fails(tmp_path):
    with pytest.raises(ValueError, match="suspend_type"):
        _load(tmp_path, with_type_col=False,
              suspends=[(D, "000001.SZ", "09:30-10:00")])


def test_skeleton_rows_equal_codes(tmp_path):
    snap = _load(tmp_path, suspends=[(D, "000001.SZ", "S", None),
                                         (D, "600000.SH", "R", None)])
    assert snap.frame.height == 3
    assert snap.frame["code"].to_list() == sorted(CODES)


def test_row_order_determinism(tmp_path):
    """exact duplicate 行序变化 → snapshot equals。"""
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    a = _load(d1, suspends=[(D, "000001.SZ", "S", "09:30-10:00"),
                            (D, "000001.SZ", "S", "09:30-10:00")])
    b = _load(d2, suspends=[(D, "000001.SZ", "S", "09:30-10:00"),
                            (D, "000001.SZ", "S", "09:30-10:00")])
    assert a.frame.equals(b.frame)


def test_loader_does_not_modify_db(tmp_path):
    db = _db(tmp_path, suspends=[(D, "000001.SZ", "S", "09:30-10:00")])
    path = _path(tmp_path)
    before = db.execute("SELECT count(*) FROM suspend_d").fetchone()[0]
    db.close()
    load_market_open_frame(path, execution_date=EXEC, codes=CODES)
    con = duckdb.connect(path, read_only=True)
    after = con.execute("SELECT count(*) FROM suspend_d").fetchone()[0]
    con.close()
    assert before == after == 1


def test_import_no_cycle():
    """data.execution → execution.suspension 无循环（parser 仅 stdlib import）。"""
    import inspect
    import re
    from factorlab.execution.suspension import parse_suspend_timing
    mod = inspect.getmodule(parse_suspend_timing)
    src = inspect.getsource(mod)
    for forbidden in ("duckdb", "polars", "platform_db", "MarketOpenSnapshot",
                      "OrderBatch", "PortfolioState"):
        assert not re.search(rf"^\s*(import|from)\s+{forbidden}", src, re.M), \
            f"suspension.py 不得 import {forbidden}"


def test_empty_codes_typed_empty_9_columns(tmp_path):
    _db(tmp_path).close()
    frame = load_market_open_frame(_path(tmp_path), execution_date=EXEC,
                                   codes=[])
    assert frame.columns == ["code", "open", "pre_close", "up_limit", "down_limit",
                             "has_daily", "has_limit", "has_suspend_record",
                             "is_suspended_at_open"]
    assert frame.schema["is_suspended_at_open"] == pl.Boolean
    assert frame.height == 0


# ---------------- domain（MarketOpenSnapshot 9 列契约） ----------------

def _mk_snapshot(records=(True, True), open_flags=(False, False), flags_daily=None,
                 flags_limit=None):
    """手工构造 9 列 snapshot（绕过 loader 测 domain）。"""
    codes = ["000001.SZ", "600000.SH"]
    rows = []
    for i, c in enumerate(codes):
        fd = flags_daily[i] if flags_daily else (True, True)[i]
        fl = flags_limit[i] if flags_limit else (False, False)[i]
        fr = records[i] if records else False
        fo = open_flags[i] if open_flags else False
        open_ = 10.0 if fd else None
        pc = 9.8 if fd else None
        up = 11.0 if fl else None
        dn = 9.0 if fl else None
        rows.append((c, open_, pc, up, dn, fd, fl, fr, fo))
    frame = pl.DataFrame(rows, schema=["code", "open", "pre_close", "up_limit",
                                       "down_limit", "has_daily", "has_limit",
                                       "has_suspend_record", "is_suspended_at_open"],
                         orient="row")
    frame = frame.with_columns(
        pl.col("open").cast(pl.Float64), pl.col("pre_close").cast(pl.Float64),
        pl.col("up_limit").cast(pl.Float64), pl.col("down_limit").cast(pl.Float64),
        pl.col("has_daily").cast(pl.Boolean), pl.col("has_limit").cast(pl.Boolean),
        pl.col("has_suspend_record").cast(pl.Boolean),
        pl.col("is_suspended_at_open").cast(pl.Boolean))
    return MarketOpenSnapshot(execution_date=EXEC, frame=frame)


def test_domain_legal_combinations():
    assert _mk_snapshot(records=(False, False), open_flags=(False, False)).frame.height == 2
    assert _mk_snapshot(records=(True, True), open_flags=(False, False)).frame.height == 2
    assert _mk_snapshot(records=(True, True), open_flags=(True, True)).frame.height == 2


def test_domain_illegal_record_false_open_true():
    with pytest.raises(ValueError, match="has_suspend_record|implication|implies"):
        _mk_snapshot(records=(False, False), open_flags=(True, False))


def test_domain_missing_column_fails():
    frame = _mk_snapshot(records=(False, False)).frame.drop("is_suspended_at_open")
    with pytest.raises(ValueError, match="9|columns|is_suspended"):
        MarketOpenSnapshot(execution_date=EXEC, frame=frame)


def test_domain_extra_column_fails():
    frame = _mk_snapshot(records=(False, False)).frame.with_columns(
        pl.Series([False, False], dtype=pl.Boolean).alias("can_trade"))
    with pytest.raises(ValueError, match="columns|can_trade|is_tradable"):
        MarketOpenSnapshot(execution_date=EXEC, frame=frame)


@pytest.mark.parametrize("dtype", [pl.Int64, pl.String, pl.Float64])
def test_domain_wrong_dtype_fails(dtype):
    frame = _mk_snapshot(records=(False, False)).frame.with_columns(
        pl.Series([0, 0]).cast(dtype).alias("is_suspended_at_open"))
    with pytest.raises(ValueError, match="Boolean"):
        MarketOpenSnapshot(execution_date=EXEC, frame=frame)


def test_domain_null_flag_fails():
    frame = _mk_snapshot(records=(True, True)).frame.with_columns(
        pl.Series([True, None], dtype=pl.Boolean).alias("is_suspended_at_open"))
    with pytest.raises(ValueError, match="is_suspended_at_open|Boolean|null"):
        MarketOpenSnapshot(execution_date=EXEC, frame=frame)
