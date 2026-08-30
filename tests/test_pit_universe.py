"""M6-02：PIT Universe——resolve_candidate_codes / resolve_universe_frame / align_to_universe。

核心 invariant：Universe membership at t 不能依赖 t 之后的数据
（ST / listing / delisting 均须 PIT）。
"""

import datetime

import duckdb
import polars as pl
import pytest

from factorlab.data.universe import (align_to_universe, resolve_candidate_codes,
                                     resolve_universe_frame)
from factorlab.spec import FactorSpec

# A: 2024-01-01 上市（无退市）；B: 2024-01-15 上市；C: 2020-01-01 上市、2024-06-01 退市
LIST_A, LIST_B, DELIST_C = "20240101", "20240115", "20240601"


def build_db(tmp_path, with_delist: bool = True, with_st_table: bool = True,
             st_rows: list[tuple] | None = None) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect(tmp_path / "t.duckdb")
    cols = "ts_code VARCHAR, symbol VARCHAR, exchange VARCHAR, list_date VARCHAR, industry VARCHAR, market VARCHAR"
    if with_delist:
        cols += ", delist_date VARCHAR"
    db.execute(f"CREATE TABLE stock_basic ({cols})")
    if with_delist:
        rows = [
            ("000001.SZ", "000001", "SZSE", LIST_A, "银行", "主板", None),
            ("600000.SH", "600000", "SSE", LIST_B, "银行", "主板", None),
            ("000002.SZ", "000002", "SZSE", "20200101", "地产", "主板", DELIST_C),
            ("830001.BJ", "830001", "BSE", "20200101", "其他", "北交所", None),
        ]
    else:
        rows = [
            ("000001.SZ", "000001", "SZSE", LIST_A, "银行", "主板"),
            ("600000.SH", "600000", "SSE", LIST_B, "银行", "主板"),
            ("000002.SZ", "000002", "SZSE", "20200101", "地产", "主板"),
            ("830001.BJ", "830001", "BSE", "20200101", "其他", "北交所"),
        ]
    db.executemany(f"INSERT INTO stock_basic VALUES ({','.join('?' * len(rows[0]))})", rows)
    if with_st_table:
        db.execute("CREATE TABLE stock_st (ts_code VARCHAR, name VARCHAR, trade_date VARCHAR, type VARCHAR, type_name VARCHAR)")
        for r in (st_rows or []):
            db.execute("INSERT INTO stock_st VALUES (?,?,?,?,?)", r)
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
    db.execute("CREATE TABLE trade_cal (exchange VARCHAR, cal_date VARCHAR, is_open BIGINT)")
    return db


@pytest.fixture
def db(tmp_path):
    # ST coverage = [20240301, 20240304]：A 3/1 ST；600000 3/4 ST（扩大 coverage 供 absent 用例）
    conn = build_db(tmp_path, st_rows=[
        ("000001.SZ", "ST平安", "20240301", "ST", "实施风险警示"),
        ("600000.SH", "ST银行", "20240304", "ST", "实施风险警示"),
    ])
    yield conn
    conn.close()


def spec_with(**universe_kwargs):
    return FactorSpec.model_validate({
        "name": "demo", "category": "custom", "direction": 1,
        "universe": universe_kwargs, "formula": "signal = close",
    })


DATES = ["2024-01-10", "2024-01-25", "2024-02-10", "2024-03-01", "2024-03-04",
         "2024-05-31", "2024-06-01", "2024-06-02"]


def _uf(db, **universe_kwargs):
    spec = spec_with(**universe_kwargs)
    return resolve_universe_frame(spec, db, DATES)


# ---------------------------------------------------------------- 基础 schema

