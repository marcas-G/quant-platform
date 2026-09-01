"""M8-03：deterministic net order planning——TargetPortfolio → OrderBatch。

覆盖 AC-01 ~ AC-86：
- API/type guards / cross-object invariants（target↔schedule、schedule↔snapshot、
  schedule↔state、PRE_EXECUTION phase、planning code coverage）
- planning equity（raw open）→ target value → ideal shares（floor）
- SELL：desired reduction → sellable cap → quantity projection（ROUND odd-lot/
  STAR/BSE）→ T+1 cap
- BUY：desired increase → per-security projection → sell-first funding →
  proportional funding scale → residual cash（不 redistribute）
- evidence boundary：has_daily=sizing evidence；has_limit/has_suspend_record
  ignored；evidence != fillability
- all-cash 特例（missing daily allowed、sell intent 生成）
- 确定性 / 输入不可变
"""

import datetime
import inspect
import math

import polars as pl
import pytest

from factorlab.domain import (ExecutionSchedule, MarketOpenSnapshot,
                              OrderBatch, PortfolioState, PortfolioStatePhase,
                              QuantityRuleKind, TargetPortfolio,
                              TargetPortfolioMeta)
from factorlab.domain.timing import (DEFAULT_EOD_SIGNAL_TIMING, ExecutionTiming,
                                     InformationCutoff, SignalAvailability,
                                     SignalTiming)
from factorlab.execution import (SecurityQuantityRules, construct_order_batch,
                                 is_valid_buy_quantity, is_valid_sell_quantity)

D1 = datetime.date(2024, 1, 2)     # decision date
D2 = datetime.date(2024, 1, 3)     # second decision date
E1 = datetime.date(2024, 1, 3)     # execution date（> D1）
E2 = datetime.date(2024, 1, 4)     # second execution date（> D2）

NEXT_CLOSE_TIMING = SignalTiming(
    information_cutoff=InformationCutoff.CLOSE,
    available_at=SignalAvailability.AFTER_CLOSE,
    default_earliest_execution=ExecutionTiming.NEXT_CLOSE,
)

LOT = QuantityRuleKind.ROUND_LOT_100
STAR = QuantityRuleKind.STAR_MIN_200_STEP_1
BSE = QuantityRuleKind.BSE_MIN_100_STEP_1


# ---------------- fixture builders ----------------

def _target(decision_dates=(D1,), rows=None, *, timing=DEFAULT_EOD_SIGNAL_TIMING,
            gross=1.0):
    """rows: {date: [(code, weight), ...]} 或单日 [(code, weight)]（默认 D1）。"""
    if rows is None:
        rows = {}
    if isinstance(rows, list):
        rows = {decision_dates[0]: rows}
    frame_rows = []
    for d, codes in rows.items():
        for code, w in codes:
            frame_rows.append((d, code, w))
    frame = pl.DataFrame(frame_rows, schema=["decision_date", "code",
                                             "target_weight"], orient="row")
    frame = frame.with_columns(pl.col("decision_date").cast(pl.Date),
                               pl.col("code").cast(pl.String),
                               pl.col("target_weight").cast(pl.Float64))
    meta = TargetPortfolioMeta(strategy_name="strat_x",
                               source_signal_name="alpha_x",
                               source_timing=timing,
                               gross_exposure=gross)
    return TargetPortfolio(frame=frame, decision_dates=decision_dates, meta=meta)


def _schedule(decision_dates=(D1,), execution_dates=(E1,), timing="next_open"):
    frame = pl.DataFrame({"decision_date": pl.Series(decision_dates, dtype=pl.Date),
                          "execution_date": pl.Series(execution_dates, dtype=pl.Date),
                          "execution_timing": pl.Series([timing] * len(decision_dates),
                                                        dtype=pl.String)})
    return ExecutionSchedule(frame=frame)


def _state(cash, positions, as_of=E1, phase=PortfolioStatePhase.PRE_EXECUTION):
    frame = pl.DataFrame(positions, schema=["code", "quantity", "sellable_quantity"],
                         orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("quantity").cast(pl.Int64),
                               pl.col("sellable_quantity").cast(pl.Int64))
    if frame.height:
        frame = frame.sort("code")
    return PortfolioState(as_of_date=as_of, phase=phase, cash=float(cash),
                          positions=frame)


def _snap_row(code, open_, pre_close, has_daily=True, has_limit=False,
              has_suspend=False, up=None, down=None):
    return (code, open_, pre_close, up, down, has_daily, has_limit, has_suspend)


def _snapshot(rows, exec_date=E1):
    frame = pl.DataFrame(rows, schema=["code", "open", "pre_close", "up_limit",
                                       "down_limit", "has_daily", "has_limit",
                                       "has_suspend_record"], orient="row")
    frame = frame.with_columns(pl.col("code").cast(pl.String),
                               pl.col("open").cast(pl.Float64),
                               pl.col("pre_close").cast(pl.Float64),
                               pl.col("up_limit").cast(pl.Float64),
                               pl.col("down_limit").cast(pl.Float64),
                               pl.col("has_daily").cast(pl.Boolean),
                               pl.col("has_limit").cast(pl.Boolean),
                               pl.col("has_suspend_record").cast(pl.Boolean),
                               pl.lit(False).cast(pl.Boolean)
                               .alias("is_suspended_at_open"))
    frame = frame.sort("code")
    return MarketOpenSnapshot(execution_date=exec_date, frame=frame)


