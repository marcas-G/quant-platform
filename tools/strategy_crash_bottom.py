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
    holdings: set[str] = set()
    nav, cost_paid, turnover_sum = 1.0, 0.0, 0.0
    weeks, rets, turnovers, entry_weeks = [], [], [], []
    prev_week_end: pl.Date | None = None
    per_episode: dict = {}
    episodes: list[dict] = []
    seg_first = True  # 触发段首周标记（skip_first_week 用）

    for (week_end,), grp in active.sort("date").group_by("date", maintain_order=True):
        if prev_week_end is not None and week_end - prev_week_end > __import__("datetime").timedelta(days=10):
            # 触发断档：上一段结束
            episodes.append({**per_episode, "end": str(prev_week_end)})
            per_episode = {}
            seg_first = True
        # 仓位权重：强度分级（-mkt20/0.16，-8% 半仓、-16% 满仓）与段首缓冲
        w = 1.0
        if skip_first_week and seg_first:
            w = 0.0
        elif intensity:
            m = float(grp["mkt20"].first()) if grp["mkt20"].first() is not None else 0.0
            w = min(1.0, -m / 0.16)
        seg_first = False
        grp = grp.sort("signal", descending=True).head(k)
        codes = set(grp["code"].to_list())
        new_codes = codes - holdings
        turnover = len(new_codes) / k
        cost = turnover * cost_bps / 10000
        fwd = grp["forward_return_5d"].mean()  # 分块块边界 forward null → mean 可为 None
        ret = float(fwd) if fwd is not None else 0.0
        # 净值变化率 = 1 + w×收益 - w×换手×成本率（仓位缩放同时缩放收益与成交额）
        r_net = w * ret - w * turnover * cost_bps / 10000
        per_episode.setdefault("start", str(week_end))
        per_episode["weeks"] = per_episode.get("weeks", 0) + 1
        per_episode["cum_ret"] = per_episode.get("cum_ret", 1.0) * (1 + r_net)
        nav *= 1 + r_net
        cost_paid += w * cost
        turnover_sum += turnover
        holdings = codes
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
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