def test_universe_frame_schema_and_unique(db):
    uf = _uf(db, rules={"min_list_days": 20, "exchanges": ["SSE", "SZSE"]})
    assert uf.columns == ["date", "code", "in_universe", "is_listed", "list_days",
                          "is_st", "exchange"]
    assert uf.schema["date"] == pl.Date
    assert uf.schema["code"] == pl.String
    assert uf.schema["in_universe"] == pl.Boolean
    assert uf["list_days"].dtype in (pl.Int32, pl.Int64)
    assert uf["is_st"].dtype == pl.Boolean
    assert uf.group_by(["date", "code"]).len().filter(pl.col("len") > 1).height == 0
    assert (uf.sort(["date", "code"])["date"].to_list() == uf["date"].to_list())


# ---------------------------------------------------------------- 上市年龄动态

def test_list_days_dynamic_membership(db):
    """min_list_days=20（自然日）：A(list 1/1) 1/21 起；B(list 1/15) 2/4 起。"""
    uf = _uf(db, rules={"min_list_days": 20, "exchanges": ["SSE", "SZSE"]})
    m = uf.filter(pl.col("code").is_in(["000001", "600000"]))
    got = {r["code"]: {r["date"]: r["in_universe"] for r in m.iter_rows(named=True)}
           if False else {} for r in []}
    a = m.filter(pl.col("code") == "000001").sort("date")
    b = m.filter(pl.col("code") == "600000").sort("date")
    a_days = {str(r["date"]): bool(r["in_universe"]) for r in a.iter_rows(named=True)}
    b_days = {str(r["date"]): bool(r["in_universe"]) for r in b.iter_rows(named=True)}
    assert a_days["2024-01-10"] is False          # 1/1 + 20 自然日 = 1/21 起
    assert a_days["2024-01-25"] is True
    assert a_days["2024-02-10"] is True
    assert b_days["2024-01-10"] is False          # 1/15 + 20 = 2/4 起
    assert b_days["2024-01-25"] is False
    assert b_days["2024-02-10"] is True


def test_list_days_is_natural_days(db):
    uf = _uf(db, rules={"min_list_days": 0})
    a = uf.filter((pl.col("code") == "000001") & (pl.col("date") == datetime.date(2024, 1, 10)))
    assert a["list_days"][0] == 9   # 2024-01-10 − 2024-01-01 = 9 自然日


# ---------------------------------------------------------------- ST PIT

def test_st_pit_membership(db):
    """ST PIT：coverage 内（20240301-20240301）当日快照出现 true、缺席 false。"""
    uf = resolve_universe_frame(spec_with(rules={"exclude_st": True, "exchanges": ["SSE", "SZSE"]}),
                                db, ["2024-03-01", "2024-03-04"])
    a = uf.filter(pl.col("code") == "000001").sort("date")
    st = {str(r["date"]): (bool(r["is_st"]), bool(r["in_universe"]))
          for r in a.iter_rows(named=True)}
    assert st["2024-03-01"] == (True, False)    # 当日 ST 快照出现
    assert st["2024-03-04"] == (False, True)    # 当日不在 ST 快照


def test_future_st_does_not_pollute_past(tmp_path, db):
    """未来 ST（2025-01-01）加入后，2024-03-01 的 membership 必须完全不变。"""
    spec = spec_with(rules={"exclude_st": True, "exchanges": ["SSE", "SZSE"]})
    before = resolve_universe_frame(spec, db, ["2024-03-01", "2024-03-04"])
    db.execute("INSERT INTO stock_st VALUES ('000001.SZ', 'ST平安', '20250101', 'ST', '实施风险警示')")
    after = resolve_universe_frame(spec, db, ["2024-03-01", "2024-03-04"])
    past_before = before.filter(pl.col("date") == datetime.date(2024, 3, 1)).sort("code")
    past_after = after.filter(pl.col("date") == datetime.date(2024, 3, 1)).sort("code")
    assert past_before.equals(past_after)


# ---------------------------------------------------------------- 退市