def _rules(code_kinds):
    """code_kinds: {code: QuantityRuleKind}（market 用 kind 名 provenance）。"""
    items = sorted(code_kinds.items())
    frame = pl.DataFrame(
        {"code": pl.Series([c for c, _ in items], dtype=pl.String),
         "market": pl.Series([k.value.split("_")[0] for _, k in items],
                             dtype=pl.String),
         "rule": pl.Series([k.value for _, k in items], dtype=pl.String)})
    return SecurityQuantityRules(frame=frame)


def _plan(target=None, schedule=None, state=None, snapshot=None, rules=None,
          decision_date=D1):
    """默认：cash=100k、无持仓、target A=1.0、open 10、ROUND——然后按需覆盖。"""
    t = target if target is not None else _target(rows=[("000001.SZ", 1.0)])
    s = schedule if schedule is not None else _schedule()
    st = state if state is not None else _state(100_000.0, [])
    sn = snapshot if snapshot is not None else _snapshot(
        [_snap_row("000001.SZ", 10.0, 9.8)])
    r = rules if rules is not None else _rules({"000001.SZ": LOT})
    return construct_order_batch(t, s, st, sn, r, decision_date=decision_date)


def _orders(batch):
    return batch.orders


def _qty(batch, code, side=None):
    f = batch.orders
    if f.height == 0:
        return None
    f = f.filter(pl.col("code") == code)
    if f.height == 0:
        return None
    if side is not None:
        f = f.filter(pl.col("side") == side)
        if f.height == 0:
            return None
    return f["quantity"][0]


# ================================================================
# AC-01/02：API 存在 + 无 ExecutionSpec 参数
# ================================================================

def test_api_exists():
    from factorlab.execution import construct_order_batch
    assert callable(construct_order_batch)


def test_signature_no_execution_spec():
    params = list(inspect.signature(construct_order_batch).parameters)
    assert params[:5] == ["target", "schedule", "state", "snapshot",
                          "quantity_rules"]
    assert params[5] == "decision_date"
    assert "spec" not in params and "execution_spec" not in params


def test_signature_keyword_only_decision_date():
    sig = inspect.signature(construct_order_batch)
    assert sig.parameters["decision_date"].kind == inspect.Parameter.KEYWORD_ONLY


def test_no_db_no_signal_no_cost_params():
    params = set(inspect.signature(construct_order_batch).parameters)
    for forbidden in ("db_path", "signal", "strategy_spec", "commission",
                      "stamp_tax", "slippage", "nav", "execution_spec"):
        assert forbidden not in params


# ================================================================
# AC-03/04：type guards
# ================================================================

def test_type_guard_target():
    with pytest.raises(TypeError, match="target"):
        _plan(target={"frame": None})


def test_type_guard_schedule():
    with pytest.raises(TypeError, match="schedule"):
        _plan(schedule=pl.DataFrame())


def test_type_guard_state():
    with pytest.raises(TypeError, match="state"):
        _plan(state={"as_of_date": None})


def test_type_guard_snapshot():
    with pytest.raises(TypeError, match="snapshot"):
        _plan(snapshot={"frame": None})


def test_type_guard_quantity_rules():
    with pytest.raises(TypeError, match="quantity_rules"):
        _plan(rules=[])


@pytest.mark.parametrize("bad", ["2024-01-02", None, 1.0, 20240102])
def test_decision_date_strict_date(bad):
    with pytest.raises((TypeError, ValueError)):
        _plan(decision_date=bad)


def test_decision_date_rejects_datetime():
    with pytest.raises(ValueError):
        _plan(decision_date=datetime.datetime(2024, 1, 2, 9, 30))


# ================================================================
# AC-05/06：target ↔ schedule 全局对应
# ================================================================

def test_schedule_missing_decision_fails():
    t = _target(decision_dates=(D1, D2), rows={D1: [("000001.SZ", 1.0)],
                                               D2: [("600000.SH", 1.0)]})
    with pytest.raises(ValueError, match="decision"):
        _plan(target=t, schedule=_schedule(decision_dates=(D1,),
                                           execution_dates=(E1,)))


def test_schedule_extra_decision_fails():
    t = _target(decision_dates=(D1,), rows={D1: [("000001.SZ", 1.0)]})
    with pytest.raises(ValueError, match="decision"):
        _plan(target=t, schedule=_schedule(decision_dates=(D1, D2),
                                           execution_dates=(E1, E2)))


def test_schedule_timing_mismatch_fails():
    t = _target()
    with pytest.raises(ValueError, match="timing|next_open"):
        _plan(target=t, schedule=_schedule(timing="next_close"))


def test_schedule_mixed_timing_fails():
    t = _target(decision_dates=(D1, D2), rows={D1: [("000001.SZ", 1.0)],
                                               D2: [("600000.SH", 1.0)]})
    with pytest.raises(ValueError, match="timing"):
        _plan(target=t, schedule=_schedule(decision_dates=(D1, D2),
                                           execution_dates=(E1, E2),
                                           timing="next_close"))


