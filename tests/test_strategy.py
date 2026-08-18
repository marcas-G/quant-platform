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


def test_monte_carlo_deterministic_with_seed():
    # 固定 seed → 结果确定；n_sims 与分位数结构完整
    from tools.strategy_crash_bottom import monte_carlo
    r = strategy_backtest(_panel(), k=2, cost_bps=0)
    mc1 = monte_carlo(r["weekly_returns"], r["episodes"], n_sims=50, seed=7)
    mc2 = monte_carlo(r["weekly_returns"], r["episodes"], n_sims=50, seed=7)
    assert mc1 == mc2
    for k in ("nav", "annual_return_active", "annual_return_total", "sharpe", "max_drawdown"):
        assert len(mc1["dist"][k]) == 5  # p5/p25/p50/p75/p95
    assert mc1["risk"]["p_active_negative"] <= 1.0


def test_monte_carlo_episode_mode_uses_episode_blocks():
    # episode 模式采样单元 = 段数；week 模式 = 周数
    from tools.strategy_crash_bottom import monte_carlo
    r = strategy_backtest(_panel(), k=2, cost_bps=0)
    mc_ep = monte_carlo(r["weekly_returns"], r["episodes"], n_sims=20, mode="episode")
    mc_wk = monte_carlo(r["weekly_returns"], r["episodes"], n_sims=20, mode="week")
    assert mc_ep["n_units"] == len(r["episodes"])
    assert mc_wk["n_units"] == r["weeks"]
    assert mc_ep["risk"]["p_active_negative"] <= 1.0


def test_monte_carlo_unknown_mode_raises():
    from tools.strategy_crash_bottom import monte_carlo
    with pytest.raises(ValueError, match="mc"):
        monte_carlo([0.01], [{"returns": [0.01]}], n_sims=5, mode="bad")


def test_strategy_rebalance_two_weeks_holds_positions():
    # rebalance=2：周 0 选 A/B，周 1 持仓不动（收益 = A/B 的周 1 收益），周 2 再调仓
    rows = []
    for w in range(3):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i,
                "forward_return_5d": 0.04 - i * 0.01,  # A=4% B=3%
            })
    r = strategy_backtest(pl.DataFrame(rows), k=2, cost_bps=0, rebalance_weeks=2)
    # 周 0 调仓（选 A/B，换手 100%，收益 3.5%）；周 1 持仓不动（A/B 周 1 收益 3.5%，换手 0）；
    # 周 2 再调仓（仍选 A/B，换手 0，收益 3.5%）
    assert r["avg_turnover"] == pytest.approx(1 / 3, abs=1e-9)
    assert r["nav"] == pytest.approx(1.035 ** 3, rel=1e-9)


def test_strategy_rebalance_two_weeks_turnover_halved_vs_weekly():
    # 换手对照：rebalance=2 的换手 ≤ 周频（持仓重叠周不换）
    p1 = strategy_backtest(_panel(), k=2, cost_bps=0)
    p2 = strategy_backtest(_panel(), k=2, cost_bps=0, rebalance_weeks=2)
    assert p2["avg_turnover"] <= p1["avg_turnover"]


def test_strategy_take_profit_sells_winners():
    # 止盈 +15%：周 0 买入 A/B（累计 1.0），周 1 A/B 涨 20% → 累计 1.2 止盈卖出 → 周 2 补仓新股
    rows = []
    for w, fwd_a in ((0, 0.10), (1, 0.20), (2, 0.02)):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i,
                "forward_return_5d": fwd_a if code == "A" else 0.01,
            })
    r = strategy_backtest(pl.DataFrame(rows), k=2, cost_bps=0,
                          take_profit=0.15, max_hold=10)
    # 周 0：买入 A/B，收益 (10%+1%)/2；周 1：A 累计 1.32 触发止盈（B 累计 1.0201 不触发）
    #   → 卖出 A，收益 (20%+1%)/2；周 2：补仓 C（A 冷却排除，C fwd=+1%），收益 (1%+1%)/2
    expected = (1 + 0.11/2) * (1 + 0.21/2) * (1 + 0.01)
    assert r["nav"] == pytest.approx(expected, rel=1e-9)


def test_strategy_stock_stop_loss_cuts_losers():
    # 个股止损 -10%：周 1 A 跌 15% → 累计 0.85 触发止损卖出
    rows = []
    for w, fwd_a in ((0, 0.05), (1, -0.15), (2, -0.02)):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i,
                "forward_return_5d": fwd_a if code == "A" else 0.01,
            })
    r = strategy_backtest(pl.DataFrame(rows), k=2, cost_bps=0,
                          stock_stop_loss=0.10, max_hold=10)
    # 周 0：买入 A/B，收益 (5%+1%)/2；周 1：A 累计 0.8925 触发止损 → 卖出，收益 (-15%+1%)/2
    # 周 2：补仓 C（A 冷却排除），收益 (1%+1%)/2
    expected = (1 + 0.06/2) * (1 + (-0.14)/2) * (1 + 0.01)
    assert r["nav"] == pytest.approx(expected, rel=1e-9)