def test_delisting_boundary(db):
    """t < delist_date 平台语义：5/31 listed、6/1 起 not listed。"""
    uf = _uf(db, rules={"exchanges": ["SSE", "SZSE"]})
    c = uf.filter(pl.col("code") == "000002").sort("date")
    days = {str(r["date"]): (bool(r["is_listed"]), bool(r["in_universe"]))
            for r in c.iter_rows(named=True)}
    assert days["2024-05-31"] == (True, True)
    assert days["2024-06-01"] == (False, False)
    assert days["2024-06-02"] == (False, False)


# ---------------------------------------------------------------- 显式 codes

def test_explicit_codes_respect_listing(db):
    """显式 codes 同样尊重上市/退市 PIT 状态（用 C 验证退市边界）。"""
    uf = _uf(db, codes=["000001", "000002"])
    c = uf.filter(pl.col("code") == "000002").sort("date")
    c_days = {str(r["date"]): bool(r["in_universe"]) for r in c.iter_rows(named=True)}
    assert c_days["2024-05-31"] is True
    assert c_days["2024-06-01"] is False   # 显式 codes 同样尊重 delist


def test_explicit_codes_before_listing(db):
    """codes 模式：list_date 前 in_universe=false。用 2023 日期验证。"""
    spec = spec_with(codes=["000001"])
    uf = resolve_universe_frame(spec, db, ["2023-12-31", "2024-01-01", "2024-01-02"])
    a = uf.filter(pl.col("code") == "000001").sort("date")
    days = {str(r["date"]): bool(r["in_universe"]) for r in a.iter_rows(named=True)}
    assert days["2023-12-31"] is False
    assert days["2024-01-01"] is True     # list_date <= t
    assert days["2024-01-02"] is True


# ---------------------------------------------------------------- exchange

def test_exchange_semantics(db):
    uf = _uf(db, rules={"exchanges": ["SSE", "SZSE"]})
    ex = uf.filter(pl.col("date") == datetime.date(2024, 2, 10)).select("code", "exchange").sort("code")
    got = {r["code"]: r["exchange"] for r in ex.iter_rows(named=True)}
    assert got["000001"] == "SZSE"
    assert got["600000"] == "SSE"
    assert "830001" not in got          # BSE 不意外纳入


def test_default_exchange_no_bse(db):
    uf = _uf(db, rules={})
    codes = set(uf.filter(pl.col("in_universe"))["code"].unique().to_list())
    assert "830001" not in codes


# ---------------------------------------------------------------- stock_st 缺表

def test_st_table_missing_exclude_st_fails(tmp_path):
    db = build_db(tmp_path, st_rows=None, with_st_table=False)
    spec = spec_with(rules={"exclude_st": True, "exchanges": ["SSE", "SZSE"]})
    with pytest.raises(ValueError, match="stock_st"):
        resolve_universe_frame(spec, db, DATES)
    db.close()


def test_st_table_missing_exclude_st_false_is_st_null(tmp_path):
    db = build_db(tmp_path, st_rows=None, with_st_table=False)
    uf = resolve_universe_frame(spec_with(rules={"exchanges": ["SSE", "SZSE"]}), db, DATES)
    assert uf["is_st"].null_count() == uf.height      # is_st = null（无法判断）
    assert uf.filter(pl.col("code") == "000001").filter(pl.col("in_universe")).height > 0
    db.close()


# ---------------------------------------------------------------- candidate codes

def test_candidate_codes_skip_dynamic_rules(db):
    """candidate 不应用 exclude_st/min_list_days（动态 PIT 条件），但应用 exchange。"""
    spec = spec_with(rules={"exclude_st": True, "min_list_days": 20, "exchanges": ["SSE", "SZSE"]})
    codes = resolve_candidate_codes(spec, db)
    assert "000001" in codes        # ST 股票仍在候选集（1/10 时未上市也不影响候选）
    assert "600000" in codes
    assert "830001" not in codes    # exchange 过滤仍应用


def test_candidate_codes_explicit(tmp_path):
    db = build_db(tmp_path)
    codes = resolve_candidate_codes(spec_with(codes=["000001"]), db)
    assert codes == ["000001"]
    db.close()


# ---------------------------------------------------------------- align_to_universe