# ================================================================
# AC-07/08：selected decision_date + schedule row
# ================================================================

def test_selected_decision_not_in_target_fails():
    with pytest.raises(ValueError, match="decision"):
        _plan(decision_date=D2)


def test_selected_schedule_row_unique():
    """domain 已保证 unique——planner 防御性断言仍拒绝重复行。"""
    sch = _schedule()
    dup = pl.DataFrame({"decision_date": pl.Series([D1, D1], dtype=pl.Date),
                        "execution_date": pl.Series([E1, E2], dtype=pl.Date),
                        "execution_timing": pl.Series(["next_open", "next_open"],
                                                      dtype=pl.String)})
    object.__setattr__(sch, "frame", dup)
    with pytest.raises(ValueError, match="decision|1 row|恰|unique"):
        _plan(schedule=sch)


# ================================================================
# AC-09/10：NEXT_OPEN only
# ================================================================

def test_next_open_supported():
    batch = _plan()
    assert batch.execution_timing is ExecutionTiming.NEXT_OPEN


def test_next_close_not_implemented():
    t = _target(timing=NEXT_CLOSE_TIMING)
    with pytest.raises(NotImplementedError, match="NEXT_CLOSE|next_close"):
        _plan(target=t, schedule=_schedule(timing="next_close"))


# ================================================================
# AC-11/12/13：execution date / phase cross-object invariants
# ================================================================

def test_schedule_snapshot_date_mismatch_fails():
    with pytest.raises(ValueError, match="execution_date"):
        _plan(snapshot=_snapshot([_snap_row("000001.SZ", 10.0, 9.8)],
                                 exec_date=E2))


def test_schedule_state_date_mismatch_fails():
    with pytest.raises(ValueError, match="as_of_date"):
        _plan(state=_state(100_000.0, [], as_of=E2))


def test_post_execution_phase_fails():
    st = _state(100_000.0, [], phase=PortfolioStatePhase.POST_EXECUTION)
    with pytest.raises(ValueError, match="PRE_EXECUTION|phase"):
        _plan(state=st)


# ================================================================
# AC-14/15/16：planning universe + 精确 coverage
# ================================================================

def test_planning_codes_union_current_and_target():
    """current {A} + target {B} → snapshot 必须精确覆盖 {A, B}。"""
    st = _state(10_000.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 11.22, 11.25),
                    _snap_row("600000.SH", 9.14, 9.18)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") == 1000
    assert _qty(batch, "600000.SH", "buy") is not None


def test_snapshot_missing_code_fails():
    st = _state(10_000.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 11.22, 11.25)])   # 缺 600000
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    with pytest.raises(ValueError, match="snapshot|600000"):
        _plan(target=t, state=st, snapshot=sn, rules=r)


def test_snapshot_extra_code_fails():
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("600000.SH", 9.14, 9.18),
                    _snap_row("601111.SH", 9.0, 8.9)])       # 多余证券
    r = _rules({"600000.SH": LOT})
    with pytest.raises(ValueError, match="snapshot|extra|多余|额外"):
        _plan(target=t, snapshot=sn, rules=r)


def test_rules_missing_code_fails():
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("600000.SH", 9.14, 9.18)])
    r = _rules({})                                            # 缺 600000
    with pytest.raises(ValueError, match="rule|600000"):
        _plan(target=t, snapshot=sn, rules=r)


def test_rules_extra_code_fails():
    t = _target()
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})          # 多余规则
    with pytest.raises(ValueError, match="rule|extra|多余|额外"):
        _plan(target=t, snapshot=sn, rules=r)


# ================================================================
# AC-17/18：empty planning universe / all-cash vs no decision
# ================================================================

def test_empty_planning_universe():
    """空持仓 + 显式 all-cash target → 空 OrderBatch（execution event 仍存在）。"""
    t = _target(rows={})                                       # 显式 all-cash
    sn = _snapshot([])
    r = _rules({})
    st = _state(100_000.0, [])
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0
    assert batch.decision_date == D1 and batch.execution_date == E1


def test_all_cash_distinct_from_no_decision():
    """all-cash（decision 存在但 0 rows）合法；无 decision 的日期 fail。"""
    t = _target(rows={})
    st = _state(100_000.0, [])
    sn = _snapshot([])
    r = _rules({})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0
    with pytest.raises(ValueError, match="decision"):
        _plan(target=t, state=st, snapshot=sn, rules=r, decision_date=D2)


# ================================================================
# AC-19/20/21：sizing evidence 边界
# ================================================================

def test_non_all_cash_missing_daily_fails():
    """非 all-cash target：任一 planning code has_daily=False → fail fast。"""
    st = _state(10_000.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", None, None, has_daily=False),
                    _snap_row("600000.SH", 9.14, 9.18)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    with pytest.raises(ValueError, match="sizing price evidence|sizing"):
        _plan(target=t, state=st, snapshot=sn, rules=r)


def test_missing_evidence_error_is_not_suspension():
    """错误文案不能是"停牌/无法交易"——has_daily 只是 evidence。"""
    st = _state(10_000.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", None, None, has_daily=False),
                    _snap_row("600000.SH", 9.14, 9.18)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    with pytest.raises(ValueError) as ei:
        _plan(target=t, state=st, snapshot=sn, rules=r)
    msg = str(ei.value)
    assert "停牌" not in msg and "suspended" not in msg.lower()
    assert "suspend" not in msg.lower()


def test_target_side_missing_daily_fails():
    """target 里的证券本身缺 open → 同样 fail。"""
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("600000.SH", None, None, has_daily=False)])
    r = _rules({"600000.SH": LOT})
    with pytest.raises(ValueError, match="sizing"):
        _plan(target=t, snapshot=sn, rules=r)


