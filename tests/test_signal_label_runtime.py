"""M6-03：Universe-Aware Signal/Label Runtime——run_factor 级集成测试（Test 5-12 + align_to_listing）。

核心 invariant：
- Signal Runtime 绝不读取 forward/future 数据；Label Runtime 独立计算 labels
- t 的 label 不因 t+h 的未来 universe membership 改变而被 censor
- legacy panel 保持 CLI/eval 兼容
"""

import datetime

import duckdb
import polars as pl
import pytest

from factorlab.data.calendar import fill_suspensions, trading_calendar
from factorlab.data.source import load_daily
from factorlab.data.universe import align_to_listing, resolve_universe_frame
from factorlab.engine.compute import (FactorResult, RunContext, _formula_columns,
                                      compute_formula, fill_suspension_values, run_factor)
from factorlab.engine.forward import compute_forward_returns
from factorlab.data.adjust import view_prices
from factorlab.process.registry import run_process_chain
from factorlab.spec import FactorSpec

DATES = ["20240102", "20240103", "20240104", "20240105", "20240108",
         "20240109", "20240110", "20240111"]


def build_db(path, close_seq: dict[str, list[float]] | None = None,
             st_rows: list[tuple] | None = None) -> duckdb.DuckDBPyConnection:
    """平台库 fixture：A/B/C 全程 listed（2024-01-01 上市）、8 个交易日。"""
    db = duckdb.connect(str(path))
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, "
               "low DOUBLE, close DOUBLE, vol DOUBLE, amount DOUBLE)")
    seq = close_seq or {
        "000001": [10.0 + i for i in range(8)],
        "000002": [20.0 + i for i in range(8)],
        "000003": [5.0 + i for i in range(8)],
    }
    for code, closes in seq.items():
        rows = []
        for i, d in enumerate(DATES):
            c = closes[i]
            rows.append((f"{code}.SZ", d, c, c * 1.01, c * 0.99, c, 1e6, c * 1e6))
        db.executemany("INSERT INTO daily VALUES (?,?,?,?,?,?,?,?)", rows)
    db.execute("CREATE TABLE adj_factor (ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
    for code in seq:
        db.executemany("INSERT INTO adj_factor VALUES (?,?,?)",
                       [(f"{code}.SZ", d, 1.0) for d in DATES])
    db.execute("CREATE TABLE trade_cal (exchange VARCHAR, cal_date VARCHAR, is_open BIGINT)")
    db.executemany("INSERT INTO trade_cal VALUES ('SSE', ?, 1)", [(d,) for d in DATES])
    db.execute("CREATE TABLE stock_basic (ts_code VARCHAR, symbol VARCHAR, exchange VARCHAR, "
               "list_date VARCHAR, industry VARCHAR, market VARCHAR, delist_date VARCHAR)")
    for code in seq:
        db.execute("INSERT INTO stock_basic VALUES (?,?,?,?,?,?,?)",
                   (f"{code}.SZ", code, "SZSE", "20240101", "x", "主板", None))
    db.execute("CREATE TABLE stock_st (ts_code VARCHAR, name VARCHAR, trade_date VARCHAR, "
               "type VARCHAR, type_name VARCHAR)")
    for r in (st_rows or []):
        db.execute("INSERT INTO stock_st VALUES (?,?,?,?,?)", r)
    return db


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "t.duckdb"
    conn = build_db(p)
    conn.close()
    return p


def spec_with(formula: str = "signal = close", **universe_kwargs) -> FactorSpec:
    uni = universe_kwargs or {"rules": {"exchanges": ["SSE", "SZSE"]}}
    return FactorSpec.model_validate({
        "name": "demo", "category": "custom", "direction": 1,
        "date": {"start": "2024-01-02", "end": "2024-01-11"},
        "universe": uni, "formula": formula,
    })


def _run(tmp_path, db, spec, formula=None):
    ctx = RunContext(db_path=tmp_path / "t.duckdb", output_dir=tmp_path / "out")
    return run_factor(spec_with(formula or spec.formula, **spec.universe.model_dump()), ctx)


# ================================================================
# Test 5 — process isolation（run_factor 级）
# ================================================================

def test_process_isolation(tmp_path):
    """A/B active、C inactive 极端 signal——standardize 必须与只有 A/B 时一致。"""
    seq = {"000001": [1.0] * 8, "000002": [2.0] * 8, "000003": [1000.0] * 8}
    db = build_db(tmp_path / "t.duckdb", close_seq=seq,
                  st_rows=[("000003.SZ", "STC", "20240102", "ST", "x"),
                           ("000003.SZ", "STC", "20240111", "ST", "x")])  # coverage 覆盖全部 dates
    db.close()
    ctx = RunContext(db_path=tmp_path / "t.duckdb", output_dir=tmp_path / "out")
    spec3 = spec_with(formula="signal = close",
                      rules={"exclude_st": True, "exchanges": ["SSE", "SZSE"]})
    r3 = run_factor(spec3, ctx)
    spec2 = spec_with(formula="signal = close",
                      codes=["000001", "000002"])
    r2 = run_factor(spec2, ctx)
    for c in ("000001", "000002"):
        v3 = r3.panel.filter(pl.col("code") == c).sort("date")["signal"].to_list()
        v2 = r2.panel.filter(pl.col("code") == c).sort("date")["signal"].to_list()
        assert v3 == v2, f"{c}: 3 股 process 结果 {v3} != 2 股 {v2}（C 污染 process）"
    db.close()


# ================================================================
# Test 6 — future close 改变 label、不改变 signal
# ================================================================

def test_future_close_changes_label_not_signal(tmp_path):
    base = {"000001": [10.0 + i for i in range(8)], "000002": [20.0 + i for i in range(8)]}
    alt = dict(base)
    alt["000001"] = [10.0, 11.0, 12.0, 13.0, 14.0, 100.0, 16.0, 17.0]  # t+5 close 改 100
    (tmp_path / "db1").mkdir()
    (tmp_path / "db2").mkdir()
    db1 = build_db(tmp_path / "db1" / "t.duckdb", close_seq=base)
    db1.close()
    db2 = build_db(tmp_path / "db2" / "t.duckdb", close_seq=alt)
    db2.close()
    ctx1 = RunContext(db_path=tmp_path / "db1" / "t.duckdb", output_dir=tmp_path / "o1")
    ctx2 = RunContext(db_path=tmp_path / "db2" / "t.duckdb", output_dir=tmp_path / "o2")
    spec = spec_with(formula="signal = ts_mean(close, 2)")   # 只依赖过去——future 无关
    r1 = run_factor(spec, ctx1)
    r2 = run_factor(spec, ctx2)
    s1 = r1.panel.filter(pl.col("code") == "000001").sort("date")["signal"].to_list()
    s2 = r2.panel.filter(pl.col("code") == "000001").sort("date")["signal"].to_list()
    # 1/2..1/8（future close 之前）的 signal 不得受 t+5 价格影响（ts_mean 只依赖过去）
    assert s1[:5] == s2[:5], f"future close 改变了未来日期之前的 signal：{s1[:5]} vs {s2[:5]}"
    l1 = r1.label_artifact.frame.filter(pl.col("code") == "000001").sort("date")
    l2 = r2.label_artifact.frame.filter(pl.col("code") == "000001").sort("date")
    f5_1 = l1["forward_return_5d"].to_list()
    f5_2 = l2["forward_return_5d"].to_list()
    assert f5_1[0] != f5_2[0], "future close 未改变 label（1/2 的 forward_return_5d）"
    db1.close(); db2.close()


# ================================================================
# Test 7 — future membership 不 censor label
# ================================================================

def test_future_membership_does_not_censor_label(tmp_path):
    """A 在 1/2 active、2/2 起 ST（inactive）——t=1/2 的 label 仍正常计算。"""
    db_path = tmp_path / "t.duckdb"
    conn = build_db(db_path, st_rows=[
        ("000002.SZ", "STB", "20240102", "ST", "x"),      # coverage 起点 = 1/2
        ("000001.SZ", "STA", "20240109", "ST", "x"),      # A 从 1/9 起 ST
        ("000001.SZ", "STA", "20240111", "ST", "x"),      # coverage 覆盖到 1/11
    ])
    conn.close()
    ctx = RunContext(db_path=db_path, output_dir=tmp_path / "out")
    spec = spec_with(rules={"exclude_st": True, "exchanges": ["SSE", "SZSE"]})
    r = run_factor(spec, ctx)
    # A 在 1/2 active（非 ST）→ label 存在且非 null（价格到 1/9）
    a = r.label_artifact.frame.filter(pl.col("code") == "000001").sort("date")
    first = a.filter(pl.col("date") == datetime.date(2024, 1, 2))
    assert first.height == 1 and first["forward_return_5d"][0] is not None
    # A 在 1/9 当天 ST → signal 无 A（未来 membership 影响 signal 正常——逐日 PIT）
    sig = r.signal_artifact.frame
    assert sig.filter((pl.col("code") == "000001")
                      & (pl.col("date") == datetime.date(2024, 1, 9))).height == 0
    # 但 1/2 的 label 未被未来 membership censor
    assert r.label_artifact.frame.filter(
        (pl.col("code") == "000001") & (pl.col("date") == datetime.date(2024, 1, 2))).height == 1


# ================================================================
# Test 8 — formula future input guard
# ================================================================

@pytest.mark.parametrize("bad_formula", [
    "signal = forward_return_5d",
    "signal = forward_price",
    "signal = future_close",
    "signal = target",
    "signal = label",
])
def test_formula_future_input_guard(tmp_path, db_path, bad_formula):
    ctx = RunContext(db_path=db_path, output_dir=tmp_path / "out")
    with pytest.raises(ValueError, match="future/label inputs are forbidden"):
        run_factor(spec_with(formula=bad_formula), ctx)


# ================================================================
# Test 9/10/11 — artifact contracts + legacy panel
# ================================================================

def test_artifact_contracts(tmp_path, db_path):
    ctx = RunContext(db_path=db_path, output_dir=tmp_path / "out")
    r = run_factor(spec_with(), ctx)
    sa = r.signal_artifact
    assert {"date", "code", "signal"} <= set(sa.frame.columns)
    assert sa.frame.schema["date"] == pl.Date and sa.frame.schema["code"] == pl.String
    assert sa.frame.group_by(["date", "code"]).len().filter(pl.col("len") > 1).height == 0
    for c in sa.frame.columns:
        assert not (c.startswith("forward_") or c.startswith("future_")
                    or c in ("target", "label")), f"SignalArtifact 含未来列 {c}"
    la = r.label_artifact
    assert {"date", "code", "forward_return_5d", "forward_return_20d"} <= set(la.frame.columns)
    assert "signal" not in la.frame.columns
    # legacy panel 兼容
    assert {"date", "code", "signal", "forward_return_5d", "forward_return_20d", "close"} \
        <= set(r.panel.columns)


def test_factor_result_fields(tmp_path, db_path):
    ctx = RunContext(db_path=db_path, output_dir=tmp_path / "out")
    r = run_factor(spec_with(), ctx)
    assert isinstance(r, FactorResult)
    assert r.signal_artifact.frame.height == r.panel.height
    assert r.summary["runtime_semantics"] == "pit_universe_signal_label_v1"
    assert r.summary["candidate_count"] == 3
    assert r.summary["signal_rows"] == r.panel.height


# ================================================================
# Test 12 — 静态兼容（全程 listed、无动态排除 → 与 legacy 路径一致）
# ================================================================

def test_static_compatibility_legacy_reference(tmp_path, db_path):
    """所有股票全程 listed + 无动态排除——M6-03 signal 与 legacy 路径逐值一致。"""
    spec = spec_with()
    ctx = RunContext(db_path=db_path, output_dir=tmp_path / "out")
    r = run_factor(spec, ctx)
    # legacy reference（旧路径：fill_suspensions → forward → fill → view → formula(无 mask) → process）
    with duckdb.connect(str(ctx.db_path), read_only=True) as con:
        from factorlab.data.universe import resolve_codes
        codes = resolve_codes(spec, con)
        cal = trading_calendar(ctx.db_path, date_start=spec.date.start, date_end=spec.date.end)
        raw = load_daily(ctx.db_path, codes, date_start=spec.date.start, date_end=spec.date.end,
                         cols=_formula_columns("signal = close") + ["close", "adj_factor"],
                         float32=False).collect()
        panel = fill_suspensions(raw, cal)
        panel = compute_forward_returns(panel)
        panel = fill_suspension_values(panel)
        panel = view_prices(panel, "qfq")
        panel = panel.join(compute_formula(panel, "signal = close"), on=["date", "code"], how="left")
        panel = run_process_chain(panel, spec.process, ctx=con)
    legacy = panel.sort(["date", "code"])
    new = r.panel.sort(["date", "code"])
    assert legacy["signal"].to_list() == new["signal"].to_list(), "静态兼容失败"


# ================================================================
# align_to_listing（6 项）
# ================================================================

def _listing_uf(db, dates):
    spec = spec_with(rules={"exchanges": ["SSE", "SZSE"]})
    return resolve_universe_frame(spec, db, dates)


def test_align_listing_basic(tmp_path):
    db = build_db(tmp_path / "t.duckdb")
    uf = _listing_uf(db, ["2024-01-02", "2024-01-03"])
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2)], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "close": pl.Series([10.0], dtype=pl.Float64),
    })
    out = align_to_listing(raw, uf)
    a = out.filter((pl.col("date") == datetime.date(2024, 1, 2)) & (pl.col("code") == "000001"))
    assert a["close"][0] == 10.0                     # listed + raw 存在 → 行情
    b = out.filter((pl.col("date") == datetime.date(2024, 1, 2)) & (pl.col("code") == "000002"))
    assert b["close"][0] is None                     # listed + raw 缺失 → null 保留
    db.close()


