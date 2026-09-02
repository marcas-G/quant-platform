"""M8-06B：backtest runtime——编排已关闭 execution primitives → BacktestResult。

- run_backtest 只做 orchestration（schedule/orders/assessment/fills/state/
  accounting/overnight/valuation 全复用；零新 execution math）
- MarksPolicy v1 = OPEN_BASED（每 execution date 用当日 raw open 标记
  holdings；缺 open evidence → ExecutionDataQualityError——无 stale policy）
- memory-only runtime object（无 persistence/DB 写入）
"""

import datetime
import inspect
import re
from pathlib import Path

import duckdb
import polars as pl
import pytest

from factorlab.domain import (ExecutionDataQualityError,
                              PortfolioStatePhase, TargetPortfolio,
                              TargetPortfolioMeta)
from factorlab.domain.timing import DEFAULT_EOD_SIGNAL_TIMING
from factorlab.execution import (ExecutionSpec, MarksPolicy, run_backtest)

D1 = datetime.date(2024, 1, 2)    # Tue
D2 = datetime.date(2024, 1, 3)    # Wed
D3 = datetime.date(2024, 1, 4)    # Thu
D8 = datetime.date(2024, 1, 8)    # next Mon
EX1, EX2 = D2, D3                 # decisions D1→EX D2, D2→EX D3


def _cal_db(tmp_path, opens):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect(tmp_path / "b.duckdb")
    db.execute("CREATE TABLE trade_cal (cal_date VARCHAR, is_open INT)")
    for d, o in opens:
        db.execute("INSERT INTO trade_cal VALUES (?,?)", (d.strftime("%Y%m%d"), o))
    db.execute("""CREATE TABLE stock_basic (ts_code VARCHAR, symbol VARCHAR,
        market VARCHAR)""")
    for c, m in (("000001.SZ", "主板"), ("600000.SH", "主板")):
        db.execute("INSERT INTO stock_basic VALUES (?,?,?)", (c, c[:6], m))
    db.execute("CREATE TABLE daily (trade_date VARCHAR, ts_code VARCHAR, "
               "open DOUBLE, pre_close DOUBLE)")
    db.execute("CREATE TABLE stk_limit (trade_date VARCHAR, ts_code VARCHAR, "
               "up_limit DOUBLE, down_limit DOUBLE)")
    db.execute("CREATE TABLE suspend_d (trade_date VARCHAR, ts_code VARCHAR, "
               "suspend_type VARCHAR, suspend_timing VARCHAR)")
    for row in opens or []:
        pass
    return db


def _add_daily(db, date, code, open_):
    up, dn = round(open_ * 1.1, 4), round(open_ * 0.9, 4)
    db.execute("INSERT INTO daily VALUES (?,?,?,?)",
               (date.strftime("%Y%m%d"), code, open_, open_))
    db.execute("INSERT INTO stk_limit VALUES (?,?,?,?)",
               (date.strftime("%Y%m%d"), code, up, dn))


def _db(tmp_path):
    db = _cal_db(tmp_path, [(D1, 1), (D2, 1), (D3, 1),
                            (datetime.date(2024, 1, 5), 1), (D8, 1),
                            (datetime.date(2024, 1, 9), 1)])
    _add_daily(db, D2, "000001.SZ", 10.0)
    _add_daily(db, D2, "600000.SH", 20.0)
    _add_daily(db, D3, "000001.SZ", 11.0)
    _add_daily(db, D3, "600000.SH", 21.0)
    _add_daily(db, D8, "000001.SZ", 12.0)
    _add_daily(db, D8, "600000.SH", 22.0)
    db.close()
    return tmp_path / "b.duckdb"


def _target(dates=(D1, D2), weights=None):
    """dates: (decision, {code: weight})；默认 D1/D2 各 0.5/0.5。"""
    rows = []
    for d, wm in (weights or [(D1, {"000001.SZ": 0.5, "600000.SH": 0.5}),
                              (D2, {"000001.SZ": 1.0})]):
        for c, w in sorted(wm.items()):
            rows.append((d, c, w))
    if dates:
        rows = [r for r in rows if r[0] in dates]
    frame = pl.DataFrame(rows, schema=["decision_date", "code",
                                       "target_weight"], orient="row")
    frame = frame.with_columns(pl.col("decision_date").cast(pl.Date),
                               pl.col("code").cast(pl.String),
                               pl.col("target_weight").cast(pl.Float64))
    return TargetPortfolio(frame=frame, decision_dates=tuple(sorted(set(dates))),
                           meta=TargetPortfolioMeta(
                               strategy_name="strat_x",
                               source_signal_name="alpha_x",
                               source_timing=DEFAULT_EOD_SIGNAL_TIMING,
                               gross_exposure=1.0))


