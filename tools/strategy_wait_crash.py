"""死等股灾战法（知乎方法论原样实现）。

规则（逐条对应原文）：
- 空仓等待：非触发期零仓位，拒绝一切其他行情
- 触发（恐慌确认，多条件 AND）：
  1. 大盘（000300 代理上证）20 日累计跌 >= 6%（月线跌 6 个点，跌半个月）；
  2. 当日仍在下跌（阴线，跌势延续）；
  3. 百股跌停（当日跌停家数 >= 100）；
  4. 大幅缩量（当日两市成交额 < 前 5 日均量 70%）。
  （情绪哀嚎/恐慌指数/4 月底 12 月中旬惯例——不可量化或日历提示，跳过）
- 标的：主线大跌资产——半导体行业股票等权组合（197 只）代理"半导体/芯片 ETF"；
  原文要求 ETF 月线跌 20-30%，触发时自然满足（月线 -6% 以上 + 板块同跌）
- 建仓：金字塔式分批，绝不梭哈——批 1 买 30%，标的每再跌 3 个点加一批（30%/40%）
- 卖出：见好就收——盈利确认后 1-2 个交易日走掉大部分（第 1 日卖 70%，第 2 日清仓）；
  10% 硬止损（标的累计亏损超 10% 全部卖出，绝不恋战）
- 成本：ETF 双边 10bps（免印花税，佣金万 2.5×2）
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import polars as pl

COST = 0.001  # 双边 10bps（ETF 免印花税）
BATCHES = (0.30, 0.30, 0.40)  # 金字塔：越跌买越多
GAP_DROP = 0.03  # 每次加仓至少再跌 3 个点
STOP_LOSS = 0.10  # 硬止损
TP_DAY1 = 0.70  # 盈利确认后第 1 日卖出比例
LIMIT_DOWN = -9.8  # 跌停判定（主板）
TRIGGER = {"idx_20d": -0.06, "limit_down_cnt": 100, "vol_ratio": 0.90}


def load_daily_table(db_path: Path) -> pl.DataFrame:
    """日频聚合表：跌停家数 / 两市成交额 / 半导体等权收益 / 000300 指数收益。"""
    with duckdb.connect(str(db_path), read_only=True) as con:
        con.execute("SET memory_limit='2GB'")
        df = con.execute("""
            WITH semi_stocks AS (SELECT symbol FROM stock_basic WHERE industry = '半导体'),
            agg AS (
                SELECT trade_date,
                    SUM(CASE WHEN pct_chg <= ? THEN 1 ELSE 0 END) AS limit_down_cnt,
                    SUM(vol) AS total_vol,
                    AVG(CASE WHEN substr(ts_code, 1, 6) IN (SELECT symbol FROM semi_stocks)
                             THEN pct_chg END) / 100.0 AS semi_ret
                FROM daily GROUP BY trade_date
            )
            SELECT a.trade_date, a.limit_down_cnt, a.total_vol, a.semi_ret,
                   i.pct_chg / 100.0 AS idx_ret
            FROM agg a
            LEFT JOIN index_daily i ON a.trade_date = i.trade_date AND i.ts_code = '000300.SH'
            ORDER BY a.trade_date
        """, [LIMIT_DOWN]).pl()
    return df.with_columns(
        pl.col("trade_date").str.strptime(pl.Date, "%Y%m%d").alias("date"),
    ).drop("trade_date")


def prepare(df: pl.DataFrame) -> pl.DataFrame:
    """衍生信号：20 日指数累计、缩量比、反弹迹象、触发标记。

    时序对齐原文：恐慌放量（跌停潮）→ 抛压衰竭缩量 → 小幅反弹后买入。
    触发 = 月线跌 6%+（恐慌确立）AND 近 5 日出现小幅反弹（靴子落地）
           AND 当日人气冷清（缩量 <= 0.9——2018 阴跌型缩量不到 0.8）；百股跌停为佐证。
    """
    df = df.sort("date").with_columns(
        pl.col("idx_ret").rolling_sum(20).alias("idx_20d"),
        (pl.col("total_vol") / pl.col("total_vol").rolling_mean(5)).alias("vol_ratio"),
        pl.col("idx_ret").rolling_max(5).alias("idx_5d_max"),
    )
    return df.with_columns(
        ((pl.col("idx_20d") <= TRIGGER["idx_20d"])
         & (pl.col("idx_5d_max") >= 0.015)  # 近 5 日出现 >=1.5% 的反弹（靴子落地）
         & (pl.col("vol_ratio") <= 0.90)     # 缩量：人气冷清
        ).alias("triggered"),
    )


def wait_crash_backtest(df: pl.DataFrame, cost: float = COST) -> dict:
    """日频交易循环：空仓等触发 → 金字塔分批 → 快速止盈 / 10% 止损。

    资金模型：现金 cash + 各批持仓（每批独立累计 cum_i，从各自买入日起）；
    净值 = cash + Σ(b_i × cum_i)。加仓金额为初始资金 1.0 的比例（0.30/0.30/0.40
    恰好耗尽现金）。止损/止盈基于加权累计（总成本口径）。
    """
    df = prepare(df)
    cash = 1.0
    lots: list[list[float]] = []  # 每批 [资金额, 累计]
    last_add = 1.0  # 上次加仓时的加权累计
    profit_day = 0
    in_market = False
    trades = 0
    episodes = []
    per_ep: dict = {}

    for r in df.sort("date").iter_rows(named=True):
        d, trig, semi = r["date"], r["triggered"], r["semi_ret"]
        if in_market:
            for lot in lots:
                lot[1] *= (1 + semi) if semi == semi else 1.0  # null 视为无变动
            invested = sum(l[0] for l in lots)
            value = sum(l[0] * l[1] for l in lots)
            wcum = value / invested if invested > 0 else 1.0
            # 10% 硬止损
            if wcum <= 1 - STOP_LOSS:
                cash += value  # 持仓回收回现金（原未投入现金保留）
                lots = []
                in_market = False
                trades += 1
                per_ep["end"] = str(d); per_ep["exit"] = "stop_loss"
                episodes.append(per_ep); per_ep = {}
                continue
            # 盈利确认后 1-2 日走掉大部分
            if value >= invested and profit_day == 0:
                profit_day = 1
            if profit_day:
                sell_ratio = TP_DAY1 if profit_day == 1 else 1.0
                cash += value * sell_ratio * (1 - cost)
                for lot in lots:
                    lot[0] *= 1 - sell_ratio
                trades += 1
                profit_day += 1
                if sum(l[0] for l in lots) <= 1e-9:
                    in_market = False
                    per_ep["end"] = str(d); per_ep["exit"] = "take_profit"
                    episodes.append(per_ep); per_ep = {}
                    continue
            # 金字塔加仓：加权累计再跌 3 个点且批数未满
            if len(lots) < len(BATCHES) and wcum <= last_add * (1 - GAP_DROP):
                slot = BATCHES[len(lots)]
                if cash >= slot * (1 + cost):
                    cash -= slot * (1 + cost)
                    lots.append([slot, 1.0])
                    last_add = wcum
        elif trig:
            in_market = True
            lots = [[BATCHES[0], 1.0]]
            cash -= BATCHES[0] * (1 + cost)
            last_add = 1.0
            profit_day = 0
            per_ep = {"start": str(d)}
        nav = cash + sum(l[0] * l[1] for l in lots)
    if in_market:
        per_ep["end"] = "open"; per_ep["exit"] = "open"
        episodes.append(per_ep)
    n = len(df)
    years = n / 244.0
    ann = nav ** (1 / years) - 1 if nav > 0 else -1.0
    return {
        "nav": nav, "annual_return": ann,
        "trades": trades, "episodes": episodes,
        "days": n,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="死等股灾战法回测")
    ap.add_argument("--db", default="data/factorlab.duckdb")
    ap.add_argument("--start", default="2015-01-01")
    args = ap.parse_args()
    df = load_daily_table(Path(args.db)).filter(pl.col("date") >= pl.lit(__import__("datetime").date.fromisoformat(args.start)))
    result = wait_crash_backtest(df)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
