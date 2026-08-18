"""crash_bottom_leader 策略回测：因子信号 → 可执行策略。

策略规格（v1）：
- 市场状态：中证1000 20 日累计 < -8% 触发（signal 掩码，非触发期空仓）
- 选股：触发周按 signal 降序取 top K（默认 20），等权
- 调仓：周频（周五对齐），触发期每周按最新信号全换（换手 = 新增股票比例）
- 退出：掩码恢复 0 自动清仓
- 成本：双边费率 cost_bps（默认 35bps = 佣金 2.5×2 + 印花税 5 + 冲击 10×2）
- 可交易性：买入日跌停（pct_chg <= -9.8%）的股票排除（买不进）
- 持有收益：forward_return_5d（周频调仓恰好匹配 5 日持有期）

数据源：results/<name>/panel.parquet（date/code/signal/forward_return_5d）
+ 平台库 daily 的 pct_chg（跌停过滤）。
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import polars as pl

from factorlab.data.source import load_daily

K_DEFAULT = 20
COST_BPS_DEFAULT = 35  # 双边（买入+卖出），基点
LIMIT_DOWN = -9.8  # 主板跌停识别阈值（pct_chg <= 该值视为跌停买不进）


def load_panel(panel_path: Path) -> pl.DataFrame:
    return pl.read_parquet(panel_path)


def load_mkt20(db_path: Path) -> pl.DataFrame:
    """中证1000 20 日累计收益（date/mkt20 两列）：index_daily 单表全段（~2800 行），
    按触发周买入日 join 用——用于触发强度分级仓位。"""
    import duckdb
    with duckdb.connect(str(db_path), read_only=True) as con:
        idx = con.execute(
            "SELECT trade_date, pct_chg FROM index_daily "
            "WHERE ts_code = '000852.SH' ORDER BY trade_date",
        ).pl()
    mkt20 = idx.with_columns(
        pl.col("trade_date").str.strptime(pl.Date, "%Y%m%d").alias("date"),
        (pl.col("pct_chg") / 100.0).alias("idx_ret"),
    ).sort("date").with_columns(
        pl.col("idx_ret").rolling_sum(20).alias("mkt20"),
    ).select(["date", "mkt20"])
    return mkt20.drop_nulls()


def strategy_backtest(
    panel: pl.DataFrame,
    limit_down: pl.DataFrame | None = None,
    k: int = K_DEFAULT,
    cost_bps: int = COST_BPS_DEFAULT,
    mkt20: pl.DataFrame | None = None,
    intensity: bool = False,
    skip_first_week: bool = False,
    stop_loss: float | None = None,
    rebalance_weeks: int = 1,
    take_profit: float | None = None,
    stock_stop_loss: float | None = None,
    max_hold: int | None = None,
    k_buy: int | None = None,
) -> dict:
    """触发期 top-K 等权周频调仓回测。返回指标 + 每轮触发明细。"""
    weekly = panel.sort(["date", "code"])
    # 触发周 = signal 非 null 的周（掩码激活）；周内按 signal 排序取 top K
    weekly = weekly.with_columns(
        pl.col("date").max().over(
            pl.col("date").dt.iso_year().alias("_y"),
            pl.col("date").dt.week().alias("_w"),
        ).alias("_week_end"),
    )
    weekly = weekly.filter(pl.col("date") == pl.col("_week_end")).drop("_week_end")
    if limit_down is not None:
        weekly = weekly.join(limit_down, on=["date", "code"], how="left")
        weekly = weekly.filter(pl.col("pct_chg").fill_null(0.0) > LIMIT_DOWN)
    active = weekly.filter(pl.col("signal").is_not_null())
    if mkt20 is not None:
        active = active.join(mkt20, on="date", how="left")

    # 逐周组合：top K 等权，换手 = 与上周持仓的新增比例
    # holdings: set[str]（周频模式）或 dict[code, (cum_ret, weeks_held)]（止盈止损模式）
    use_rules = take_profit is not None or stock_stop_loss is not None or max_hold is not None
    holdings: set[str] | dict[str, tuple[float, int]] = set() if not use_rules else {}
    nav, cost_paid, turnover_sum = 1.0, 0.0, 0.0
    weeks, rets, turnovers, entry_weeks = [], [], [], []
    prev_week_end: pl.Date | None = None
    per_episode: dict = {}
    episodes: list[dict] = []
    seg_first = True  # 触发段首周标记（skip_first_week 用）
    seg_peak = 1.0  # 段内净值峰值（止损用）
    stopped = False  # 本段已止损退出（等下次触发段）
    cycle_week = 0  # 调仓周期内周数（rebalance_weeks：0=调仓周）

    for (week_end,), grp in active.sort("date").group_by("date", maintain_order=True):
        if prev_week_end is not None and week_end - prev_week_end > __import__("datetime").timedelta(days=10):
            # 触发断档：上一段结束
            episodes.append({**per_episode, "end": str(prev_week_end)})
            per_episode = {}
            seg_first = True
            seg_peak = 1.0
            stopped = False
        # 仓位权重：强度分级（-mkt20/0.16，-8% 半仓、-16% 满仓）与段首缓冲
        w = 1.0
        if skip_first_week and seg_first:
            w = 0.0
        elif stopped:
            w = 0.0  # 段内已止损：本段剩余周空仓，等指数修复重新触发
        elif intensity:
            m = float(grp["mkt20"].first()) if grp["mkt20"].first() is not None else 0.0
            w = min(1.0, -m / 0.16)
        seg_first = False
        if use_rules and w > 0:
            # 止盈止损持仓管理：周收益 = 周初持仓（卖出决策前）的当周 fwd5 均值；
            # 周末检查累计收益（止盈/止损/最长持有）→ 卖出 → 按信号补仓
            if not holdings:
                # 空仓入场：按信号买入 top K（段首缓冲后首周）
                sel = grp.sort("signal", descending=True).head(k)
                holdings = {c: (1.0, 0) for c in sel["code"].to_list()}
                turnover = 1.0
                hold_grp = sel
                fwd = hold_grp["forward_return_5d"].mean()
                ret = float(fwd) if fwd is not None else 0.0
            else:
                # 周收益先算：基于周初持仓（含本周将卖出股——它们持有到周末）
                hold_grp = grp.filter(pl.col("code").is_in(holdings))
                fwd = hold_grp["forward_return_5d"].mean()
                ret = float(fwd) if fwd is not None else 0.0
                sold: list[str] = []
                for code, (cum, held) in list(holdings.items()):
                    row = grp.filter(pl.col("code") == code)
                    if row.height:
                        fwd_val = row["forward_return_5d"][0]
                        r = float(fwd_val) if fwd_val is not None else 0.0  # 边界 null 视为无变动
                        cum2 = cum * (1 + r)
                    else:
                        cum2 = cum
                    held2 = held + 1
                    if (take_profit is not None and cum2 >= 1 + take_profit) \
                            or (stock_stop_loss is not None and cum2 <= 1 - stock_stop_loss) \
                            or (max_hold is not None and held2 >= max_hold):
                        sold.append(code)
                    else:
                        holdings[code] = (cum2, held2)
                turnover = len(sold) / k
                if sold:
                    for c in sold:
                        del holdings[c]
                    # 补仓：信号最强的未持仓股票（排除本周卖出——避免止损-买回循环损耗）。
                    # k_buy 买入门槛（<=k）：只买信号排名前 k_buy 的强股，缺口宁可空仓——
                    # 买入要求高于卖出要求 → 反弹末端信号转弱自动减仓、换手稳定
                    pool = grp.filter(
                        ~pl.col("code").is_in(holdings) & ~pl.col("code").is_in(sold),
                    ).sort("signal", descending=True).head(k_buy or k)
                    for c in pool["code"].to_list()[:len(sold)]:
                        holdings[c] = (1.0, 0)
        elif w > 0 and cycle_week == 0:
            # 调仓周：按最新 signal 重选 top K（换手 = 与上周持仓的新增比例）
            grp = grp.sort("signal", descending=True).head(k)
            codes = set(grp["code"].to_list())
            new_codes = codes - holdings
            turnover = len(new_codes) / k
            holdings = codes
        elif w > 0:
            # 非调仓周：持仓不动（吃更完整反弹），只计持仓股票收益
            grp = grp.filter(pl.col("code").is_in(list(holdings)))
            turnover = 0.0
        else:
            turnover = 0.0  # 空仓周（段首缓冲/止损/强度 0）：不换仓
        cost = turnover * cost_bps / 10000
        if not use_rules:
            fwd = grp["forward_return_5d"].mean()  # 分块块边界 forward null → mean 可为 None
            ret = float(fwd) if fwd is not None else 0.0
        elif w == 0:
            ret = 0.0  # 规则模式下空仓周（段首缓冲/止损）：无持仓无收益
        # 净值变化率 = 1 + w×收益 - w×换手×成本率（仓位缩放同时缩放收益与成交额）
        r_net = w * ret - w * turnover * cost_bps / 10000
        nav *= 1 + r_net
        if w > 0 and stop_loss is not None:
            seg_peak = max(seg_peak, nav)
            if nav / seg_peak < 1 - stop_loss:
                stopped = True  # 段内组合回撤超阈值：退出本段，剩余周空仓
        per_episode.setdefault("start", str(week_end))
        per_episode["weeks"] = per_episode.get("weeks", 0) + 1
        per_episode["cum_ret"] = per_episode.get("cum_ret", 1.0) * (1 + r_net)
        per_episode.setdefault("returns", []).append(r_net)  # 段内周收益（蒙特卡洛 block 单元）
        if stopped:
            per_episode["stopped"] = True
        cost_paid += w * cost
        turnover_sum += turnover
        if w > 0:
            cycle_week = (cycle_week + 1) % max(rebalance_weeks, 1)  # 空仓周不消耗调仓周期
        prev_week_end = week_end
        weeks.append(week_end)
        rets.append(r_net)
        turnovers.append(turnover)
    if per_episode:
        episodes.append({**per_episode, "end": str(prev_week_end)})

    import statistics
    n = len(rets)
    if n == 0:
        return {"weeks": 0, "error": "无触发周"}
    total = nav
    years = n / 52.0
    ann = total ** (1 / years) - 1 if years > 0 else 0.0
    mean_r = sum(rets) / n
    var = sum((r - mean_r) ** 2 for r in rets) / max(n - 1, 1)
    vol = var ** 0.5 * (52 ** 0.5)
    sharpe = ann / vol if vol > 0 else 0.0
    # 回撤（周收益序列）
    peak, mdd = 1.0, 0.0
    for r in rets:
        peak = max(peak, peak * (1 + r))
        mdd = max(mdd, (peak - peak * (1 + r)) / peak)
    return {
        "weeks": n,
        "nav": total,
        "annual_return": ann,
        "annual_vol": vol,
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_cost": cost_paid,
        "avg_turnover": turnover_sum / n,
        "episodes": episodes,
        "weekly_returns": rets,  # 触发周净收益序列（蒙特卡洛周级 bootstrap 单元）
    }


def monte_carlo(
    weekly_returns: list[float],
    episodes: list[dict],
    n_sims: int = 1000,
    seed: int = 42,
    mode: str = "episode",
) -> dict:
    """bootstrap 蒙特卡洛：从采样单元（周 或 触发段）有放回抽，拼接 109 触发周路径。

    - mode="week"：109 个触发周 iid 有放回（忽略段内序列相关，分布偏乐观）
    - mode="episode"：33 个触发段为块，整段有放回（保留段内相关，更真实）
    年化口径与真实路径一致（109 触发周分布在 11.5 年：ann = nav^(1/11.5)-1）。
    """
    rng = random.Random(seed)
    n_weeks = len(weekly_returns)
    if mode == "week":
        units = [[r] for r in weekly_returns]
    elif mode == "episode":
        units = [ep["returns"] for ep in episodes]
    else:
        raise ValueError(f"未知 mc 模式: {mode}（支持 week|episode）")

    sims = []
    for _ in range(n_sims):
        rets: list[float] = []
        while len(rets) < n_weeks:
            rets.extend(rng.choice(units))
        rets = rets[:n_weeks]
        nav = 1.0
        peak, mdd = 1.0, 0.0
        for r in rets:
            nav *= 1 + r
            peak = max(peak, nav)
            mdd = max(mdd, (peak - nav) / peak)
        # 双口径年化：触发期（109 周/52 ≈ 2.1 年，策略"用钱时"的资金效率）与
        # 全期（11.5 年，总资金回报——空仓 86% 时间的资金闲置成本）
        ann_active = nav ** (1 / (n_weeks / 52)) - 1
        ann_total = nav ** (1 / 11.5) - 1
        mean_r = sum(rets) / n_weeks
        var = sum((r - mean_r) ** 2 for r in rets) / max(n_weeks - 1, 1)
        vol = var ** 0.5 * (52 ** 0.5)
        sharpe = ann_active / vol if vol > 0 else 0.0
        sims.append({
            "nav": nav, "annual_return_active": ann_active,
            "annual_return_total": ann_total, "sharpe": sharpe, "max_drawdown": mdd,
        })

    def q(key: str, p: float) -> float:
        vals = sorted(s[key] for s in sims)
        return vals[min(int(p * n_sims), n_sims - 1)]

    dist = {
        k: [q(k, p) for p in (0.05, 0.25, 0.50, 0.75, 0.95)]
        for k in ("nav", "annual_return_active", "annual_return_total", "sharpe", "max_drawdown")
    }
    return {
        "mode": mode,
        "n_sims": n_sims,
        "seed": seed,
        "n_units": len(units),
        "dist": dist,
        "risk": {
            "p_active_negative": sum(1 for s in sims if s["annual_return_active"] <= 0) / n_sims,
            "p_active_below_10pct": sum(1 for s in sims if s["annual_return_active"] < 0.10) / n_sims,
            "p_total_below_10pct": sum(1 for s in sims if s["annual_return_total"] < 0.10) / n_sims,
            "p_mdd_above_30pct": sum(1 for s in sims if s["max_drawdown"] > 0.30) / n_sims,
            "p_sharpe_below_1": sum(1 for s in sims if s["sharpe"] < 1.0) / n_sims,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="crash_bottom_leader 策略回测")
    ap.add_argument("--panel", default="results/crash_bottom_leader_timed/panel.parquet")
    ap.add_argument("--db", default="data/factorlab.duckdb")
    ap.add_argument("--k", type=int, default=K_DEFAULT)
    ap.add_argument("--cost-bps", type=int, default=COST_BPS_DEFAULT)
    ap.add_argument("--no-limit-down", action="store_true", help="关闭跌停过滤")
    ap.add_argument("--intensity", action="store_true",
                    help="触发强度分级仓位：w = min(1, -mkt20/0.16)（-8% 半仓、-16% 满仓）")
    ap.add_argument("--skip-first-week", action="store_true", help="触发段首周空仓缓冲")
    ap.add_argument("--stop-loss", type=float, default=None,
                    help="段内组合回撤止损（如 0.15 = 从段内峰值回撤 15% 退出该段）")
    ap.add_argument("--mc", type=int, default=0, help="蒙特卡洛模拟次数（0=关闭）")
    ap.add_argument("--mc-mode", choices=["week", "episode"], default="episode",
                    help="bootstrap 采样单元：week=触发周 iid；episode=触发段 block（默认）")
    ap.add_argument("--mc-seed", type=int, default=42)
    ap.add_argument("--rebalance", type=int, default=1,
                    help="调仓间隔（周；1=每周调仓，2=持 2 周再调，吃更完整反弹）")
    ap.add_argument("--take-profit", type=float, default=None,
                    help="个股止盈（累计收益 ≥ 该比例卖出，如 0.15）——启用止盈止损持仓管理")
    ap.add_argument("--stock-stop-loss", type=float, default=None,
                    help="个股止损（累计收益 ≤ -该比例卖出，如 0.10）")
    ap.add_argument("--max-hold", type=int, default=None,
                    help="个股最长持有周数（到期强制卖出）")
    ap.add_argument("--k-buy", type=int, default=None,
                    help="买入门槛（<=k）：补仓只买信号排名前 k_buy 的强股，缺口空仓")
    args = ap.parse_args()

    panel = load_panel(Path(args.panel))
    limit_down = None
    if not args.no_limit_down:
        # 跌停过滤只需触发周买入日：全段 pct_chg 加载会 segfault，按触发日期 SQL 直查
        import duckdb
        trigger_dates = (
            panel.filter(pl.col("signal").is_not_null())
            .sort("date")["date"].unique().dt.strftime("%Y%m%d").to_list()
        )
        with duckdb.connect(str(Path(args.db)), read_only=True) as con:
            con.execute(f"SET memory_limit='2GB'")
            ld = con.execute(
                "SELECT substr(ts_code, 1, 6) AS code, trade_date AS date, pct_chg "
                "FROM daily WHERE trade_date IN (SELECT unnest(?))",
                [trigger_dates],
            ).pl()
        limit_down = ld.with_columns(
            pl.col("date").str.strptime(pl.Date, "%Y%m%d")
        ).select(["date", "code", "pct_chg"])
    mkt20 = None
    if args.intensity:
        mkt20 = load_mkt20(Path(args.db))
    result = strategy_backtest(
        panel, limit_down, k=args.k, cost_bps=args.cost_bps,
        mkt20=mkt20, intensity=args.intensity, skip_first_week=args.skip_first_week,
        stop_loss=args.stop_loss, rebalance_weeks=args.rebalance,
        take_profit=args.take_profit, stock_stop_loss=args.stock_stop_loss,
        max_hold=args.max_hold, k_buy=args.k_buy,
    )
    if args.mc:
        result["monte_carlo"] = monte_carlo(
            result["weekly_returns"], result["episodes"],
            n_sims=args.mc, seed=args.mc_seed, mode=args.mc_mode,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