def _run(target=None, db_path=None, **over):
    spec = ExecutionSpec.model_validate({"initial_cash": 1_000_000.0})
    return run_backtest(target if target is not None else _target(),
                        spec, db_path if db_path is not None else "FIXME",
                        **over)


# ================================================================
# API / guards
# ================================================================

def test_api_exists():
    assert callable(run_backtest)
    assert MarksPolicy.OPEN_BASED.value == "open_based"


def test_type_guards(tmp_path):
    db = _db(tmp_path)
    spec = ExecutionSpec.model_validate({})
    with pytest.raises(TypeError, match="target"):
        run_backtest({"x": 1}, spec, db)
    with pytest.raises(TypeError, match="execution_spec"):
        run_backtest(_target(), {"c": 1}, db)
    with pytest.raises(TypeError, match="db_path"):
        run_backtest(_target(), spec, str(db))


def test_caller_explicit_marks_not_implemented(tmp_path):
    with pytest.raises(NotImplementedError, match="OPEN_BASED|caller"):
        _run(db_path=_db(tmp_path), marks="caller_explicit")


def test_no_strategy_params():
    params = inspect.signature(run_backtest).parameters
    for forbidden in ("signal", "strategy_spec", "universe"):
        assert forbidden not in params


# ================================================================
# single / multi-event runs
# ================================================================

def test_single_event_run(tmp_path):
    """单 decision：buy 0.5/0.5 @ D2 opens → artifact 1、NAV 1 行。"""
    db = _db(tmp_path)
    t = _target(dates=(D1,))
    r = _run(target=t, db_path=db)
    assert len(r.artifacts) == 1
    a = r.artifacts[0]
    assert a.decision_date == D1 and a.execution_date == D2
    assert a.fills.frame.height == 2
    assert a.post_state.phase is PortfolioStatePhase.POST_EXECUTION
    assert a.accounting.cash_before == 1_000_000.0
    assert a.accounting.cash_after == 0.0
    assert a.accounting.net_cash_delta == -1_000_000.0
    # NAV @ D2 open marks：cash 0 + 50,000×10 + 25,000×20 = 1,000,000
    assert a.nav.nav == 1_000_000.0
    assert r.nav_series.frame.height == 1
    row = r.nav_series.frame.row(0)
    assert row[1] == 0.0 and row[3] == 1_000_000.0
    # final state = PRE at D3
    assert r.final_state.as_of_date == D3
    assert r.final_state.phase is PortfolioStatePhase.PRE_EXECUTION


def test_multi_event_rebalance(tmp_path):
    """D1→D2 buy 0.5/0.5；D2→D3 rebalance to 000001-only（sell 600000）。
    T+1：600000 在 D2 买入 → D3 可卖（隔夜释放）。"""
    db = _db(tmp_path)
    r = _run(db_path=db)
    assert len(r.artifacts) == 2
    a2 = r.artifacts[1]
    assert a2.decision_date == D2 and a2.execution_date == D3
    sides = a2.orders.orders["side"].to_list()
    assert sides == ["buy", "sell"]      # 000001 buy、600000 sell（code ASC）
    assert a2.accounting.cash_after == 300.0
    r1 = r.artifacts[0].nav.nav
    r2 = a2.nav.nav
    assert r1 == 1_000_000.0
    assert r2 == 1_075_000.0             # 550k+525k @11/21
    assert r.nav_series.frame.height == 2
    assert r.final_state.as_of_date == datetime.date(2024, 1, 5)


