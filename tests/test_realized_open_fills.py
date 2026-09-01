"""M8-04C：cost-aware realized funding + FillBatch——OrderBatch/assessment/state
→ actual modeled fills。

- FillBatch 是 sparse actual fills（filled_quantity > 0 才有一行；blocked/
  funding-zero → 无行，原因由 upstream assessment 持有）
- SELL FILLABLE → full fill；BUY partial 仅由 funding constraint 导致
- sell-first funding：available = state.cash + Σ actual net SELL proceeds
- BUY funding 迭代比例缩量 + quantity projection + re-cost 直到 cash-feasible
- slippage 产生的 execution_price 必须落在 [down, up]（越界 ValueError，不
  clipping）；最终 cash_after >= 0 严格（无 tolerance）
"""

import datetime
import math

import polars as pl
import pytest

from factorlab.domain import (ExecutionDataQualityError, ExecutionSchedule,
                              FillBatch, MarketOpenSnapshot, OpenFillAssessment,
                              OpenOrderDisposition, OrderBatch, OrderSide,
                              PortfolioState, PortfolioStatePhase,
                              QuantityRuleKind)
from factorlab.domain.timing import ExecutionTiming
from factorlab.execution import (ExecutionCostSpec, SecurityQuantityRules,
                                 assess_open_fillability, project_buy_quantity,
                                 project_sell_quantity, realize_open_fills)

D1 = datetime.date(2024, 1, 2)
E1 = datetime.date(2024, 1, 3)
LOT = QuantityRuleKind.ROUND_LOT_100
STAR = QuantityRuleKind.STAR_MIN_200_STEP_1
BSE = QuantityRuleKind.BSE_MIN_100_STEP_1


# ================================================================
# quantity authority（public projection == 旧 M8-03 private semantics）
# ================================================================

@pytest.mark.parametrize("cap,expected", [
    (0, 0), (1, 0), (99, 0), (100, 100), (101, 100), (199, 100),
    (200, 200), (375, 300), (500, 500)])
def test_project_buy_round(cap, expected):
    assert project_buy_quantity(LOT, cap) == expected


@pytest.mark.parametrize("cap,expected", [
    (199, 0), (200, 200), (201, 201), (251, 251), (999, 999)])
def test_project_buy_star(cap, expected):
    assert project_buy_quantity(STAR, cap) == expected


@pytest.mark.parametrize("cap,expected", [
    (99, 0), (100, 100), (101, 101), (137, 137), (157, 157)])
def test_project_buy_bse(cap, expected):
    assert project_buy_quantity(BSE, cap) == expected


@pytest.mark.parametrize("h,l,expected", [
    (299, 50, 0), (299, 99, 99), (299, 149, 100), (299, 198, 100),
    (299, 199, 199), (299, 250, 200), (299, 299, 299)])
def test_project_sell_round_table(h, l, expected):
    assert project_sell_quantity(LOT, holding_quantity=h, max_quantity=l) == expected


def test_project_sell_star():
    assert project_sell_quantity(STAR, holding_quantity=250, max_quantity=150) == 0
    assert project_sell_quantity(STAR, holding_quantity=250, max_quantity=250) == 250
    assert project_sell_quantity(STAR, holding_quantity=199, max_quantity=199) == 199
    assert project_sell_quantity(STAR, holding_quantity=199, max_quantity=100) == 0


def test_project_sell_bse():
    assert project_sell_quantity(BSE, holding_quantity=80, max_quantity=80) == 80
    assert project_sell_quantity(BSE, holding_quantity=250, max_quantity=150) == 150
    assert project_sell_quantity(BSE, holding_quantity=250, max_quantity=99) == 0


def test_project_unknown_rule_fails():
    with pytest.raises(ValueError):
        project_buy_quantity(QuantityRuleKind("nope"), 100)


# ================================================================
# fixture builders
# ================================================================