def test_align_keeps_active_missing_and_drops_inactive(db):
    uf = _uf(db, rules={"exchanges": ["SSE", "SZSE"]})
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 2, 10), datetime.date(2024, 2, 10), datetime.date(2024, 2, 10)], dtype=pl.Date),
        "code": pl.Series(["000001", "000002", "830001"], dtype=pl.String),
        "close": pl.Series([1.0, 100.0, 50.0], dtype=pl.Float64),
    })
    out = align_to_universe(raw, uf)
    d = out.filter(pl.col("date") == datetime.date(2024, 2, 10))
    got = {r["code"]: (r["close"] if r["close"] is not None else None)
           for r in d.iter_rows(named=True)}
    assert got["000001"] == 1.0      # A active + 有行情
    assert got["000002"] == 100.0    # C（2/10 未退市）active + 有行情
    assert got["600000"] is None     # B active 但 raw 无行情 → null 保留
    assert "830001" not in got       # BSE 非 active 排除
    # 重新用 5/31（C 未退市、B 未上市——active 集合 = A(1/21起)+C）：
    uf2 = resolve_universe_frame(spec_with(rules={"exchanges": ["SSE", "SZSE"]}), db,
                                 ["2024-05-31"])
    raw2 = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 5, 31), datetime.date(2024, 5, 31), datetime.date(2024, 5, 31)], dtype=pl.Date),
        "code": pl.Series(["000001", "000002", "600000"], dtype=pl.String),
        "close": pl.Series([1.0, 100.0, 50.0], dtype=pl.Float64),
    })
    out2 = align_to_universe(raw2, uf2)
    d2 = out2.filter(pl.col("date") == datetime.date(2024, 5, 31))
    got2 = {r["code"]: (r["close"] if r["close"] is not None else None)
            for r in d2.iter_rows(named=True)}
    assert got2["000001"] == 1.0
    assert got2["000002"] == 100.0
    assert got2["600000"] == 50.0    # B active + raw 有行情


def test_align_excludes_inactive_even_with_raw(db):
    """C inactive 即使 raw 有行情也必须排除（CS isolation 前置条件）。"""
    uf = _uf(db, rules={"exchanges": ["SSE", "SZSE"]})
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 6, 2), datetime.date(2024, 6, 2), datetime.date(2024, 6, 2)], dtype=pl.Date),
        "code": pl.Series(["000001", "000002", "600000"], dtype=pl.String),
        "value": pl.Series([1.0, 100.0, 2.0], dtype=pl.Float64),
    })
    out = align_to_universe(raw, uf)
    d = out.filter(pl.col("date") == datetime.date(2024, 6, 2))
    codes = set(d["code"].to_list())
    assert codes == {"000001", "600000"}      # C（退市 inactive）完全不存在
    assert d.filter(pl.col("code") == "600000")["value"][0] == 2.0  # B active + 有行情


def test_align_fail_fast_duplicate_raw(db):
    uf = _uf(db, rules={"exchanges": ["SSE", "SZSE"]})
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 2, 10), datetime.date(2024, 2, 10)], dtype=pl.Date),
        "code": pl.Series(["000001", "000001"], dtype=pl.String),
        "close": pl.Series([1.0, 2.0], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="unique"):
        align_to_universe(raw, uf)


def test_align_fail_fast_duplicate_universe(db):
    uni = _uf(db, rules={"exchanges": ["SSE", "SZSE"]})
    dup = pl.concat([uni, uni.head(1)])
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 2, 10)], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "close": pl.Series([1.0], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="unique"):
        align_to_universe(raw, dup)


# ---------------------------------------------------------------- chunk / slice

def test_date_slice_independent(db):
    """API 支持任意日期 slice——多次小 slice 与全量结果一致（不依赖全历史生成）。"""
    spec = spec_with(rules={"min_list_days": 20, "exchanges": ["SSE", "SZSE"]})
    full = resolve_universe_frame(spec, db, DATES)
    parts = []
    for chunk in (DATES[:3], DATES[3:6], DATES[6:]):
        parts.append(resolve_universe_frame(spec, db, chunk))
    merged = pl.concat(parts).sort(["date", "code"])
    assert merged.equals(full.sort(["date", "code"]))


