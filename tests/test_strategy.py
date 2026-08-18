"""tools/strategy_crash_bottom.py 策略回测核心逻辑测试：top-K 选股、换手、成本、净值。"""
import datetime

import polars as pl
import pytest

from tools.strategy_crash_bottom import strategy_backtest


def _panel() -> pl.DataFrame:
    """3 个触发周 × 4 股票：signal 降序 A>B>C>D，forward 与之正相关（A 最强）。"""
    rows = []
    for w in range(3):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i,          # A=4 B=3 C=2 D=1
                "forward_return_5d": 0.04 - i * 0.01,  # A=4% B=3% C=2% D=1%
            })
    return pl.DataFrame(rows)


def test_strategy_top_k_equal_weight_and_nav():
    # K=2：每周选 A/B 等权 → 周收益 = (4%+3%)/2 = 3.5%；成本 0 → 净值 = 1.035^3
    r = strategy_backtest(_panel(), k=2, cost_bps=0)
    assert r["weeks"] == 3
    assert r["nav"] == pytest.approx(1.035 ** 3, rel=1e-9)
    assert r["total_cost"] == 0.0


def test_strategy_cost_and_turnover():
    # K=2、第一周换手 100%（空仓→满仓），第二/三周持仓相同 → 换手 0
    r = strategy_backtest(_panel(), k=2, cost_bps=35)
    assert r["avg_turnover"] == pytest.approx(1 / 3, abs=1e-9)  # (1+0+0)/3
    # 第一周成本 = 100% × 0.35%，后续 0
    assert r["total_cost"] == pytest.approx(0.0035, abs=1e-9)
    # 净值 = (1+0.035-0.0035) × 1.035^2
    assert r["nav"] == pytest.approx((1 + 0.035 - 0.0035) * 1.035 ** 2, rel=1e-9)


def test_strategy_limit_down_excludes_unbuyable():
    # 跌停过滤：周 0 的 A 跌停（pct_chg=-10）→ 不可买 → 周 0 持仓 B/C → 收益 (3%+2%)/2
    ld = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5), datetime.date(2024, 1, 5)],
        "code": ["A", "B"], "pct_chg": [-10.0, 1.0],
    })
    r = strategy_backtest(_panel(), limit_down=ld, k=2, cost_bps=0)
    # 周 0：(3%+2%)/2=2.5%；周 1/2：3.5%
    assert r["nav"] == pytest.approx(1.025 * 1.035 ** 2, rel=1e-9)


def test_strategy_turnover_counts_new_holdings():
    # 周 0 选 A/B，周 1 signal 反转（D/C 最强）→ 全换；周 2 与周 1 相同 → 换手 0
    rows = []
    for w in range(3):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        order = ("A", "B", "C", "D") if w == 0 else ("D", "C", "B", "A")
        for i, code in enumerate(order):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i, "forward_return_5d": 0.02,
            })
    r = strategy_backtest(pl.DataFrame(rows), k=2, cost_bps=0)
    assert r["avg_turnover"] == pytest.approx((1 + 1 + 0) / 3, abs=1e-9)


def test_strategy_no_trigger_weeks():
    # 空面板（列齐全、无行）→ 无触发周，不崩溃
    empty = pl.DataFrame(schema=_panel().schema)
    r = strategy_backtest(empty, k=2, cost_bps=35)
    assert r["weeks"] == 0
    assert "error" in r


def test_strategy_skip_first_week_of_episode():
    # 触发段首周空仓：3 周连续触发 → 首周 w=0，净值 = 1.035^2（周 2/3 正常）
    r = strategy_backtest(_panel(), k=2, cost_bps=0, skip_first_week=True)
    assert r["nav"] == pytest.approx(1.035 ** 2, rel=1e-9)
    assert r["weeks"] == 3  # 仍计 3 个触发周（首周空仓但属于触发段）


def test_strategy_skip_first_week_resets_per_episode():
    # 断档后新触发段的首周再次跳过：3 周 + 断档 + 1 周 → 段 1 首周跳过、段 2 首周跳过
    rows = []
    for w, gap in ((0, 0), (1, 0), (2, 0), (4, 1)):  # 第 4 周与第 3 周断档（gap>10 天）
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w + gap)
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i, "forward_return_5d": 0.02,
            })
    r = strategy_backtest(pl.DataFrame(rows), k=2, cost_bps=0, skip_first_week=True)
    # 段 1（3 周）：首周跳过 → 2 周收益；段 2（1 周）：首周跳过 → 0 收益
    assert r["nav"] == pytest.approx(1.02 ** 2, rel=1e-9)


def test_strategy_intensity_scales_position():
    # 强度分级：-8% → w=0.5、-16% → w=1.0；净值 = ∏(1 + w×ret)
    mkt20 = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5),
                 datetime.date(2024, 1, 12),
                 datetime.date(2024, 1, 19)],
        "mkt20": [-0.08, -0.16, -0.08],
    })
    r = strategy_backtest(_panel(), k=2, cost_bps=0, mkt20=mkt20, intensity=True)
    expected = (1 + 0.5 * 0.035) * (1 + 1.0 * 0.035) * (1 + 0.5 * 0.035)
    assert r["nav"] == pytest.approx(expected, rel=1e-9)
    assert r["total_cost"] == 0.0


def test_strategy_stop_loss_exits_episode():
    # 段内回撤止损：周 1 组合 -20%（>15%）→ 周 2 起空仓；止损后段内不再入场
    rows = []
    for w, fwd in ((0, 0.05), (1, -0.20), (2, 0.05)):  # 周 2 反弹但已止损
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i, "forward_return_5d": fwd,
            })
    r = strategy_backtest(pl.DataFrame(rows), k=2, cost_bps=0, stop_loss=0.15)
    # 周 0 +5%、周 1 -20% → 回撤 20%>15% → 止损；周 2 空仓（w=0）
    assert r["nav"] == pytest.approx(1.05 * 0.80, rel=1e-9)
    assert any(ep.get("stopped") for ep in r["episodes"])


def test_strategy_stop_loss_below_threshold_holds():
    # 回撤未达阈值（-10% < 15%）不触发止损：3 周全部持仓
    rows = []
    for w, fwd in ((0, 0.05), (1, -0.10), (2, 0.05)):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i, "forward_return_5d": fwd,
            })
    r = strategy_backtest(pl.DataFrame(rows), k=2, cost_bps=0, stop_loss=0.15)
    assert r["nav"] == pytest.approx(1.05 * 0.90 * 1.05, rel=1e-9)
    assert not any(ep.get("stopped") for ep in r["episodes"])