def _orders(rows, decision=D1, exec_date=E1):
    frame = pl.DataFrame(rows, schema=["code", "side", "quantity"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("side").cast(pl.String),
                               pl.col("quantity").cast(pl.Int64))
    if frame.height:
        frame = frame.sort("code")
    return OrderBatch(decision_date=decision, execution_date=exec_date,
                      execution_timing=ExecutionTiming.NEXT_OPEN, orders=frame)


def _snap(rows, exec_date=E1):
    frame = pl.DataFrame(rows, schema=["code", "open", "pre_close", "up_limit",
                                       "down_limit", "has_daily", "has_limit",
                                       "has_suspend_record",
                                       "is_suspended_at_open"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("open").cast(pl.Float64),
                               pl.col("pre_close").cast(pl.Float64),
                               pl.col("up_limit").cast(pl.Float64),
                               pl.col("down_limit").cast(pl.Float64),
                               pl.col("has_daily").cast(pl.Boolean),
                               pl.col("has_limit").cast(pl.Boolean),
                               pl.col("has_suspend_record").cast(pl.Boolean),
                               pl.col("is_suspended_at_open").cast(pl.Boolean))
    frame = frame.sort("code")
    return MarketOpenSnapshot(execution_date=exec_date, frame=frame)


def _rules(code_kinds):
    items = sorted(code_kinds.items())
    frame = pl.DataFrame(
        {"code": pl.Series([c for c, _ in items], dtype=pl.String),
         "market": pl.Series([k.value.split("_")[0] for _, k in items],
                             dtype=pl.String),
         "rule": pl.Series([k.value for _, k in items], dtype=pl.String)})
    return SecurityQuantityRules(frame=frame)


def _state(cash, positions, as_of=E1):
    frame = pl.DataFrame(positions, schema=["code", "quantity",
                                            "sellable_quantity"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("quantity").cast(pl.Int64),
                               pl.col("sellable_quantity").cast(pl.Int64))
    if frame.height:
        frame = frame.sort("code")
    return PortfolioState(as_of_date=as_of,
                          phase=PortfolioStatePhase.PRE_EXECUTION,
                          cash=float(cash), positions=frame)


def _normal_row(code="000001.SZ", open_=10.0, up=11.0, dn=9.0):
    return (code, open_, open_ - 0.2, up, dn, True, True, False, False)


def _assessment(rows, decision=D1, exec_date=E1):
    frame = pl.DataFrame(rows, schema=["code", "side", "quantity", "disposition",
                                       "fillable_price"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("side").cast(pl.String),
                               pl.col("quantity").cast(pl.Int64),
                               pl.col("disposition").cast(pl.String),
                               pl.col("fillable_price").cast(pl.Float64))
    if frame.height:
        frame = frame.sort("code")
    return OpenFillAssessment(decision_date=decision, execution_date=exec_date,
                              execution_timing=ExecutionTiming.NEXT_OPEN,
                              frame=frame)


def _cost(**over):
    base = {"commission_rate": 0.0, "minimum_commission": 0.0,
            "stamp_tax_sell_rate": 0.0, "transfer_fee_rate": 0.0,
            "slippage_bps": 0.0}
    base.update(over)
    return ExecutionCostSpec.model_validate(base)


def _realize(orders=None, assessment=None, state=None, snapshot=None,
             rules=None, cost=None):
    """默认：BUY 000001 1000 @10，cash=100k，无持仓——可覆盖。"""
    o = orders if orders is not None else _orders([("000001.SZ", "buy", 1000)])
    s = snapshot if snapshot is not None else _snap([_normal_row()])
    a = assessment if assessment is not None else _assessment(
        [("000001.SZ", "buy", 1000, "fillable", 10.0)])
    st = state if state is not None else _state(100_000.0, [])
    r = rules if rules is not None else _rules({"000001.SZ": LOT})
    c = cost if cost is not None else _cost()
    return realize_open_fills(o, a, st, s, r, c)


def _fills(batch, code):
    f = batch.frame.filter(pl.col("code") == code)
    if f.height == 0:
        return None
    return f.row(0)


# ================================================================
# AC-01..21：FillBatch domain
# ================================================================

def _mk_batch(rows, decision=D1, exec_date=E1):
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
    return FillBatch(decision_date=decision, execution_date=exec_date,
                     execution_timing=ExecutionTiming.NEXT_OPEN, frame=frame)


def test_fill_batch_exact_schema():
    b = _mk_batch([("000001.SZ", "buy", 1000, 1000, 10.0, 10.0, 10000.0,
                    0.0, 0.0, 0.0, 0.0, -10000.0)])
    assert b.frame.columns == ["code", "side", "order_quantity",
                               "filled_quantity", "reference_price",
                               "execution_price", "gross_notional",
                               "commission", "stamp_tax", "transfer_fee",
                               "total_fees", "effective_cash_delta"]


def test_fill_batch_dtypes():
    b = _mk_batch([("000001.SZ", "sell", 1000, 1000, 10.0, 10.0, 10000.0,
                    0.0, 0.0, 0.0, 0.0, 10000.0)])
    assert b.frame.schema["code"] == pl.String
    assert b.frame.schema["side"] == pl.String
    assert b.frame.schema["order_quantity"] == pl.Int64
    assert b.frame.schema["filled_quantity"] == pl.Int64
    assert b.frame.schema["reference_price"] == pl.Float64
    assert b.frame.schema["execution_price"] == pl.Float64
    assert b.frame.schema["gross_notional"] == pl.Float64
    assert b.frame.schema["commission"] == pl.Float64
    assert b.frame.schema["stamp_tax"] == pl.Float64
    assert b.frame.schema["transfer_fee"] == pl.Float64
    assert b.frame.schema["total_fees"] == pl.Float64
    assert b.frame.schema["effective_cash_delta"] == pl.Float64


def test_fill_batch_sell_row_valid():
    b = _mk_batch([("000001.SZ", "sell", 1000, 1000, 10.0, 10.0, 10000.0,
                    10.0, 5.0, 0.2, 15.2, 9984.8)])
    assert b.frame.height == 1


def test_fill_batch_invalid_cases():
    # 非 canonical
    with pytest.raises(ValueError):
        _mk_batch([("000001", "buy", 1000, 1000, 10.0, 10.0, 10000.0,
                    0.0, 0.0, 0.0, 0.0, -10000.0)])
    # 重复 code
    with pytest.raises(ValueError):
        _mk_batch([("000001.SZ", "buy", 100, 100, 10.0, 10.0, 1000.0,
                    0.0, 0.0, 0.0, 0.0, -1000.0),
                   ("000001.SZ", "sell", 50, 50, 10.0, 10.0, 500.0,
                    0.0, 0.0, 0.0, 0.0, 500.0)])
    # 乱序
    with pytest.raises(ValueError):
        _mk_batch([("600000.SH", "buy", 100, 100, 10.0, 10.0, 1000.0,
                    0.0, 0.0, 0.0, 0.0, -1000.0),
                   ("000001.SZ", "buy", 100, 100, 10.0, 10.0, 1000.0,
                    0.0, 0.0, 0.0, 0.0, -1000.0)])
    # 非法 side
    with pytest.raises(ValueError):
        _mk_batch([("000001.SZ", "long", 100, 100, 10.0, 10.0, 1000.0,
                    0.0, 0.0, 0.0, 0.0, -1000.0)])
    # filled > ordered
    with pytest.raises(ValueError):
        _mk_batch([("000001.SZ", "buy", 100, 200, 10.0, 10.0, 1000.0,
                    0.0, 0.0, 0.0, 0.0, -1000.0)])
    # filled == 0
    with pytest.raises(ValueError):
        _mk_batch([("000001.SZ", "buy", 100, 0, 10.0, 10.0, 1000.0,
                    0.0, 0.0, 0.0, 0.0, -1000.0)])
    # gross != price*filled
    with pytest.raises(ValueError):
        _mk_batch([("000001.SZ", "buy", 100, 100, 10.0, 10.0, 999.0,
                    0.0, 0.0, 0.0, 0.0, -1000.0)])
    # total != 三者之和
    with pytest.raises(ValueError):
        _mk_batch([("000001.SZ", "sell", 100, 100, 10.0, 10.0, 1000.0,
                    10.0, 5.0, 0.2, 16.0, 984.0)])
    # BUY stamp != 0
    with pytest.raises(ValueError):
        _mk_batch([("000001.SZ", "buy", 100, 100, 10.0, 10.0, 1000.0,
                    0.0, 5.0, 0.0, 5.0, -1005.0)])
    # BUY cash delta 公式错误
    with pytest.raises(ValueError):
        _mk_batch([("000001.SZ", "buy", 100, 100, 10.0, 10.0, 1000.0,
                    5.0, 0.0, 0.0, 5.0, -1000.0)])
    # SELL cash delta 公式错误（<=0）
    with pytest.raises(ValueError):
        _mk_batch([("000001.SZ", "sell", 100, 100, 10.0, 10.0, 1000.0,
                    1000.0, 0.0, 0.0, 1000.0, 0.0)])


def test_fill_batch_empty_valid():
    frame = pl.DataFrame({"code": pl.Series([], dtype=pl.String),
                          "side": pl.Series([], dtype=pl.String),
                          "order_quantity": pl.Series([], dtype=pl.Int64),
                          "filled_quantity": pl.Series([], dtype=pl.Int64),
                          "reference_price": pl.Series([], dtype=pl.Float64),
                          "execution_price": pl.Series([], dtype=pl.Float64),
                          "gross_notional": pl.Series([], dtype=pl.Float64),
                          "commission": pl.Series([], dtype=pl.Float64),
                          "stamp_tax": pl.Series([], dtype=pl.Float64),
                          "transfer_fee": pl.Series([], dtype=pl.Float64),
                          "total_fees": pl.Series([], dtype=pl.Float64),
                          "effective_cash_delta": pl.Series([], dtype=pl.Float64)})
    b = FillBatch(decision_date=D1, execution_date=E1,
                  execution_timing=ExecutionTiming.NEXT_OPEN, frame=frame)
    assert b.frame.height == 0
    assert b.frame.columns[-1] == "effective_cash_delta"


# ================================================================
# AC-22..31：API / cross-object
# ================================================================

def test_api_exists():
    assert callable(realize_open_fills)


def test_type_guards():
    with pytest.raises(TypeError, match="orders"):
        realize_open_fills(None, _assessment([]), _state(0.0, []),
                           _snap([]), _rules({}), _cost())
    with pytest.raises(TypeError, match="assessment"):
        realize_open_fills(_orders([]), None, _state(0.0, []), _snap([]),
                           _rules({}), _cost())
    with pytest.raises(TypeError, match="state"):
        realize_open_fills(_orders([]), _assessment([]), None, _snap([]),
                           _rules({}), _cost())
    with pytest.raises(TypeError, match="snapshot"):
        realize_open_fills(_orders([]), _assessment([]), _state(0.0, []), None,
                           _rules({}), _cost())
    with pytest.raises(TypeError, match="quantity_rules"):
        realize_open_fills(_orders([]), _assessment([]), _state(0.0, []),
                           _snap([]), None, _cost())
    with pytest.raises(TypeError, match="cost_spec"):
        realize_open_fills(_orders([]), _assessment([]), _state(0.0, []),
                           _snap([]), _rules({}), None)


def test_metadata_mismatch_fails():
    o = _orders([("000001.SZ", "buy", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.0)],
                    exec_date=datetime.date(2024, 1, 4))
    with pytest.raises(ValueError, match="execution_date|decision"):
        _realize(orders=o, assessment=a)


def test_identity_mismatch_fails():
    o = _orders([("000001.SZ", "buy", 100)])
    # assessment 缺行
    with pytest.raises(ValueError):
        _realize(orders=o, assessment=_assessment([]))
    # assessment 多行
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.0),
                     ("600000.SH", "buy", 100, "fillable", 10.0)])
    s = _snap([_normal_row(), _normal_row("600000.SH")])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    with pytest.raises(ValueError):
        _realize(orders=o, assessment=a, snapshot=s, rules=r)
    # assessment 数量不同
    a = _assessment([("000001.SZ", "buy", 999, "fillable", 10.0)])
    with pytest.raises(ValueError):
        _realize(orders=o, assessment=a)


def test_state_alignment_fails():
    st = _state(100.0, [], as_of=datetime.date(2024, 1, 4))
    with pytest.raises(ValueError, match="as_of_date"):
        _realize(state=st)


def test_post_execution_phase_fails():
    st = PortfolioState(as_of_date=E1, phase=PortfolioStatePhase.POST_EXECUTION,
                        cash=100.0, positions=_state(0.0, []).positions)
    with pytest.raises(ValueError, match="PRE_EXECUTION"):
        _realize(state=st)


def test_snapshot_date_mismatch_fails():
    s = _snap([_normal_row()], exec_date=datetime.date(2024, 1, 4))
    with pytest.raises(ValueError, match="execution_date"):
        _realize(snapshot=s)


def test_missing_snapshot_code_fails():
    o = _orders([("000001.SZ", "buy", 100), ("600000.SH", "buy", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.0),
                     ("600000.SH", "buy", 100, "fillable", 10.0)])
    s = _snap([_normal_row()])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    with pytest.raises(ValueError, match="600000|snapshot"):
        _realize(orders=o, assessment=a, snapshot=s, rules=r)


def test_missing_rule_code_fails():
    o = _orders([("000001.SZ", "buy", 100), ("600000.SH", "buy", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.0),
                     ("600000.SH", "buy", 100, "fillable", 10.0)])
    s = _snap([_normal_row(), _normal_row("600000.SH")])
    r = _rules({"000001.SZ": LOT})
    with pytest.raises(ValueError, match="600000|rules"):
        _realize(orders=o, assessment=a, snapshot=s, rules=r)


def test_extra_snapshot_and_rule_codes_allowed():
    o = _orders([("000001.SZ", "buy", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.0)])
    s = _snap([_normal_row(), _normal_row("601111.SH")])
    r = _rules({"000001.SZ": LOT, "601111.SH": LOT})
    b = _realize(orders=o, assessment=a, snapshot=s, rules=r)
    assert b.frame.height == 1


def test_next_close_not_implemented():
    o = OrderBatch(decision_date=D1, execution_date=E1,
                   execution_timing=ExecutionTiming.NEXT_CLOSE,
                   orders=_orders([("000001.SZ", "buy", 100)]).orders)
    with pytest.raises(NotImplementedError):
        _realize(orders=o)


# ================================================================
# AC-32..37：quantity/inventory revalidation
# ================================================================

def test_buy_quantity_revalidated():
    o = _orders([("000001.SZ", "buy", 150)])   # ROUND 非法数量
    a = _assessment([("000001.SZ", "buy", 150, "fillable", 10.0)])
    with pytest.raises(ValueError, match="buy|数量|is_valid"):
        _realize(orders=o, assessment=a)


def test_sell_missing_position_fails():
    o = _orders([("000001.SZ", "sell", 100)])
    a = _assessment([("000001.SZ", "sell", 100, "fillable", 10.0)])
    with pytest.raises(ValueError, match="position|持仓"):
        _realize(orders=o, assessment=a)


def test_sell_exceeds_holding_fails():
    o = _orders([("000001.SZ", "sell", 1500)])
    a = _assessment([("000001.SZ", "sell", 1500, "fillable", 10.0)])
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    with pytest.raises(ValueError, match="quantity|holding"):
        _realize(orders=o, assessment=a, state=st)


def test_sell_exceeds_sellable_fails():
    o = _orders([("000001.SZ", "sell", 800)])
    a = _assessment([("000001.SZ", "sell", 800, "fillable", 10.0)])
    st = _state(0.0, [("000001.SZ", 1000, 500)])
    with pytest.raises(ValueError, match="sellable"):
        _realize(orders=o, assessment=a, state=st)


def test_sell_invalid_lot_structure_fails():
    o = _orders([("000001.SZ", "sell", 150)])
    a = _assessment([("000001.SZ", "sell", 150, "fillable", 10.0)])
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    with pytest.raises(ValueError):
        _realize(orders=o, assessment=a, state=st)


def test_blocked_sell_still_inventory_validated():
    """blocked SELL 也必须通过 inventory check（市场 blocked 不掩盖 corruption）。"""
    o = _orders([("000001.SZ", "sell", 100)])
    a = _assessment([("000001.SZ", "sell", 100, "blocked_suspension", None)])
    with pytest.raises(ValueError, match="position|持仓"):
        _realize(orders=o, assessment=a)


# ================================================================
# AC-38..47：SELL realization
# ================================================================

def test_sell_full_fill():
    o = _orders([("000001.SZ", "sell", 1000)])
    a = _assessment([("000001.SZ", "sell", 1000, "fillable", 10.0)])
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    b = _realize(orders=o, assessment=a, state=st)
    r = _fills(b, "000001.SZ")
    assert r[1] == "sell" and r[2] == 1000 and r[3] == 1000
    assert r[4] == 10.0 and r[5] == 10.0
    assert r[10] == 0.0 and r[11] == 10000.0


def test_blocked_sell_zero_fill_no_row():
    o = _orders([("000001.SZ", "sell", 1000)])
    a = _assessment([("000001.SZ", "sell", 1000, "blocked_suspension", None)])
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    b = _realize(orders=o, assessment=a, state=st)
    assert b.frame.height == 0


def test_sell_cost_applied():
    o = _orders([("000001.SZ", "sell", 1000)])
    a = _assessment([("000001.SZ", "sell", 1000, "fillable", 10.0)])
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    c = _cost(commission_rate=0.001, minimum_commission=5.0,
              stamp_tax_sell_rate=0.001, transfer_fee_rate=0.00002)
    b = _realize(orders=o, assessment=a, state=st, cost=c)
    r = _fills(b, "000001.SZ")
    # gross=10000, comm=10, stamp=10, transfer=0.2, fees=20.2, delta=9979.8
    assert r[6] == 10000.0 and r[7] == 10.0 and r[8] == 10.0
    assert r[9] == 0.2 and r[10] == 20.2 and r[11] == 9979.8


# ================================================================
# AC-48..65：BUY funding
# ================================================================

def test_available_cash_uses_actual_sell_proceeds():
    """SELL 成交 → 其净回款进入 available（blocked SELL 不提供现金）。"""
    o = _orders([("000001.SZ", "sell", 1000), ("600000.SH", "buy", 1000)])
    a = _assessment([("000001.SZ", "sell", 1000, "fillable", 10.0),
                     ("600000.SH", "buy", 1000, "fillable", 10.0)])
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    s = _snap([_normal_row(), _normal_row("600000.SH")])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    b = _realize(orders=o, assessment=a, state=st, snapshot=s, rules=r)
    assert _fills(b, "000001.SZ")[3] == 1000
    assert _fills(b, "600000.SH")[3] == 1000     # available=10000 ≥ 10000
    assert b.frame["effective_cash_delta"].sum() == 0.0


def test_blocked_sell_removes_funding():
    """cash=0，SELL blocked → available=0 → BUY fill=0。"""
    o = _orders([("000001.SZ", "sell", 1000), ("600000.SH", "buy", 1000)])
    a = _assessment([("000001.SZ", "sell", 1000, "blocked_suspension", None),
                     ("600000.SH", "buy", 1000, "fillable", 10.0)])
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    s = _snap([("000001.SZ", None, None, None, None, False, False, True, True),
               _normal_row("600000.SH")])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    b = _realize(orders=o, assessment=a, state=st, snapshot=s, rules=r)
    assert b.frame.height == 0


def test_blocked_buy_absent():
    o = _orders([("000001.SZ", "sell", 1000), ("600000.SH", "buy", 1000)])
    a = _assessment([("000001.SZ", "sell", 1000, "fillable", 10.0),
                     ("600000.SH", "buy", 1000, "blocked_limit_up", None)])
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    s = _snap([_normal_row(), _normal_row("600000.SH", open_=11.0, up=11.0)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    b = _realize(orders=o, assessment=a, state=st, snapshot=s, rules=r)
    assert b.frame.height == 1
    assert _fills(b, "000001.SZ") is not None
    assert _fills(b, "600000.SH") is None
    assert b.frame["effective_cash_delta"].sum() == 10000.0


def test_cost_driven_buy_reduction():
    """gross funding 刚好够，但 commission 加入后不够 → 缩量。"""
    o = _orders([("000001.SZ", "buy", 1000)])
    a = _assessment([("000001.SZ", "buy", 1000, "fillable", 10.0)])
    st = _state(10_000.0, [])
    c = _cost(commission_rate=0.001)   # required = 10000*1.001 > 10000
    b = _realize(orders=o, assessment=a, state=st, cost=c)
    r = _fills(b, "000001.SZ")
    assert r[3] == 900          # 9900*1.001=9909.9 <= 10000；1000→floor(1000*10000/10010)=999→900
    assert b.frame["effective_cash_delta"][0] >= -10_000.0


def test_symmetry_no_code_bias():
    """两个同经济参数 BUY 资金不足 → 同比例缩量（无 code-order greedy）。"""
    o = _orders([("000001.SZ", "buy", 500), ("600000.SH", "buy", 500)])
    a = _assessment([("000001.SZ", "buy", 500, "fillable", 10.0),
                     ("600000.SH", "buy", 500, "fillable", 10.0)])
    st = _state(5_000.0, [])
    s = _snap([_normal_row(), _normal_row("600000.SH")])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    b = _realize(orders=o, assessment=a, state=st, snapshot=s, rules=r)
    q1 = _fills(b, "000001.SZ")[3]
    q2 = _fills(b, "600000.SH")[3]
    assert q1 == q2 == 200      # scale 0.5 → cap 250 → ROUND 200（同参数同结果）
    assert b.frame["effective_cash_delta"].sum() >= -5_000.0


def test_minimum_commission_second_pass():
    """第一次比例缩量后 minimum commission 使 total 仍 > budget → 第二轮。"""
    o = _orders([("688001.SH", "buy", 1000), ("920001.BJ", "buy", 1000)])
    a = _assessment([("688001.SH", "buy", 1000, "fillable", 1.0),
                     ("920001.BJ", "buy", 1000, "fillable", 1.0)])
    st = _state(1_000.0, [])
    s = _snap([_normal_row("688001.SH", open_=1.0, up=1.1, dn=0.9),
               _normal_row("920001.BJ", open_=1.0, up=1.1, dn=0.9)])
    r = _rules({"688001.SH": STAR, "920001.BJ": BSE})
    c = _cost(commission_rate=0.001, minimum_commission=5.0)
    b = _realize(orders=o, assessment=a, state=st, snapshot=s, rules=r, cost=c)
    # 首轮 total = 2×(1000 + max(1, 5)) = 2010 > 1000 → scale=1000/2010 →
    # cap floor(497.51)=497 → STAR/BSE 497 → total = 2×(497+5) = 1004 > 1000
    # → scale=1000/1004 → cap floor(495.02)=495 → total = 2×(495+5) = 1000
    # <= 1000 ✓（第二轮——minimum commission 使首轮后仍超预算）
    q1 = _fills(b, "688001.SH")[3]
    q2 = _fills(b, "920001.BJ")[3]
    assert q1 == q2 == 495
    assert b.frame["effective_cash_delta"].sum() >= -1_000.0


def test_progress_invariant_and_zero_removal():
    """极小 budget → 全投影 0 → 空 FillBatch（candidates 移除）。"""
    o = _orders([("000001.SZ", "buy", 1000)])
    a = _assessment([("000001.SZ", "buy", 1000, "fillable", 10.0)])
    st = _state(1.0, [])
    b = _realize(orders=o, assessment=a, state=st)
    assert b.frame.height == 0


def test_no_residual_redistribution():
    """缩量后残余现金不二次分配——结果确定性。"""
    o = _orders([("000001.SZ", "buy", 500), ("600000.SH", "buy", 500)])
    a = _assessment([("000001.SZ", "buy", 500, "fillable", 10.0),
                     ("600000.SH", "buy", 500, "fillable", 10.0)])
    st = _state(4_000.0, [])
    s = _snap([_normal_row(), _normal_row("600000.SH")])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    b = _realize(orders=o, assessment=a, state=st, snapshot=s, rules=r)
    # scale = 4000/10000 = 0.4 → cap floor(500×0.4) = 200 → ROUND 200 each
    # spend 4000 = budget 精确（残余 0——不做二次分配）
    assert _fills(b, "000001.SZ")[3] == 200
    assert _fills(b, "600000.SH")[3] == 200


def test_cash_never_negative_strict():
    """cash_after >= 0 严格（无 tolerance/clamp）。"""
    o = _orders([("000001.SZ", "buy", 1000)])
    a = _assessment([("000001.SZ", "buy", 1000, "fillable", 10.0)])
    st = _state(10_000.0, [])
    c = _cost(commission_rate=0.001, minimum_commission=5.0)
    b = _realize(orders=o, assessment=a, state=st, cost=c)
    cash_after = 10_000.0 + b.frame["effective_cash_delta"].sum()
    assert cash_after >= 0.0


# ================================================================
# AC-66..71：slippage legal bound
# ================================================================

def test_slippage_bound_ok_within_limits():
    o = _orders([("000001.SZ", "buy", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.0)])
    c = _cost(slippage_bps=50)   # price 10.0*1.005 < up 11
    b = _realize(orders=o, assessment=a, cost=c)
    assert _fills(b, "000001.SZ")[5] == 10.0 * 1.005


def test_buy_slippage_crosses_upper_fails():
    o = _orders([("000001.SZ", "buy", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.0)])
    s = _snap([_normal_row(open_=10.0, up=10.04, dn=9.9)])
    c = _cost(slippage_bps=50)   # 10.05 > up 10.04
    with pytest.raises(ValueError, match="slippage|crosses|limit"):
        _realize(orders=o, assessment=a, snapshot=s, cost=c)


def test_sell_slippage_crosses_lower_fails():
    o = _orders([("000001.SZ", "sell", 100)])
    a = _assessment([("000001.SZ", "sell", 100, "fillable", 10.0)])
    st = _state(0.0, [("000001.SZ", 100, 100)])
    s = _snap([_normal_row(open_=10.0, up=10.04, dn=9.96)])
    c = _cost(slippage_bps=50)   # 9.95 < dn 9.96
    with pytest.raises(ValueError, match="slippage|crosses|limit"):
        _realize(orders=o, assessment=a, state=st, snapshot=s, cost=c)


def test_slippage_bound_exact_equality_ok():
    """execution_price == up（BUY）合法（不是 adverse-queue 重判）。
    up 用与 slippage 相同的表达式构造——exact equality。"""
    o = _orders([("000001.SZ", "buy", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.0)])
    s = _snap([_normal_row(open_=10.0, up=10.0 * 1.005, dn=9.9)])
    c = _cost(slippage_bps=50)
    b = _realize(orders=o, assessment=a, snapshot=s, cost=c)
    assert _fills(b, "000001.SZ")[5] == 10.0 * 1.005


def test_slippage_bound_error_is_not_data_quality_error():
    o = _orders([("000001.SZ", "buy", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.0)])
    s = _snap([_normal_row(open_=10.0, up=10.04, dn=9.9)])
    c = _cost(slippage_bps=50)
    with pytest.raises(ValueError) as ei:
        _realize(orders=o, assessment=a, snapshot=s, cost=c)
    assert not isinstance(ei.value, ExecutionDataQualityError)


def test_no_price_clipping():
    """越界必须 fail——不 min/max clip。"""
    o = _orders([("000001.SZ", "buy", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.0)])
    s = _snap([_normal_row(open_=10.0, up=10.04, dn=9.9)])
    c = _cost(slippage_bps=50)
    with pytest.raises(ValueError):
        _realize(orders=o, assessment=a, snapshot=s, cost=c)


# ================================================================
# AC-80..94：golden / parity
# ================================================================

def test_zero_cost_full_fill_parity():
    o = _orders([("000001.SZ", "buy", 1000), ("600000.SH", "sell", 500)])
    a = _assessment([("000001.SZ", "buy", 1000, "fillable", 10.0),
                     ("600000.SH", "sell", 500, "fillable", 9.0)])
    st = _state(100_000.0, [("600000.SH", 500, 500)])
    s = _snap([_normal_row(), _normal_row("600000.SH", open_=9.0, up=10.0, dn=8.0)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    b = _realize(orders=o, assessment=a, state=st, snapshot=s, rules=r)
    assert b.frame.height == 2
    for row in b.frame.iter_rows():
        assert row[3] == row[2]          # filled == ordered
        assert row[5] == row[4]          # execution == reference（zero-cost）
        assert row[10] == 0.0            # no fees


def test_zero_cost_cash_parity():
    o = _orders([("000001.SZ", "sell", 1000), ("600000.SH", "buy", 600)])
    a = _assessment([("000001.SZ", "sell", 1000, "fillable", 10.0),
                     ("600000.SH", "buy", 600, "fillable", 10.0)])
    st = _state(100_000.0, [("000001.SZ", 1000, 1000)])
    s = _snap([_normal_row(), _normal_row("600000.SH")])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    b = _realize(orders=o, assessment=a, state=st, snapshot=s, rules=r)
    cash_after = 100_000.0 + b.frame["effective_cash_delta"].sum()
    assert cash_after == 100_000.0 + 10_000.0 - 6_000.0


def test_reference_price_must_equal_raw_open():
    """assessment.fillable_price 必须 == snapshot.open（raw Float64 exact）。"""
    o = _orders([("000001.SZ", "buy", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "fillable", 10.5)])
    s = _snap([_normal_row(open_=10.0)])
    with pytest.raises(ValueError, match="reference|open"):
        _realize(orders=o, assessment=a, snapshot=s)


def test_all_blocked_empty_batch():
    o = _orders([("000001.SZ", "buy", 100), ("600000.SH", "sell", 100)])
    a = _assessment([("000001.SZ", "buy", 100, "blocked_limit_up", None),
                     ("600000.SH", "sell", 100, "blocked_suspension", None)])
    st = _state(0.0, [("600000.SH", 100, 100)])
    s = _snap([_normal_row(), _normal_row("600000.SH")])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    b = _realize(orders=o, assessment=a, state=st, snapshot=s, rules=r)
    assert b.frame.height == 0
    assert b.decision_date == D1 and b.execution_date == E1


def test_empty_orders_empty_batch():
    o = _orders([])
    a = _assessment([])
    b = _realize(orders=o, assessment=a)
    assert b.frame.height == 0
    assert b.frame.columns[-1] == "effective_cash_delta"
    assert b.decision_date == D1 and b.execution_date == E1


def test_partial_buy_fees_based_on_filled():
    """缩量后费用基于 filled_quantity 重算（不按 order_quantity 收费）。"""
    o = _orders([("000001.SZ", "buy", 1000)])
    a = _assessment([("000001.SZ", "buy", 1000, "fillable", 10.0)])
    st = _state(9_000.0, [])
    c = _cost(commission_rate=0.001, minimum_commission=5.0)
    b = _realize(orders=o, assessment=a, state=st, cost=c)
    r = _fills(b, "000001.SZ")
    assert r[3] == 800          # 800*10*1.001 = 8008 <= 9000；900→9009>9000
    assert r[6] == 8000.0       # gross 基于 filled
    assert r[7] == 8.0          # commission 基于 filled（8000*0.001=8 > min 5）


def test_sell_unchanged_by_buy_shortage():
    """BUY 资金不足不影响已 FILLABLE SELL（sell-first）。"""
    o = _orders([("000001.SZ", "sell", 1000), ("600000.SH", "buy", 1000)])
    a = _assessment([("000001.SZ", "sell", 1000, "fillable", 10.0),
                     ("600000.SH", "buy", 1000, "fillable", 10.0)])
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    s = _snap([_normal_row(), _normal_row("600000.SH")])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    b = _realize(orders=o, assessment=a, state=st, snapshot=s, rules=r)
    assert _fills(b, "000001.SZ")[3] == 1000
    assert _fills(b, "600000.SH")[3] == 1000    # available=10000 == required


def test_determinism_and_no_mutation():
    args = dict(orders=_orders([("000001.SZ", "sell", 1000),
                                ("600000.SH", "buy", 1000)]),
                assessment=_assessment([("000001.SZ", "sell", 1000, "fillable", 10.0),
                                        ("600000.SH", "buy", 1000, "fillable", 10.0)]),
                state=_state(5_000.0, [("000001.SZ", 1000, 1000)]),
                snapshot=_snap([_normal_row(), _normal_row("600000.SH")]),
                quantity_rules=_rules({"000001.SZ": LOT, "600000.SH": LOT}),
                cost_spec=_cost(commission_rate=0.001, minimum_commission=5.0))
    snapshots = {k: (v.frame.clone() if hasattr(v, "frame") else v)
                 for k, v in args.items()}
    a = realize_open_fills(**args)
    b = realize_open_fills(**args)
    assert a.frame.equals(b.frame)
    for k, v in args.items():
        if hasattr(v, "frame"):
            assert v.frame.equals(snapshots[k])