# ================================================================
# M6-02A Hardening 新增测试
# ================================================================

# ---- 1. universe 驱动：某日 raw 完全无行，active date/code 不消失 ----

def test_align_keeps_entire_active_date_when_raw_has_no_rows_for_date(db):
    uf = _uf(db, rules={"exchanges": ["SSE", "SZSE"]})
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 2, 10)], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "close": pl.Series([1.0], dtype=pl.Float64),
    })
    out = align_to_universe(raw, uf)
    # 1/10：raw 完全无行——active 行（A）必须保留 null
    jan = out.filter(pl.col("date") == datetime.date(2024, 1, 10))
    assert jan.filter(pl.col("code") == "000001")["close"][0] is None
    assert jan.height >= 1
    # 2/10：000001 有行情
    feb = out.filter((pl.col("date") == datetime.date(2024, 2, 10))
                     & (pl.col("code") == "000001"))
    assert feb["close"][0] == 1.0


# ---- 2/3. code 严格 pl.String ----

def test_align_raw_code_int_rejected(db):
    uf = _uf(db, rules={"exchanges": ["SSE", "SZSE"]})
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 2, 10)], dtype=pl.Date),
        "code": pl.Series([1], dtype=pl.Int64),
        "close": pl.Series([1.0], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="String"):
        align_to_universe(raw, uf)


def test_align_universe_code_int_rejected(db):
    uni = _uf(db, rules={"exchanges": ["SSE", "SZSE"]}).with_columns(pl.col("code").cast(pl.Int64))
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 2, 10)], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "close": pl.Series([1.0], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="String"):
        align_to_universe(raw, uni)


# ---- 4/5. universe 完整 schema ----

def test_align_universe_missing_in_universe(db):
    uni = _uf(db, rules={"exchanges": ["SSE", "SZSE"]}).drop("in_universe")
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 2, 10)], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "close": pl.Series([1.0], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="in_universe"):
        align_to_universe(raw, uni)


def test_align_universe_in_universe_wrong_dtype(db):
    uni = _uf(db, rules={"exchanges": ["SSE", "SZSE"]}).with_columns(pl.col("in_universe").cast(pl.Int8))
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 2, 10)], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "close": pl.Series([1.0], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="Boolean"):
        align_to_universe(raw, uni)


# ---- 6/7. duplicate dates / candidate_codes ----

def test_duplicate_dates_rejected(db):
    with pytest.raises(ValueError, match="dates 重复"):
        resolve_universe_frame(spec_with(rules={"exchanges": ["SSE", "SZSE"]}), db,
                               ["2024-01-10", "2024-01-10"])


def test_duplicate_candidate_codes_rejected(db):
    with pytest.raises(ValueError, match="candidate_codes 重复"):
        resolve_universe_frame(spec_with(rules={}), db, ["2024-01-10"],
                               candidate_codes=["000001", "000001"])


# ---- 8. pre-list list_days null ----

def test_pre_list_list_days_null(db):
    uf = resolve_universe_frame(spec_with(codes=["000001"]), db, ["2023-12-31"])
    a = uf.filter(pl.col("code") == "000001")
    assert a["list_days"][0] is None
    assert a["is_listed"][0] == False


# ---- 9/10. ST coverage 外 + exclude_st=true → fail fast ----

def test_st_before_coverage_exclude_true_fails(db):
    """coverage = [20240301, 20240301]；1/10 在 coverage 前 → fail fast。"""
    with pytest.raises(ValueError, match="ST coverage"):
        _uf(db, rules={"exclude_st": True, "exchanges": ["SSE", "SZSE"]})