def test_strategy_max_hold_forces_exit():
    # 最长持有 2 周：周 2 持仓到期强制卖出（即使浮盈未到止盈）
    rows = []
    for w in range(3):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i, "forward_return_5d": 0.02,
            })
    r = strategy_backtest(pl.DataFrame(rows), k=2, cost_bps=0, max_hold=2)
    # 周 0 买入（held=1）；周 1 held=2 → 到期卖出；周 2 补仓新仓（held=1）
    # 收益 = 3 周各 (2%+2%)/2 = 2%
    assert r["nav"] == pytest.approx(1.02 ** 3, rel=1e-9)


def test_strategy_k_buy_gate_keeps_cash_when_no_strong_signals():
    # 买入门槛：止损卖出 A 后，补仓池限信号排名前 1（A 被排除 → 只剩 C）→ 补入 C
    # 若 k_buy=1 且 C 不在前 1（C 排第 3）→ 缺口空仓（收益只计 B）
    rows = []
    for w, fwd_a in ((0, 0.05), (1, -0.15), (2, 0.01)):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i,  # A=4 B=3 C=2 D=1
                "forward_return_5d": fwd_a if code == "A" else 0.01,
            })
    r = strategy_backtest(pl.DataFrame(rows), k=2, cost_bps=0,
                          stock_stop_loss=0.10, max_hold=10, k_buy=1)
    # 周 0：买入 A/B（入场不受 k_buy 限制），收益 3%；周 1：A 止损卖出（收益 -7%）；
    # 周 2：补仓池 = 信号前 1 且未持仓未卖出 → D（A 排除、B 已持）→ 收益 (B 1% + D 1%)/2
    expected = (1 + 0.03) * (1 - 0.07) * (1 + 0.01)
    assert r["nav"] == pytest.approx(expected, rel=1e-9)


def test_strategy_long_batch_entry_and_repair_exit():
    # 危机修复模式：触发 2 周（mkt20<-8%）→ 每周买 1/2 仓（batches=2, gap=1）；
    # 修复（mkt20>=0）→ 全仓退出
    from tools.strategy_crash_bottom import strategy_long_backtest
    rows = []
    mkt = []
    for w, m in ((0, -0.10), (1, -0.09), (2, 0.01)):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        mkt.append({"date": d, "mkt20": m})
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i, "forward_return_5d": 0.02,
            })
    panel = pl.DataFrame(rows)
    mkt20 = pl.DataFrame(mkt)
    r = strategy_long_backtest(panel, k=2, cost_bps=0, mkt20=mkt20,
                               batches=2, batch_gap=1, repair_threshold=0.0)
    # 周 0：触发，买批 1（A/B，半仓）→ 收益 0.5×2% = 1%
    # 周 1：仍触发，买批 2（满仓）→ 收益 1.0×2% = 2%
    # 周 2：修复退出 → 0
    assert r["nav"] == pytest.approx(1.01 * 1.02, rel=1e-9)
    assert r["episodes"][0]["weeks"] == 2


def test_strategy_long_stops_adding_when_trigger_ends():
    # 掩码恢复（-4%）但未修复（<0）：停止加仓、继续持有（不退出）
    from tools.strategy_crash_bottom import strategy_long_backtest
    rows = []
    mkt = []
    for w, m in ((0, -0.10), (1, -0.04), (2, -0.02)):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        mkt.append({"date": d, "mkt20": m})
        for i, code in enumerate(("A", "B", "C", "D")):
            rows.append({
                "date": d, "code": code,
                "signal": 4.0 - i, "forward_return_5d": 0.02,
            })
    r = strategy_long_backtest(pl.DataFrame(rows), k=2, cost_bps=0,
                               mkt20=pl.DataFrame(mkt),
                               batches=4, batch_gap=1, repair_threshold=0.0)
    # 周 0：触发买批 1（半仓？batches=4 → 25%）收益 0.25×2%
    # 周 1：掩码恢复（-4% > -8%）→ 不加仓，持仓 25% 继续：收益 0.25×2%
    # 周 2：仍持有：收益 0.25×2%
    expected = (1 + 0.25 * 0.02) ** 3
    assert r["nav"] == pytest.approx(expected, rel=1e-9)
    assert r["episodes"][0]["weeks"] == 3
