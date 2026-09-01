"""M8-04E：overnight T+1 inventory release——POST_EXECUTION(D) →
PRE_EXECUTION(next trade_cal open day)。

release 数量 = 当天 FillBatch 中 same-day BUY 的 filled_quantity
（provenance-aware——严禁 sellable=quantity 全量释放，因为 PortfolioState
不记录不可卖库存的原因）。calendar authority = trading_calendar（唯一）。
"""

import datetime
import inspect
import re
from pathlib import Path

import duckdb
import polars as pl
import pytest

from factorlab.domain import (FillBatch, PortfolioState, PortfolioStatePhase)
from factorlab.domain.timing import ExecutionTiming
from factorlab.execution import advance_to_next_trading_day

# 2024-01-05 Friday open；01-06/07 closed；01-08 Monday open
FRI = datetime.date(2024, 1, 5)
MON = datetime.date(2024, 1, 8)
TUE = datetime.date(2024, 1, 9)


def _cal_db(tmp_path, opens):
    """opens: list of (date, is_open)；额外加一个 trailing open 日期保证
    FRI 之后有 next。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect(tmp_path / "c.duckdb")
    db.execute("CREATE TABLE trade_cal (cal_date VARCHAR, is_open INT)")
    for d, o in opens:
        db.execute("INSERT INTO trade_cal VALUES (?,?)", (d.strftime("%Y%m%d"), o))
    db.close()
    return tmp_path / "c.duckdb"


def _default_cal(tmp_path):
    return _cal_db(tmp_path, [(FRI, 1), (datetime.date(2024, 1, 6), 0),
                              (datetime.date(2024, 1, 7), 0), (MON, 1),
                              (TUE, 1)])


def _state(cash, positions, as_of=FRI, phase=PortfolioStatePhase.POST_EXECUTION):
    frame = pl.DataFrame(positions, schema=["code", "quantity",
                                            "sellable_quantity"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("quantity").cast(pl.Int64),
                               pl.col("sellable_quantity").cast(pl.Int64))
    if frame.height:
        frame = frame.sort("code")
    return PortfolioState(as_of_date=as_of, phase=phase, cash=float(cash),
                          positions=frame)


def _fills(rows, exec_date=FRI, timing=ExecutionTiming.NEXT_OPEN):
    frame = pl.DataFrame(rows, schema=["code", "side", "order_quantity",
                                       "filled_quantity", "reference_price",
                                       "execution_price", "gross_notional",
                                       "commission", "stamp_tax",
                                       "transfer_fee", "total_fees",
                                       "effective_cash_delta"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("side").cast(pl.String),
                               pl.col("order_quantity").cast(pl.Int64),
                               pl.col("filled_quantity").cast(pl.Int64),
                               pl.col("reference_price").cast(pl.Float64),
                               pl.col("execution_price").cast(pl.Float64),
                               pl.col("gross_notional").cast(pl.Float64),
                               pl.col("commission").cast(pl.Float64),
                               pl.col("stamp_tax").cast(pl.Float64),
                               pl.col("transfer_fee").cast(pl.Float64),
                               pl.col("total_fees").cast(pl.Float64),
                               pl.col("effective_cash_delta").cast(pl.Float64))
    if frame.height:
        frame = frame.sort("code")
    return FillBatch(decision_date=datetime.date(2024, 1, 4),
                     execution_date=exec_date, execution_timing=timing,
                     frame=frame)


def _buy(code, filled, ordered=None):
    ordered = ordered if ordered is not None else filled
    gross = 10.0 * filled
    return (code, "buy", ordered, filled, 10.0, 10.0, gross, 0.0, 0.0, 0.0,
            0.0, -gross)


def _sell(code, filled):
    gross = 10.0 * filled
    return (code, "sell", filled, filled, 10.0, 10.0, gross, 0.0, 0.0, 0.0,
            0.0, gross)


def _advance(state, fills, db_path):
    return advance_to_next_trading_day(state, fills, db_path)


def _row(st, code):
    f = st.positions.filter(pl.col("code") == code)
    if f.height == 0:
        return None
    return f.row(0)


# ================================================================
# AC-01..18：API / calendar
# ================================================================

def test_api_exists():
    assert callable(advance_to_next_trading_day)


def test_type_guards(tmp_path):
    cal = _default_cal(tmp_path)
    with pytest.raises(TypeError, match="state"):
        advance_to_next_trading_day({"x": 1}, _fills([]), cal)
    with pytest.raises(TypeError, match="fills"):
        advance_to_next_trading_day(_state(0.0, []), {"f": 1}, cal)
    with pytest.raises(TypeError, match="db_path"):
        advance_to_next_trading_day(_state(0.0, []), _fills([]), str(cal))


def test_pre_input_fails(tmp_path):
    st = _state(0.0, [], phase=PortfolioStatePhase.PRE_EXECUTION)
    with pytest.raises(ValueError, match="POST_EXECUTION"):
        _advance(st, _fills([]), _default_cal(tmp_path))


def test_wrong_fill_date_fails(tmp_path):
    st = _state(0.0, [])
    f = _fills([], exec_date=MON)
    with pytest.raises(ValueError, match="as_of_date|execution_date"):
        _advance(st, f, _default_cal(tmp_path))


def test_next_close_not_implemented(tmp_path):
    st = _state(0.0, [])
    f = _fills([], timing=ExecutionTiming.NEXT_CLOSE)
    with pytest.raises(NotImplementedError, match="next_close|NEXT_CLOSE"):
        _advance(st, f, _default_cal(tmp_path))


def test_weekend_skip(tmp_path):
    nxt = _advance(_state(0.0, []), _fills([]), _default_cal(tmp_path))
    assert nxt.as_of_date == MON           # Friday → Monday（跳过周六日）


def test_holiday_skip(tmp_path):
    """D open、D+1/2 closed、D+3 open → D+3。"""
    D = datetime.date(2024, 1, 9)          # Tuesday
    D3 = datetime.date(2024, 1, 12)        # Friday（周三四 closed）
    cal = _cal_db(tmp_path, [(D, 1), (datetime.date(2024, 1, 10), 0),
                             (datetime.date(2024, 1, 11), 0), (D3, 1)])
    st = _state(0.0, [], as_of=D)
    nxt = _advance(st, _fills([], exec_date=D), cal)
    assert nxt.as_of_date == D3


def test_current_date_must_be_open(tmp_path):
    cal = _cal_db(tmp_path, [(FRI, 0), (MON, 1)])
    st = _state(0.0, [], as_of=FRI)
    with pytest.raises(ValueError, match="开放|trading"):
        _advance(st, _fills([]), cal)


def test_trailing_unresolved_fails(tmp_path):
    cal = _cal_db(tmp_path, [(FRI, 1)])
    st = _state(0.0, [], as_of=FRI)
    with pytest.raises(ValueError, match="next|后续|开放"):
        _advance(st, _fills([]), cal)


def test_output_metadata(tmp_path):
    nxt = _advance(_state(100.0, []), _fills([]), _default_cal(tmp_path))
    assert nxt.as_of_date == MON
    assert nxt.phase is PortfolioStatePhase.PRE_EXECUTION


def test_cash_unchanged(tmp_path):
    nxt = _advance(_state(14_488.0, []), _fills([]), _default_cal(tmp_path))
    assert nxt.cash == 14_488.0


def test_quantity_unchanged(tmp_path):
    st = _state(0.0, [("000001.SZ", 1000, 600), ("600000.SH", 500, 0)])
    nxt = _advance(st, _fills([]), _default_cal(tmp_path))
    r1 = _row(nxt, "000001.SZ")
    r2 = _row(nxt, "600000.SH")
    assert (r1[1], r1[2]) == (1000, 600)
    assert (r2[1], r2[2]) == (500, 0)


# ================================================================
# AC-19..42：T+1 provenance release
# ================================================================

def test_new_buy_position_release(tmp_path):
    """POST A 500/0 + BUY 500 → NEXT A 500/500。"""
    st = _state(0.0, [("000001.SZ", 500, 0)])
    f = _fills([_buy("000001.SZ", 500)])
    nxt = _advance(st, f, _default_cal(tmp_path))
    r = _row(nxt, "000001.SZ")
    assert (r[1], r[2]) == (500, 500)


def test_existing_buy_release(tmp_path):
    """POST A 1500/1000 + BUY 500 → NEXT 1500/1500。"""
    st = _state(0.0, [("000001.SZ", 1500, 1000)])
    f = _fills([_buy("000001.SZ", 500)])
    nxt = _advance(st, f, _default_cal(tmp_path))
    r = _row(nxt, "000001.SZ")
    assert (r[1], r[2]) == (1500, 1500)


def test_partial_buy_release_uses_filled(tmp_path):
    """order=1000 filled=600 → 只释放 600。"""
    st = _state(0.0, [("000001.SZ", 600, 0)])
    f = _fills([_buy("000001.SZ", 600, ordered=1000)])
    nxt = _advance(st, f, _default_cal(tmp_path))
    r = _row(nxt, "000001.SZ")
    assert (r[1], r[2]) == (600, 600)


def test_preserve_other_unavailable_inventory(tmp_path):
    """POST A 1500/600 + BUY 200 → NEXT 1500/800（剩余 700 不释放）。"""
    st = _state(0.0, [("000001.SZ", 1500, 600)])
    f = _fills([_buy("000001.SZ", 200)])
    nxt = _advance(st, f, _default_cal(tmp_path))
    r = _row(nxt, "000001.SZ")
    assert (r[1], r[2]) == (1500, 800)


def test_no_buy_holding_unchanged(tmp_path):
    """fills 只有别的 code → 本 holding 严格保持。"""
    st = _state(0.0, [("000001.SZ", 1000, 600), ("600000.SH", 300, 0)])
    f = _fills([_buy("600000.SH", 300)])
    nxt = _advance(st, f, _default_cal(tmp_path))
    r = _row(nxt, "000001.SZ")
    assert (r[1], r[2]) == (1000, 600)


def test_sell_only_no_release(tmp_path):
    """SELL-only 的 holding 不因过夜自动释放。"""
    st = _state(0.0, [("000001.SZ", 400, 100)])
    f = _fills([_sell("000001.SZ", 300)])
    nxt = _advance(st, f, _default_cal(tmp_path))
    r = _row(nxt, "000001.SZ")
    assert (r[1], r[2]) == (400, 100)


def test_empty_fills_preserves_all(tmp_path):
    st = _state(14_488.0, [("000001.SZ", 1000, 600)])
    nxt = _advance(st, _fills([]), _default_cal(tmp_path))
    assert nxt.cash == 14_488.0
    r = _row(nxt, "000001.SZ")
    assert (r[1], r[2]) == (1000, 600)
    assert nxt.as_of_date == MON


def test_cash_only_state(tmp_path):
    st = _state(100_000.0, [])
    nxt = _advance(st, _fills([]), _default_cal(tmp_path))
    assert nxt.cash == 100_000.0
    assert nxt.positions.height == 0
    assert nxt.positions.schema["code"] == pl.String
    assert nxt.positions.schema["quantity"] == pl.Int64
    assert nxt.positions.schema["sellable_quantity"] == pl.Int64


def test_no_new_or_deleted_codes(tmp_path):
    st = _state(0.0, [("000001.SZ", 1000, 600)])
    nxt = _advance(st, _fills([_buy("000001.SZ", 100)]), _default_cal(tmp_path))
    assert nxt.positions["code"].to_list() == ["000001.SZ"]


def test_output_sorted_asc(tmp_path):
    st = _state(0.0, [("600000.SH", 300, 0), ("000001.SZ", 200, 0)])
    nxt = _advance(st, _fills([]), _default_cal(tmp_path))
    assert nxt.positions["code"].to_list() == ["000001.SZ", "600000.SH"]


def test_new_sellable_never_exceeds_quantity(tmp_path):
    """release 后 new_sellable <= quantity 显式检查。"""
    st = _state(0.0, [("000001.SZ", 500, 400)])
    f = _fills([_buy("000001.SZ", 100)])
    nxt = _advance(st, f, _default_cal(tmp_path))
    r = _row(nxt, "000001.SZ")
    assert r[1] == 500 and r[2] == 500


# ================================================================
# AC-28..33：cross-object guards
# ================================================================

def test_buy_code_missing_in_post_fails(tmp_path):
    st = _state(0.0, [])
    f = _fills([_buy("000001.SZ", 500)])
    with pytest.raises(ValueError, match="position|持仓|存在"):
        _advance(st, f, _default_cal(tmp_path))


def test_insufficient_unsellable_capacity_fails(tmp_path):
    """POST 1000/900（unsellable=100）+ BUY 200 → 无法解释 200 provenance。"""
    st = _state(0.0, [("000001.SZ", 1000, 900)])
    f = _fills([_buy("000001.SZ", 200)])
    with pytest.raises(ValueError, match="unsellable|capacity|inventory"):
        _advance(st, f, _default_cal(tmp_path))


# ================================================================
# AC-56..60：immutability / determinism / reapply
# ================================================================

def test_immutability(tmp_path):
    st = _state(14_488.0, [("000001.SZ", 1500, 1000)])
    f = _fills([_buy("000001.SZ", 500)])
    pos_before = st.positions.clone()
    f_before = f.frame.clone()
    _advance(st, f, _default_cal(tmp_path))
    assert st.positions.equals(pos_before)
    assert f.frame.equals(f_before)
    assert st.phase is PortfolioStatePhase.POST_EXECUTION


def test_determinism(tmp_path):
    st = _state(14_488.0, [("000001.SZ", 1500, 1000)])
    f = _fills([_buy("000001.SZ", 500)])
    cal = _default_cal(tmp_path)
    a = _advance(st, f, cal)
    b = _advance(st, f, cal)
    assert a.as_of_date == b.as_of_date
    assert a.cash == b.cash
    assert a.positions.equals(b.positions)


def test_cannot_reapply_to_pre_output(tmp_path):
    cal = _default_cal(tmp_path)
    st = _state(0.0, [("000001.SZ", 500, 0)])
    f = _fills([_buy("000001.SZ", 500)])
    nxt = _advance(st, f, cal)
    assert nxt.phase is PortfolioStatePhase.PRE_EXECUTION
    with pytest.raises(ValueError, match="POST_EXECUTION"):
        _advance(nxt, _fills([]), cal)


def test_output_passes_validator(tmp_path):
    nxt = _advance(_state(100.0, [("000001.SZ", 100, 50)]), _fills([]),
                   _default_cal(tmp_path))
    assert isinstance(nxt, PortfolioState)


# ================================================================
# AC-85/86：source audits
# ================================================================

def test_no_blanket_release_source_audit():
    """overnight.py 不得出现 sellable=quantity 等价逻辑。"""
    from factorlab.execution import overnight as mod
    src = inspect.getsource(mod)
    assert "alias(\"sellable_quantity\")" not in src
    assert "sellable_quantity = quantity" not in src
    assert "pl.col(\"quantity\").alias" not in src


def test_no_forbidden_dependencies():
    from factorlab.execution import overnight as mod
    src = inspect.getsource(mod)
    for forbidden in ("compute_execution_cost", "ExecutionCostSpec",
                      "MarketOpenSnapshot", "OpenFillAssessment",
                      "SecurityQuantityRules", "OrderBatch",
                      "TargetPortfolio", "StrategySpec",
                      "daily", "stk_limit", "suspend_d"):
        assert not re.search(rf"^\s*(import|from)\s+[^\s]*{forbidden}", src,
                             re.M), f"overnight.py 不得引用 {forbidden}"