def test_st_after_coverage_exclude_true_fails(db):
    with pytest.raises(ValueError, match="ST coverage"):
        resolve_universe_frame(spec_with(rules={"exclude_st": True, "exchanges": ["SSE", "SZSE"]}),
                               db, ["2024-04-01"])


# ---- 11/12. coverage 外 unknown / 内 absent=false ----

def test_st_outside_coverage_is_st_null(db):
    uf = _uf(db, rules={"exchanges": ["SSE", "SZSE"]})
    jan = uf.filter(pl.col("date") == datetime.date(2024, 1, 10))
    assert jan["is_st"].null_count() == jan.height    # unknown ≠ false


def test_st_inside_coverage_absent_false(db):
    uf = _uf(db, rules={"exchanges": ["SSE", "SZSE"]})
    mar4 = uf.filter((pl.col("date") == datetime.date(2024, 3, 4))
                     & (pl.col("code") == "000001"))
    assert mar4["is_st"][0] == False


# ---- 日期严格校验 ----

@pytest.mark.parametrize("bad", ["2024-01-01 garbage", "20240101", "abc", "2024/01/01"])
def test_invalid_date_strings_rejected(db, bad):
    with pytest.raises(ValueError, match="非法日期"):
        resolve_universe_frame(spec_with(rules={}), db, [bad])


# ================================================================
# M6-07B：raw stock_st duplicates 不膨胀 UniverseFrame
# ================================================================

def test_duplicate_st_rows_no_cardinality_blowup(tmp_path):
    """同 (date, code) 两条 payload 不同的 ST 行（type=ST / type=*ST）——
    UniverseFrame 每 date/code 仅 1 行、is_st=true。"""
    db = build_db(tmp_path, st_rows=[
        ("000001.SZ", "ST平安", "20240301", "ST", "实施风险警示"),
        ("000001.SZ", "*ST平安", "20240301", "*ST", "退市风险警示"),   # 同 key payload 不同
        ("600000.SH", "ST银行", "20240304", "ST", "实施风险警示"),      # coverage 覆盖到 3/4
    ])
    spec = spec_with(rules={"exclude_st": True, "exchanges": ["SSE", "SZSE"]})
    uf = resolve_universe_frame(spec, db, ["2024-03-01", "2024-03-04"])
    a = uf.filter(pl.col("code") == "000001").sort("date")
    assert a.height == 2                            # 每日期仅 1 行（无膨胀）
    assert a.group_by(["date", "code"]).len().filter(pl.col("len") > 1).height == 0
    st = {str(r["date"]): (bool(r["is_st"]), bool(r["in_universe"]))
          for r in a.iter_rows(named=True)}
    assert st["2024-03-01"] == (True, False)        # 重复行 → is_st=true → inactive
    assert st["2024-03-04"] == (False, True)        # 无 ST 行 → active
    db.close()


def test_duplicate_st_identical_payload_no_blowup(tmp_path):
    """同 key 两条完全相同的 ST 行——同样 1 行 is_st=true。"""
    db = build_db(tmp_path, st_rows=[
        ("000001.SZ", "ST平安", "20240301", "ST", "实施风险警示"),
        ("000001.SZ", "ST平安", "20240301", "ST", "实施风险警示"),
    ])
    spec = spec_with(rules={"exclude_st": True, "exchanges": ["SSE", "SZSE"]})
    uf = resolve_universe_frame(spec, db, ["2024-03-01"])
    a = uf.filter((pl.col("code") == "000001") & (pl.col("date") == datetime.date(2024, 3, 1)))
    assert a.height == 1 and a["is_st"][0] == True and a["in_universe"][0] == False
    db.close()


# ================================================================
# M6-07B4：UniverseFrame rules 路径排除 legacy vendor aliases
# ================================================================