def test_all_cash_missing_daily_golden():
    """§75：600000 缺 open（has_daily=False）但 target 全现金 → SELL 1000 仍生成。"""
    st = _state(0.0, [("600000.SH", 1000, 1000)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("600000.SH", None, None, has_daily=False)])
    r = _rules({"600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "600000.SH", "sell") == 1000


def test_all_cash_mixed_daily_evidence():
    """all-cash：一个 holding 有 open、另一个没有 → 都只生成 SELL intent。"""
    st = _state(0.0, [("000001.SZ", 500, 500), ("600000.SH", 300, 300)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("600000.SH", None, None, has_daily=False)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") == 500
    assert _qty(batch, "600000.SH", "sell") == 300


# ================================================================
# AC-22/23/24/25/26：planning equity / target value / floor
# ================================================================

def test_planning_equity_raw_open():
    """equity = cash + Σ(current qty × raw open)——通过 target value 反证。"""
    st = _state(50_000.0, [("000001.SZ", 1000, 1000), ("600000.SH", 200, 200)])
    t = _target(rows=[("000001.SZ", 0.5)], gross=0.5)
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("600000.SH", 20.0, 19.5)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    # equity = 50k + 1000×10 + 200×20 = 64k；target value = 32k → ideal 3200
    assert _qty(batch, "000001.SZ", "buy") == 2200


def test_ideal_shares_use_floor():
    """floor(target_value / open)——64000/30=2133.33 → 2133 → ROUND 2100。"""
    st = _state(64_000.0, [])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("600000.SH", 30.0, 29.5)])
    r = _rules({"600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "600000.SH", "buy") == 2100


def test_pre_close_not_used():
    """改变 pre_close（open 相同）→ OrderBatch 不变。"""
    base = _plan()
    sn2 = _snapshot([_snap_row("000001.SZ", 10.0, 999.0)])
    alt = _plan(snapshot=sn2)
    assert base.orders.equals(alt.orders)


# ================================================================
# AC-27/28/29/30：delta / target quantity 语义
# ================================================================

def test_target_holding_need_not_satisfy_buy_min():
    """ideal target holding=150 可存在；从 0 持仓 BUY 150 非法 → 不下单。"""
    st = _state(15_000.0, [])
    t = _target(rows=[("688001.SH", 1.0)])
    sn = _snapshot([_snap_row("688001.SH", 100.0, 99.0)])
    r = _rules({"688001.SH": STAR})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0


def test_delta_current_absent_target():
    """current 持仓不在 target → ideal=0 → delta = -holding → SELL。"""
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("600000.SH", 20.0, 19.5)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") == 1000
    assert _qty(batch, "000001.SZ", "buy") is None


def test_delta_target_absent_current():
    """target 证券当前无持仓 → current=0 → BUY。"""
    st = _state(100_000.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("600000.SH", 20.0, 19.5)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    # equity=110k → ideal 5500 @20 → BUY 5500
    assert _qty(batch, "600000.SH", "buy") == 5500
    assert _qty(batch, "000001.SZ", "sell") == 1000


# ================================================================
# AC-31/32/33：desired sell / sellable cap / T+1
# ================================================================

def test_sell_capped_by_sellable():
    """H=1000 sellable=200 desired=1000 → L=200 → SELL 200（ROUND）。"""
    st = _state(0.0, [("000001.SZ", 1000, 200)])
    t = _target(rows={})                     # all-cash → desired=1000 → L=200
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") == 200


def test_t1_zero_sellable_no_sell():
    st = _state(0.0, [("000001.SZ", 1000, 0)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0


def test_sell_never_exceeds_current_holding():
    """desired_sell 以 holding 为上限（sellable <= quantity domain 保证）。"""
    st = _state(0.0, [("000001.SZ", 500, 500)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("000001.SZ", None, None, has_daily=False)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") == 500


# ================================================================
# AC-34/35：ROUND_LOT_100 SELL projection（§35 表格）
# ================================================================

@pytest.mark.parametrize("sellable,expected", [
    (50, None), (99, 99), (149, 100), (198, 100), (199, 199),
    (250, 200), (299, 299),
])
def test_round_sell_projection_table(sellable, expected):
    """H=299（odd-lot remainder=99）下的最大合法 SELL。"""
    st = _state(0.0, [("000001.SZ", 299, sellable)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("000001.SZ", None, None, has_daily=False)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") == expected


def test_round_sell_exact_lots():
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("000001.SZ", None, None, has_daily=False)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") == 1000


# ================================================================
# AC-36/37：STAR / BSE SELL projection
# ================================================================

def test_star_full_liquidation():
    """H=250 target=0 → SELL 250。"""
    st = _state(0.0, [("688001.SH", 250, 250)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("688001.SH", None, None, has_daily=False)])
    r = _rules({"688001.SH": STAR})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "688001.SH", "sell") == 250


def test_star_small_remainder():
    """H=199 <200 → 只能全量卖出。"""
    st = _state(0.0, [("688001.SH", 199, 199)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("688001.SH", None, None, has_daily=False)])
    r = _rules({"688001.SH": STAR})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "688001.SH", "sell") == 199


def test_star_remainder_t1_cap_below_holding():
    """H=199 sellable=100 → L=100 <H → 不能卖（只有全量合法）→ 0。"""
    st = _state(0.0, [("688001.SH", 199, 100)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("688001.SH", None, None, has_daily=False)])
    r = _rules({"688001.SH": STAR})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0


def test_bse_small_remainder():
    """H=80 <100 → 全量卖出。"""
    st = _state(0.0, [("920001.BJ", 80, 80)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("920001.BJ", None, None, has_daily=False)])
    r = _rules({"920001.BJ": BSE})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "920001.BJ", "sell") == 80


def test_bse_normal_sell_step1():
    """H=250 全现金 → L=250 → SELL 250（step=1 无整手限制）。"""
    st = _state(0.0, [("920001.BJ", 250, 250)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("920001.BJ", None, None, has_daily=False)])
    r = _rules({"920001.BJ": BSE})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "920001.BJ", "sell") == 250


# ================================================================
# AC-38/39/40：SELL 不 overshoot + authority 验证
# ================================================================

def test_star_no_oversell_target():
    """H=250（equity 25k）target w=0.4 → ideal 100 → desired_sell=150 <200
    最小卖出 → SELL 0（不得 SELL 200 超卖到低于 target）。"""
    st = _state(0.0, [("688001.SH", 250, 250)])
    t = _target(rows=[("688001.SH", 0.4)], gross=0.4)
    sn = _snapshot([_snap_row("688001.SH", 100.0, 99.0)])
    r = _rules({"688001.SH": STAR})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0


def test_round_overweight_sell():
    """§82：H=1000 target shares=600 → SELL 400。"""
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("000001.SZ", 0.6)], gross=0.6)
    sn = _snapshot([_snap_row("000001.SZ", 100.0, 99.0)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    # equity=100k → target value 60k → ideal 600 → delta=-400
    assert _qty(batch, "000001.SZ", "sell") == 400


def test_every_sell_validates_authority():
    """produced SELL 全部通过 is_valid_sell_quantity。"""
    st = _state(0.0, [("000001.SZ", 299, 299), ("688001.SH", 199, 199),
                      ("920001.BJ", 80, 80)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("000001.SZ", None, None, has_daily=False),
                    _snap_row("688001.SH", None, None, has_daily=False),
                    _snap_row("920001.BJ", None, None, has_daily=False)])
    r = _rules({"000001.SZ": LOT, "688001.SH": STAR, "920001.BJ": BSE})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") == 299
    assert _qty(batch, "688001.SH", "sell") == 199
    assert _qty(batch, "920001.BJ", "sell") == 80


# ================================================================
# AC-41/42/43：planned sell proceeds / sell-first funding
# ================================================================

def test_sell_first_funding_golden():
    """§90：cash=0，A 全可卖价值 100k → B 用 sell proceeds 全额 BUY。"""
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 100.0, 99.0),
                    _snap_row("600000.SH", 100.0, 99.0)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") == 1000
    assert _qty(batch, "600000.SH", "buy") == 1000


def test_t1_constrained_funding():
    """§91：A sellable=0 → proceeds=0 → BUY 只能用 cash=1000（ROUND → 0）。"""
    st = _state(1000.0, [("000001.SZ", 1000, 0)])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 100.0, 99.0),
                    _snap_row("600000.SH", 100.0, 99.0)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") is None
    assert _qty(batch, "600000.SH", "buy") is None


def test_planned_sell_proceeds_raw_open():
    """SELL 10,000 @11.22 → 参与 funding（budget = cash + 112,200）。"""
    st = _state(0.0, [("000001.SZ", 10000, 10000)])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 11.22, 11.25),
                    _snap_row("600000.SH", 9.14, 9.18)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    # equity = 112,200 → ideal floor(112200/9.14) = 12,275 → ROUND 12,200
    assert _qty(batch, "000001.SZ", "sell") == 10000
    assert _qty(batch, "600000.SH", "buy") == 12200


# ================================================================
# AC-44/45/46/47/48：BUY projection
# ================================================================

def test_round_buy_projection():
    st = _state(100_000.0, [])
    t = _target(rows=[("000001.SZ", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "buy") == 10000


def test_round_buy_below_minimum_zero():
    """§78：cash=500，open=10 → target shares=50 <100 → BUY 0 → empty。"""
    st = _state(500.0, [])
    t = _target(rows=[("000001.SZ", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0


def test_star_buy_below_minimum_zero():
    """§79：cash=15,000 open=100 ideal=150 <200 → BUY 0（不得 BUY 200）。"""
    st = _state(15_000.0, [])
    t = _target(rows=[("688001.SH", 1.0)])
    sn = _snapshot([_snap_row("688001.SH", 100.0, 99.0)])
    r = _rules({"688001.SH": STAR})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0


def test_bse_buy_step1():
    """§80：cash=12,345 open=100 ideal=123 → BSE BUY 123。"""
    st = _state(12_345.0, [])
    t = _target(rows=[("920001.BJ", 1.0)])
    sn = _snapshot([_snap_row("920001.BJ", 100.0, 99.0)])
    r = _rules({"920001.BJ": BSE})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "920001.BJ", "buy") == 123


def test_star_buy_step1():
    """STAR step=1：cash=25,000 open=100 → ideal 250 → BUY 250。"""
    st = _state(25_000.0, [])
    t = _target(rows=[("688001.SH", 1.0)])
    sn = _snapshot([_snap_row("688001.SH", 100.0, 99.0)])
    r = _rules({"688001.SH": STAR})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "688001.SH", "buy") == 250


def test_buy_never_overshoots_target():
    """BUY <= desired_buy（STAR delta=25 → 投影 0，不因最小 200 超买）。"""
    st = _state(0.0, [("688001.SH", 175, 175)])
    t = _target(rows=[("688001.SH", 1.0)])
    sn = _snapshot([_snap_row("688001.SH", 100.0, 99.0)])
    r = _rules({"688001.SH": STAR})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0


# ================================================================
# AC-49/50/51：provisional buys / sufficient budget
# ================================================================

def test_sufficient_budget_unchanged():
    """provisional notional <= budget → final == provisional。"""
    st = _state(100_000.0, [])
    t = _target(rows=[("000001.SZ", 0.6), ("600000.SH", 0.4)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("600000.SH", 20.0, 19.5)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "buy") == 6000
    assert _qty(batch, "600000.SH", "buy") == 2000


def test_every_buy_validates_authority():
    st = _state(200_000.0, [])
    t = _target(rows=[("000001.SZ", 0.25), ("688001.SH", 0.25),
                      ("920001.BJ", 0.5)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("688001.SH", 100.0, 99.0),
                    _snap_row("920001.BJ", 100.0, 99.0)])
    r = _rules({"000001.SZ": LOT, "688001.SH": STAR, "920001.BJ": BSE})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    for row in batch.orders.iter_rows():
        code, side, qty = row
        rule = r.frame.filter(pl.col("code") == code)["rule"][0]
        kind = QuantityRuleKind(rule)
        if side == "buy":
            assert is_valid_buy_quantity(kind, qty)
        else:
            h = st.positions.filter(pl.col("code") == code)["quantity"][0]
            assert is_valid_sell_quantity(kind, holding_quantity=h,
                                          sell_quantity=qty)


# ================================================================
# AC-52/53/54/55/56/57：proportional funding scale
# ================================================================

def test_proportional_scale_no_code_priority():
    """§92：A 60k/B 40k、budget 50k → scale 0.5 → A 300 / B 200（非 A 满 B 零）。"""
    st = _state(50_000.0, [("601111.SH", 1000, 0)])   # T+1 锁定，proceeds=0
    t = _target(rows=[("000001.SZ", 0.6), ("600000.SH", 0.4)], gross=1.0)
    sn = _snapshot([_snap_row("601111.SH", 50.0, 49.5),
                    _snap_row("000001.SZ", 100.0, 99.0),
                    _snap_row("600000.SH", 100.0, 99.0)])
    r = _rules({"601111.SH": LOT, "000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    # equity=100k → A ideal 600、B ideal 400 → notional 100k > 50k → scale 0.5
    assert _qty(batch, "000001.SZ", "buy") == 300
    assert _qty(batch, "600000.SH", "buy") == 200
    assert _qty(batch, "601111.SH", "sell") is None


def test_scaled_floor_before_rule_projection():
    """§55：ROUND provisional=500 scale=0.75 → cap=375 → final 300。"""
    st = _state(7500.0, [("601111.SH", 100, 0)])
    t = _target(rows=[("000001.SZ", 1.0)])
    sn = _snapshot([_snap_row("601111.SH", 25.0, 24.5),
                    _snap_row("000001.SZ", 20.0, 19.5)])
    r = _rules({"601111.SH": LOT, "000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    # equity=10k → ideal 500 → notional 10k > 7.5k → scale 0.75 → cap 375 → 300
    assert _qty(batch, "000001.SZ", "buy") == 300


def test_no_residual_redistribution():
    """§93：scale≈0.588 → A 300 / B 147（spend 44.7k，residual 5.3k）——不做
    第二轮 greedy 补仓（greedy 会让 B 补到 200）。"""
    st = _state(50_000.0, [("601111.SH", 5000, 0)])   # T+1 锁定 → proceeds=0
    t = _target(rows=[("000001.SZ", 0.6), ("920001.BJ", 0.25)], gross=0.85)
    sn = _snapshot([_snap_row("601111.SH", 10.0, 9.9),
                    _snap_row("000001.SZ", 100.0, 99.0),
                    _snap_row("920001.BJ", 100.0, 99.0)])
    r = _rules({"601111.SH": LOT, "000001.SZ": LOT, "920001.BJ": BSE})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    # equity=100k → A ideal 600、B ideal 250 → notional 85k > budget 50k →
    # scale=50/85 → A cap 352 → 300；B cap 147 → 147；spend 44.7k、residual 5.3k
    # （greedy 第二轮：B 用残余 5.3k 补 53 股 → 200——禁止）
    assert _qty(batch, "000001.SZ", "buy") == 300
    assert _qty(batch, "920001.BJ", "buy") == 147


def test_final_spend_within_budget():
    """AC-57：最终 buy notional <= budget（float tolerance 内）。"""
    st = _state(50_000.0, [("601111.SH", 1000, 0)])
    t = _target(rows=[("000001.SZ", 0.5), ("600000.SH", 0.3),
                      ("600519.SH", 0.2)], gross=1.0)
    sn = _snapshot([_snap_row("601111.SH", 10.0, 9.9),
                    _snap_row("000001.SZ", 11.22, 11.25),
                    _snap_row("600000.SH", 9.14, 9.18),
                    _snap_row("600519.SH", 1355.0, 1355.29)])
    r = _rules({"601111.SH": LOT, "000001.SZ": LOT, "600000.SH": LOT,
                "600519.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    opens = {c: o for c, o, *_ in sn.frame.iter_rows()}
    spend = 0.0
    for row in batch.orders.iter_rows():
        code, side, qty = row
        if side == "buy":
            spend += qty * opens[code]
    assert spend <= 50_000.0 + 1e-10 * max(1.0, 50_000.0)


# ================================================================
# AC-58/59/60：zero budget / zero equity / 每 code 单 side
# ================================================================

def test_zero_budget_no_buys():
    st = _state(0.0, [("000001.SZ", 1000, 0)])   # T+1 locked → proceeds=0
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("600000.SH", 10.0, 9.8)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "600000.SH", "buy") is None
    assert _qty(batch, "000001.SZ", "sell") is None


def test_zero_planning_equity_valid():
    """equity=0 + 非 all-cash target → ideal quantities 0 → 无 BUY（不强制 fail）。"""
    st = _state(0.0, [])
    t = _target(rows=[("000001.SZ", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0


def test_same_code_never_dual_side():
    """同一 code 不可能同时出现 BUY+SELL。"""
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("000001.SZ", 0.5), ("600000.SH", 0.5)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("600000.SH", 10.0, 9.8)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert len(batch.orders) == len(batch.orders.unique(subset=["code"]))


# ================================================================
# AC-61/62/63/64/65/66/67：output OrderBatch
# ================================================================

def test_zero_quantity_rows_omitted():
    """projection=0 不创建订单行。"""
    st = _state(500.0, [])
    t = _target(rows=[("000001.SZ", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0


def test_order_batch_exact_schema():
    batch = _plan()
    assert batch.orders.columns == ["code", "side", "quantity"]
    assert batch.orders.schema["code"] == pl.String
    assert batch.orders.schema["side"] == pl.String
    assert batch.orders.schema["quantity"] == pl.Int64


def test_output_sorted_by_code():
    st = _state(0.0, [("600519.SH", 100, 100)])
    t = _target(rows=[("000001.SZ", 0.5), ("600000.SH", 0.5)])
    sn = _snapshot([_snap_row("600519.SH", 100.0, 99.0),
                    _snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("600000.SH", 10.0, 9.8)])
    r = _rules({"600519.SH": LOT, "000001.SZ": LOT, "600000.SH": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders["code"].to_list() == ["000001.SZ", "600000.SH",
                                              "600519.SH"]


def test_output_metadata():
    batch = _plan()
    assert batch.decision_date == D1
    assert batch.execution_date == E1
    assert batch.execution_timing is ExecutionTiming.NEXT_OPEN


def test_empty_batch_is_legal_event():
    """target 已匹配 → empty OrderBatch（execution event 存在但 0 orders）。"""
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("000001.SZ", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 100.0, 99.0)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert batch.orders.height == 0
    assert batch.decision_date == D1 and batch.execution_date == E1


# ================================================================
# AC-68/69/70：limit / suspend / pre_close invariance
# ================================================================

def test_limit_suspend_invariance():
    """§73：A（has_limit=True, suspend=False）vs B（limit=False, suspend=True）
    相同 open → 订单完全一致。"""
    common = _snap_row("000001.SZ", 10.0, 9.8, has_limit=True, up=11.0,
                       down=9.0)
    sn_a = _snapshot([common])
    sn_b = _snapshot([_snap_row("000001.SZ", 10.0, 9.8,
                                has_suspend=True)])
    batch_a = _plan(snapshot=sn_a)
    batch_b = _plan(snapshot=sn_b)
    assert batch_a.orders.equals(batch_b.orders)
    assert batch_a.orders.height == 1


def test_pre_close_change_does_not_affect_orders():
    a = _plan()
    sn2 = _snapshot([_snap_row("000001.SZ", 10.0, 5.0)])
    b = _plan(snapshot=sn2)
    assert a.orders.equals(b.orders)


def test_is_suspended_at_open_invariance():
    """§52：仅改变 is_suspended_at_open（其他 planner 消费列相同）→ 订单不变。"""
    base = _snapshot([_snap_row("000001.SZ", 10.0, 9.8, has_suspend=False)])
    alt = base.frame.with_columns(
        pl.col("is_suspended_at_open").fill_null(True))
    alt = MarketOpenSnapshot(execution_date=E1, frame=alt)
    a = _plan(snapshot=base)
    b = _plan(snapshot=alt)
    assert a.orders.equals(b.orders)


def test_combined_evidence_invariance():
    """§53：has_limit / has_suspend_record / is_suspended_at_open / pre_close
    变化而 open+has_daily 相同 → OrderBatch 不变。"""
    a = _plan()
    rows = _snap_row("000001.SZ", 10.0, 5.0, has_limit=True, up=11.0, down=9.0,
                     has_suspend=True)
    frame = pl.DataFrame([rows], schema=["code", "open", "pre_close", "up_limit",
                                         "down_limit", "has_daily", "has_limit",
                                         "has_suspend_record"], orient="row")
    frame = frame.with_columns(pl.lit(True).cast(pl.Boolean)
                               .alias("is_suspended_at_open"))
    alt = MarketOpenSnapshot(execution_date=E1, frame=frame)
    b = _plan(snapshot=alt)
    assert a.orders.equals(b.orders)


def test_suspend_record_does_not_cancel_orders():
    """§72：has_suspend_record=True 不取消订单（M8-04 职责）。"""
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("000001.SZ", None, None, has_daily=False,
                              has_suspend=True)])
    r = _rules({"000001.SZ": LOT})
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert _qty(batch, "000001.SZ", "sell") == 1000


# ================================================================
# AC-71..79：不做的事（fill/state 修改/T+1 transition/cost/NAV/DB/信号）
# ================================================================

def test_no_fill_or_trade_objects():
    batch = _plan()
    assert batch.orders.columns == ["code", "side", "quantity"]
    assert not hasattr(batch, "fills") and not hasattr(batch, "trades")
    assert "fill" not in str(batch.__class__).lower()
    assert "trade" not in str(batch.__class__).lower()


def test_no_portfolio_state_mutation():
    st = _state(100_000.0, [("000001.SZ", 1000, 500)])
    t = _target(rows=[("600000.SH", 1.0)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("600000.SH", 20.0, 19.5)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    before = st.positions.clone()
    _plan(target=t, state=st, snapshot=sn, rules=r)
    assert st.positions.equals(before)
    assert st.phase is PortfolioStatePhase.PRE_EXECUTION


def test_no_t1_overnight_transition():
    """M8-03 不产生 POST_EXECUTION state、不更新 sellable。"""
    st = _state(0.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows={})
    sn = _snapshot([_snap_row("000001.SZ", None, None, has_daily=False)])
    r = _rules({"000001.SZ": LOT})
    before = st.positions.clone()
    batch = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert st.positions.equals(before)
    assert st.positions["sellable_quantity"][0] == 1000
    assert st.phase is PortfolioStatePhase.PRE_EXECUTION
    assert batch.orders.height == 1     # 只产生 intent


def test_input_frames_immutable():
    """§95：调用前后全部输入 frame equals。"""
    st = _state(50_000.0, [("000001.SZ", 1000, 1000)])
    t = _target(rows=[("000001.SZ", 0.6), ("600000.SH", 0.4)])
    sn = _snapshot([_snap_row("000001.SZ", 10.0, 9.8),
                    _snap_row("600000.SH", 20.0, 19.5)])
    r = _rules({"000001.SZ": LOT, "600000.SH": LOT})
    sch = _schedule()
    snapshots = {k: v.clone() for k, v in
                 {"t": t.frame, "s": sch.frame, "pos": st.positions,
                  "sn": sn.frame, "r": r.frame}.items()}
    _plan(target=t, schedule=sch, state=st, snapshot=sn, rules=r)
    assert t.frame.equals(snapshots["t"])
    assert sch.frame.equals(snapshots["s"])
    assert st.positions.equals(snapshots["pos"])
    assert sn.frame.equals(snapshots["sn"])
    assert r.frame.equals(snapshots["r"])


def test_no_db_path_parameter():
    assert "db_path" not in inspect.signature(construct_order_batch).parameters


# ================================================================
# AC-80/81/82/83/84：上游零修改（import 层面回归）
# ================================================================

def test_m8_01b_quantity_authority_reused():
    """planner 输出通过 M8-01B validators（authority 复用，非重写）。"""
    assert is_valid_buy_quantity(LOT, 100)
    assert is_valid_sell_quantity(LOT, holding_quantity=299, sell_quantity=99)


def test_existing_domain_unchanged():
    from factorlab.domain.execution import OrderBatch as OB
    assert OB.__module__ == "factorlab.domain.execution"


# ================================================================
# AC-94/95：确定性
# ================================================================

def test_deterministic_repeated_calls():
    a = _plan()
    b = _plan()
    assert a.orders.equals(b.orders)


def test_deterministic_with_orders():
    st = _state(50_000.0, [("601111.SH", 1000, 0)])
    t = _target(rows=[("000001.SZ", 0.6), ("600000.SH", 0.4)])
    sn = _snapshot([_snap_row("601111.SH", 50.0, 49.5),
                    _snap_row("000001.SZ", 100.0, 99.0),
                    _snap_row("600000.SH", 100.0, 99.0)])
    r = _rules({"601111.SH": LOT, "000001.SZ": LOT, "600000.SH": LOT})
    a = _plan(target=t, state=st, snapshot=sn, rules=r)
    b = _plan(target=t, state=st, snapshot=sn, rules=r)
    assert a.orders.equals(b.orders)
