"""M6-07C2E：QFQ fixed-base chunk invariance——FULL/CHUNK-120/CHUNK-60 位级一致。

生产发现：qfq 双重复权（÷全局 base + view_prices ÷块内 latest）使复权依赖
chunk 划分（688256 2025-11-14 adj_factor 变化日：CHUNK-120 输出复权价、
CHUNK-60 输出原价）。本测试锁定 runtime qfq 与分块无关。
"""

import datetime

import duckdb
import polars as pl
import pytest
import yaml

from factorlab.engine.compute import RunContext, run_factor
from factorlab.spec import FactorSpec


def _dates(n: int, start="2024-01-02") -> list[str]:
    """n 个交易日（跳过周末）YYYYMMDD 列表。"""
    d = datetime.date.fromisoformat(start)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += datetime.timedelta(days=1)
    return out


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def build_db(tmp_path, n=200, event_day=95, base=1.4912, second_code=False,
             future_only_adj: dict | None = None, trade_cal_days: int | None = None):
    """180+ 交易日 fixture：adj_factor 在 event_day（0-based）从 1.0 → base。

    future_only_adj={"dates": [...], "adj": 2.0}：研究日历（trade_cal）之外的
    adj_factor 行——不得参与 qfq base。
    """
    dates = _dates(n)
    db = duckdb.connect(tmp_path / "q.duckdb")
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, open DOUBLE,"
               " high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE, change DOUBLE,"
               " pct_chg DOUBLE, vol DOUBLE, amount DOUBLE)")
    codes = [("000001", "000001.SZ")]
    if second_code:
        codes.append(("000002", "000002.SZ"))
    for symbol, ts_code in codes:
        for i, d in enumerate(dates):
            close = 10.0 + i * 0.1
            db.execute("INSERT INTO daily VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (ts_code, d, close - 0.5, close + 0.5, close - 1.0, close,
                        close - 0.1, 0.1, 0.01, 1000.0, 1e6))
    db.execute("CREATE TABLE adj_factor (ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
    for symbol, ts_code in codes:
        for i, d in enumerate(dates):
            adj = 1.0 if i < event_day else base
            if second_code and symbol == "000002":
                adj = 1.0 if i < event_day else 3.0
            db.execute("INSERT INTO adj_factor VALUES (?,?,?)", (ts_code, d, adj))
    if future_only_adj:
        for d in future_only_adj["dates"]:
            db.execute("INSERT INTO adj_factor VALUES ('000001.SZ', ?, ?)",
                       (d, future_only_adj["adj"]))
    db.execute("CREATE TABLE stock_basic (symbol VARCHAR, ts_code VARCHAR, exchange VARCHAR,"
               " list_date VARCHAR, industry VARCHAR)")
    db.execute("INSERT INTO stock_basic VALUES ('000001','000001.SZ','SZSE','19910101','银行')")
    if second_code:
        db.execute("INSERT INTO stock_basic VALUES ('000002','000002.SZ','SZSE','19910101','银行')")
    db.execute("CREATE TABLE daily_basic (trade_date VARCHAR, ts_code VARCHAR, total_mv DOUBLE)")
    db.execute("CREATE TABLE stock_st (ts_code VARCHAR, trade_date VARCHAR)")
    db.execute("CREATE TABLE trade_cal (cal_date VARCHAR, is_open INT)")
    for d in dates[:trade_cal_days or n]:
        db.execute("INSERT INTO trade_cal VALUES (?,1)", (d,))
    db.close()


def _spec(tmp_path, formula="signal = close", end: str | None = None,
          adjustment: str = "qfq", second_code: bool = False):
    dates = _dates(200)
    date_block = f'  start: "{_iso(dates[0])}"\n'
    if end is not None:
        date_block += f'  end: "{end}"\n'
    codes = '["000001.SZ"]' if not second_code else '["000001.SZ", "000002.SZ"]'
    spec_yaml = f"""
name: t
category: custom
direction: 1
universe:
  codes: {codes}
date:
{date_block}adjustment: {adjustment}
formula: |
  {formula}
process: []
"""
    path = tmp_path / "spec.yaml"
    path.write_text(spec_yaml, encoding="utf-8")
    return FactorSpec.model_validate(yaml.safe_load(spec_yaml))


def _run(db_path, out_dir, chunk, formula="signal = close", end=None,
         adjustment="qfq", second_code=False):
    ctx = RunContext(db_path=db_path, output_dir=out_dir, chunk_days=chunk,
                     warmup_days=None, adjustment=adjustment)
    spec = _spec(out_dir.parent, formula=formula, end=end, adjustment=adjustment,
                 second_code=second_code)
    return run_factor(spec, ctx).signal_artifact.frame


# ---------------- Test A：signal=close FULL/60/120 strict exact ----------------

def test_signal_close_full_chunk60_chunk120_exact(tmp_path):
    build_db(tmp_path)
    frames = {str(c): _run(tmp_path / "q.duckdb", tmp_path / f"out_{c}", c)
              for c in (None, 60, 120)}
    assert frames["None"].equals(frames["60"]), "FULL != CHUNK-60"
    assert frames["None"].equals(frames["120"]), "FULL != CHUNK-120"
    assert frames["60"].equals(frames["120"]), "CHUNK-60 != CHUNK-120"


# ---------------- Test C：event 边界显式断言 ----------------

def test_adjustment_event_boundary_explicit(tmp_path):
    """event 前/当/后 qfq 数学正确且三模式一致（§18/19：不存在一块输出 raw、另一块输出 qfq）。"""
    build_db(tmp_path)
    dates = _dates(200)
    ev = dates[95]          # event_day=95（0-based）→ 第 96 天是 1.0→1.4912 首日
    prev, cur, nxt = dates[94], dates[95], dates[96]
    frames = {str(c): _run(tmp_path / "q.duckdb", tmp_path / f"o_{c}", c)
              for c in (None, 60, 120)}
    for c, f in frames.items():
        for d, expected_factor in ((prev, 1.0 / 1.4912), (cur, 1.0), (nxt, 1.0)):
            row = f.filter((pl.col("date") == datetime.date.fromisoformat(_iso(d)))
                           & (pl.col("code") == "000001.SZ"))
            raw = 10.0 + dates.index(d) * 0.1
            assert row["signal"][0] == pytest.approx(raw * expected_factor, rel=1e-5), \
                f"{c} {d}: {row['signal'][0]} vs {raw * expected_factor}"
    # 三模式逐行位级一致（覆盖全窗）
    assert frames["None"].equals(frames["60"])
    assert frames["None"].equals(frames["120"])


# ---------------- Test B：signal=adj_factor FULL/CHUNK exact（raw 不被覆盖） ----------------

def test_signal_adj_factor_full_chunk_exact(tmp_path):
    build_db(tmp_path)
    f_full = _run(tmp_path / "q.duckdb", tmp_path / "o_full", None, formula="signal = adj_factor")
    f_c120 = _run(tmp_path / "q.duckdb", tmp_path / "o_c120", 120, formula="signal = adj_factor")
    assert f_full.equals(f_c120), "adj_factor raw 字段被 chunk 覆盖/改写"
    # 值必须是 raw adj_factor（1.0 / 1.4912 原样，非 normalized ratio）
    d0 = _dates(200)[0]
    row = f_full.filter((pl.col("date") == datetime.date.fromisoformat(_iso(d0)))
                        & (pl.col("code") == "000001.SZ"))
    assert row["signal"][0] == 1.0


# ---------------- Test D：multiple codes per-code base ----------------

def test_multiple_codes_per_code_base(tmp_path):
    build_db(tmp_path, second_code=True)
    f = _run(tmp_path / "q.duckdb", tmp_path / "o", None, second_code=True)
    dates = _dates(200)
    prev = dates[94]
    a = f.filter((pl.col("date") == datetime.date.fromisoformat(_iso(prev)))
                 & (pl.col("code") == "000001.SZ"))
    b = f.filter((pl.col("date") == datetime.date.fromisoformat(_iso(prev)))
                 & (pl.col("code") == "000002.SZ"))
    raw_a, raw_b = 10.0 + 94 * 0.1, 10.0 + 94 * 0.1
    assert a["signal"][0] == pytest.approx(raw_a * 1.0 / 1.4912, rel=1e-5)
    assert b["signal"][0] == pytest.approx(raw_b * 1.0 / 3.0, rel=1e-5)


# ---------------- Test E：no-end-date 不读未来 adj ----------------

def test_no_end_date_ignores_future_adj(tmp_path):
    dates = _dates(200)
    # 未来日期（daily/trade_cal 之外的 2025-01 交易日）：库中存在但研究日历外
    future_dates = _dates(20, start="2025-01-02")
    build_db(tmp_path, future_only_adj={"dates": future_dates, "adj": 2.0},
             trade_cal_days=180)
    # spec date.end=None → effective_end = cal[-1]（day 179）
    f = _run(tmp_path / "q.duckdb", tmp_path / "o", None, end=None)
    # day 95+（adj=1.4912）factor = 1.4912/1.4912 = 1.0——若错误用 future 2.0 → 0.7456
    d95 = dates[95]
    row = f.filter((pl.col("date") == datetime.date.fromisoformat(_iso(d95)))
                   & (pl.col("code") == "000001.SZ"))
    raw = 10.0 + 95 * 0.1
    assert row["signal"][0] == pytest.approx(raw, rel=1e-5), \
        f"no-end base 读了未来 adj: {row['signal'][0]} vs {raw}"


# ---------------- §25：non-trading end ----------------

def test_non_trading_end_ok(tmp_path):
    build_db(tmp_path)
    # 2024-12-29 是周日（非交易日），晚于研究窗末——base 取 <= end 的最后 adj
    f = _run(tmp_path / "q.duckdb", tmp_path / "o", None, end="2024-12-29")
    assert f.height > 0
    d95 = _dates(200)[95]
    row = f.filter((pl.col("date") == datetime.date.fromisoformat(_iso(d95)))
                   & (pl.col("code") == "000001.SZ"))
    raw = 10.0 + 95 * 0.1
    assert row["signal"][0] == pytest.approx(raw, rel=1e-5)  # factor=1.0（event 后）