def _build_db_with_aliases(tmp_path):
    """canonical 000001.SZ/600018.SH + legacy aliases（老 list_date、无 delist_date）。
    保护：即使 alias 有历史 list_date 且无 delist_date，也不得进入 research universe。"""
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE stock_basic (ts_code VARCHAR, symbol VARCHAR, exchange VARCHAR, list_date VARCHAR, industry VARCHAR, market VARCHAR, delist_date VARCHAR)")
    db.execute("""INSERT INTO stock_basic VALUES
        ('000001.SZ', '000001', 'SZSE', '19910403', '银行', '主板', NULL),
        ('600018.SH', '600018', 'SSE', '20061026', '港口', '主板', NULL),
        ('T600018.SH', 'T600018', 'SSE', '20000719', '港口', '主板', NULL),
        ('TS0018.SH', 'TS0018', 'SSE', '20000719', '港口', '主板', NULL)""")
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
    db.execute("CREATE TABLE trade_cal (exchange VARCHAR, cal_date VARCHAR, is_open BIGINT)")
    return db


def test_universe_frame_rules_excludes_legacy_aliases(tmp_path):
    """§13 invariant：T600018/TS0018 绝不进 candidate_codes / UniverseFrame.code。"""
    db = _build_db_with_aliases(tmp_path)
    spec = spec_with(rules={"exchanges": ["SSE", "SZSE"]})
    codes = resolve_candidate_codes(spec, db)
    assert codes == ["000001", "600018"]
    uf = resolve_universe_frame(spec, db, DATES)
    assert "T600018" not in uf["code"].to_list()
    assert "TS0018" not in uf["code"].to_list()
    assert {"000001", "600018"} <= set(uf["code"].to_list())
    db.close()


# ================================================================
# M6-07C1：稀疏 PIT Universe DataFrame 构造（显式 dtype，不依赖推断）
# ================================================================

def _build_db_sparse(tmp_path, with_st: bool = True, n_listed: int = 150,
                     with_delisted: bool = True) -> duckdb.DuckDBPyConnection:
    """151 canonical stocks：150 L（delist null）+ 999999.SZ D（delist 20020614）。
    候选排序（resolve_candidate_codes 返回 sorted）保证 D 股最后——前 150 行
    delist_date 全 null，第 151 行出现非 null（复现生产分布：非 null 首现于
    Polars 默认 100 行推断窗口之后）。"""
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE stock_basic (ts_code VARCHAR, symbol VARCHAR, exchange VARCHAR,"
               " list_date VARCHAR, industry VARCHAR, market VARCHAR, delist_date VARCHAR)")
    rows = [(f"{i:06d}.SZ", f"{i:06d}", "SZSE", "20240101", "银行", "主板", None)
            for i in range(1, n_listed + 1)]
    if with_delisted:
        rows.append(("999999.SZ", "999999", "SZSE", "20000101", "地产", "主板", "20020614"))
    db.executemany("INSERT INTO stock_basic VALUES (?,?,?,?,?,?,?)", rows)
    if with_st:
        db.execute("CREATE TABLE stock_st (ts_code VARCHAR, name VARCHAR, trade_date VARCHAR,"
                   " type VARCHAR, type_name VARCHAR)")
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
    db.execute("CREATE TABLE trade_cal (exchange VARCHAR, cal_date VARCHAR, is_open BIGINT)")
    return db


DATES_SPARSE = ["2002-06-13", "2002-06-14", "2002-06-15", "2024-01-10"]


def test_sparse_delist_construction_150_leading_nulls(tmp_path):
    """生产分布复现：≥150 前导 null 后出现 delist 值——构造不得崩溃。

    UniverseFrame 最终输出裁剪为 7 列，delist_date 的 String dtype 通过
    行为级验证：后续 strptime 解析成功（999999 的 PIT is_listed 正确）即
    证明构造边界 delist_date 为 String（Null dtype 会 str.strptime 崩溃）。
    """
    db = _build_db_sparse(tmp_path)
    spec = spec_with(rules={"exchanges": ["SSE", "SZSE"]})
    uf = resolve_universe_frame(spec, db, DATES_SPARSE)
    assert uf["date"].dtype == pl.Date
    assert uf["code"].dtype == pl.String
    assert uf["is_st"].dtype == pl.Boolean
    assert uf["exchange"].dtype == pl.String
    assert uf["is_listed"].dtype == pl.Boolean
    # 晚 D 股（第 151 行，非 null delist）PIT 正确——delist_date 值被精确解析
    d = uf.filter((pl.col("code") == "999999") & (pl.col("date") == datetime.date(2002, 6, 13)))
    assert d["is_listed"][0] is True
    db.close()