def test_align_listing_pre_post_delist(tmp_path):
    db = build_db(tmp_path / "t.duckdb")
    db.execute("UPDATE stock_basic SET list_date='20240105' WHERE symbol='000001'")   # A 1/5 上市
    db.execute("UPDATE stock_basic SET delist_date='20240108' WHERE symbol='000002'")  # B 1/8 退市
    uf = _listing_uf(db, ["2024-01-02", "2024-01-09"])
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2), datetime.date(2024, 1, 9)], dtype=pl.Date),
        "code": pl.Series(["000001", "000002"], dtype=pl.String),
        "close": pl.Series([1.0, 2.0], dtype=pl.Float64),
    })
    out = align_to_listing(raw, uf)
    assert out.filter((pl.col("code") == "000001") & (pl.col("date") == datetime.date(2024, 1, 2))).height == 0  # pre-list
    assert out.filter((pl.col("code") == "000002") & (pl.col("date") == datetime.date(2024, 1, 9))).height == 0  # post-delist
    assert out.filter((pl.col("code") == "000001") & (pl.col("date") == datetime.date(2024, 1, 9))).height == 1
    db.close()


def test_align_listing_duplicate_fail_fast(tmp_path):
    db = build_db(tmp_path / "t.duckdb")
    uf = _listing_uf(db, ["2024-01-02"])
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2), datetime.date(2024, 1, 2)], dtype=pl.Date),
        "code": pl.Series(["000001", "000001"], dtype=pl.String),
        "close": pl.Series([1.0, 2.0], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="unique"):
        align_to_listing(raw, uf)
    db.close()


def test_align_listing_code_non_string_fail(tmp_path):
    db = build_db(tmp_path / "t.duckdb")
    uf = _listing_uf(db, ["2024-01-02"])
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2)], dtype=pl.Date),
        "code": pl.Series([1], dtype=pl.Int64),
        "close": pl.Series([1.0], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="String"):
        align_to_listing(raw, uf)
    db.close()


def test_align_listing_missing_is_listed_fail(tmp_path):
    db = build_db(tmp_path / "t.duckdb")
    uf = _listing_uf(db, ["2024-01-02"]).drop("is_listed")
    raw = pl.DataFrame({
        "date": pl.Series([datetime.date(2024, 1, 2)], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "close": pl.Series([1.0], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="is_listed"):
        align_to_listing(raw, uf)
    db.close()