def test_weekly_gap_redate(tmp_path):
    """decisions D1(exec 1/3) 与 D5=1/5 all-cash(exec D8=1/8)：
    1/3 后 advance→1/4，再 re-date→1/8；D1 买入的持仓在 D8 全部清算。"""
    db = _db(tmp_path)
    D5 = datetime.date(2024, 1, 5)
    t = _target(dates=(D1, D5), weights=[
        (D1, {"000001.SZ": 0.5, "600000.SH": 0.5}), (D5, {})])
    r = _run(target=t, db_path=db)
    assert len(r.artifacts) == 2
    a1, a2 = r.artifacts
    assert a2.execution_date == D8
    # 两笔 SELL（000001/600000 全清）——T+1：1/3 买入 600000 在 1/8 可卖
    assert a2.orders.orders["side"].to_list() == ["sell", "sell"]
    assert a1.nav.nav == 1_000_000.0
    # D8: SELL @12/22 → cash = 600,000 + 550,000 = 1,150,000
    assert a2.accounting.cash_after == 1_150_000.0
    assert a2.nav.nav == 1_150_000.0


def test_empty_event_day(tmp_path):
    """现金账户 + all-cash decision → empty orders/fills、cash 不变。"""
    db = _db(tmp_path)
    D5 = datetime.date(2024, 1, 5)
    t = _target(dates=(D5,), weights=[(D5, {})])
    r = _run(target=t, db_path=db)
    assert len(r.artifacts) == 1
    a = r.artifacts[0]
    assert a.execution_date == D8          # D5(Fri) → D8(Mon)
    assert a.orders.orders.height == 0
    assert a.fills.frame.height == 0
    assert a.accounting.net_cash_delta == 0.0
    assert a.accounting.cash_after == a.accounting.cash_before == 1_000_000.0
    assert a.nav.nav == 1_000_000.0


def test_decision_range(tmp_path):
    db = _db(tmp_path)
    r = _run(db_path=db, decision_range=(D2, D2))
    assert len(r.artifacts) == 1
    assert r.artifacts[0].decision_date == D2


def test_decision_range_empty_fails(tmp_path):
    db = _db(tmp_path)
    with pytest.raises(ValueError, match="decision"):
        _run(db_path=db, decision_range=(datetime.date(2024, 5, 1),
                                         datetime.date(2024, 5, 2)))


# ================================================================
# marks / data gates
# ================================================================

def test_missing_open_mark_fails(tmp_path):
    """POST 持仓证券在 execution date 无 open evidence（停牌且无 daily row、
    SELL 被 blocked 仍持有）→ marks 无法构造 → ExecutionDataQualityError。"""
    db = _db(tmp_path)
    con = duckdb.connect(db)
    con.execute("DELETE FROM daily WHERE trade_date='20240104' AND ts_code='600000.SH'")
    con.execute("DELETE FROM stk_limit WHERE trade_date='20240104' AND ts_code='600000.SH'")
    con.execute("INSERT INTO suspend_d VALUES ('20240104','600000.SH','S',NULL)")
    con.close()
    t = _target(dates=(D1, D2), weights=[
        (D1, {"600000.SH": 1.0}), (D2, {})])   # 1/3 买 600000；1/4 停牌+all-cash
    with pytest.raises(ExecutionDataQualityError, match="mark|open"):
        _run(target=t, db_path=db)


def test_determinism(tmp_path):
    db = _db(tmp_path)
    a = _run(db_path=db)
    b = _run(db_path=db)
    assert len(a.artifacts) == len(b.artifacts)
    for x, y in zip(a.artifacts, b.artifacts):
        assert x.post_state.cash == y.post_state.cash
        assert x.post_state.positions.equals(y.post_state.positions)
        assert x.fills.frame.equals(y.fills.frame)
        assert x.nav.nav == y.nav.nav
    assert a.nav_series.frame.equals(b.nav_series.frame)
    assert a.final_state.positions.equals(b.final_state.positions)


def test_no_db_writes(tmp_path):
    db = _db(tmp_path)
    before = {t: duckdb.connect(db).execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("daily", "stk_limit", "suspend_d", "stock_basic")}
    _run(db_path=db)
    after = {t: duckdb.connect(db).execute(f"SELECT count(*) FROM {t}").fetchone()[0]
             for t in ("daily", "stk_limit", "suspend_d", "stock_basic")}
    assert before == after


def test_source_audit_no_strategy_engine():
    from factorlab.execution import backtest as mod
    src = inspect.getsource(mod)
    for forbidden in ("strategy", "engine", "SignalArtifact", "StrategySpec",
                      "duckdb"):
        assert not re.search(rf"^\s*(import|from)\s+[^\s]*{forbidden}", src,
                             re.M), f"backtest.py 不得 import {forbidden}"