def test_sparse_delist_pit_semantics_unchanged(tmp_path):
    """晚 D 股 PIT：date<delist → listed；date>=delist → 不 listed。"""
    db = _build_db_sparse(tmp_path)
    uf = resolve_universe_frame(spec_with(rules={"exchanges": ["SSE", "SZSE"]}),
                                db, DATES_SPARSE)
    d = uf.filter(pl.col("code") == "999999")
    expect = {
        datetime.date(2002, 6, 13): True,    # pre-delist
        datetime.date(2002, 6, 14): False,   # == delist
        datetime.date(2002, 6, 15): False,   # post-delist
        datetime.date(2024, 1, 10): False,   # 长期退市
    }
    for day, listed in expect.items():
        row = d.filter(pl.col("date") == day)
        assert row["is_listed"][0] == listed, f"{day}: {listed}"
    db.close()


def test_all_null_delist_date_stays_string(tmp_path):
    """全 null delist_date：dtype 必须 String（旧库/无退市子集锁定），不推断 Null。"""
    db = _build_db_sparse(tmp_path, with_delisted=False)
    uf = resolve_universe_frame(spec_with(rules={"exchanges": ["SSE", "SZSE"]}),
                                db, ["2024-01-10"])
    # 全 null delist 构造成功 + is_listed 正常（后续 strptime 对 null 幂等——
    # Null dtype 会在 str.strptime 崩溃，构造成功即证明 String）
    assert uf.height == 150
    assert uf["is_listed"].null_count() == 0
    assert uf["is_listed"].all()
    db.close()


def test_unmatched_candidate_nullable_text_stays_string(tmp_path):
    """显式 candidate_codes 不在 stock_basic：ts_code/list_date/delist null 但 dtype String。"""
    db = _build_db_sparse(tmp_path, n_listed=3, with_delisted=False)
    uf = resolve_universe_frame(spec_with(rules={}), db, ["2024-01-10"],
                                candidate_codes=["600519"])
    # 构造成功即证明中间可空文本列（ts_code/list_date/delist_date）非 Null dtype
    # （Null dtype 会在后续 strptime 操作崩溃）；未匹配行保留、is_listed=false
    row = uf.filter(pl.col("code") == "600519")
    assert row.height == 1
    assert row["is_listed"][0] is False
    assert uf["is_listed"].dtype == pl.Boolean
    db.close()


def test_has_st_false_keeps_is_st_boolean(tmp_path):
    """无 stock_st 表：is_st 仍 Boolean、全 null（行为不变）。"""
    db = _build_db_sparse(tmp_path, with_st=False, n_listed=3, with_delisted=False)
    uf = resolve_universe_frame(spec_with(rules={"exchanges": ["SSE", "SZSE"]}),
                                db, ["2024-01-10"])
    assert uf["is_st"].dtype == pl.Boolean
    assert uf["is_st"].null_count() == uf.height
    db.close()


def test_has_st_true_sparse_is_st_boolean(tmp_path):
    """has_st=true 且 ST 表为空：is_st 仍显式 Boolean（不得依赖推断）。"""
    db = _build_db_sparse(tmp_path, with_st=True, n_listed=3, with_delisted=False)
    uf = resolve_universe_frame(spec_with(rules={"exchanges": ["SSE", "SZSE"]}),
                                db, ["2024-01-10"])
    assert uf["is_st"].dtype == pl.Boolean
    # 空 ST 表：presence join 产生 false（NULL IS NOT NULL → false），非 null
    assert uf["is_st"].null_count() == 0
    assert not uf["is_st"].any()
    db.close()
