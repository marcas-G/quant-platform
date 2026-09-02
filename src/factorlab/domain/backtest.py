"""M8-06B：backtest runtime domain contracts——NavSeries / ExecutionArtifact /
BacktestResult。

- ExecutionArtifact：一天的事实记录快照（字段全部来自已关闭 primitive 的
  输出——零新计算；cash bridge invariant 校验）
- NavSeries：execution-event NAV 序列（memory-only；日期严格递增；
  per-row nav == cash + market_value exact）
- BacktestResult：frozen runtime object（无 writer/persistence）
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass

import polars as pl

from factorlab.domain.accounting import (ExecutionAccountingSummary,
                                         PortfolioValuation)
from factorlab.domain.execution import (FillBatch, OpenFillAssessment,
                                        OrderBatch, PortfolioState,
                                        PortfolioStatePhase)


def _require_date(value, field: str) -> datetime.date:
    if not isinstance(value, datetime.date) or isinstance(value, datetime.datetime):
        raise ValueError(
            f"{field} 必须为 datetime.date（收到 {value!r}）")
    return value


_NAV_COLUMNS = ["execution_date", "cash", "market_value", "nav"]


@dataclass(frozen=True)
class NavSeries:
    """execution-event NAV 序列（memory-only contract）。

    - 严格四列：execution_date(Date)/cash(Float64)/market_value(Float64)/
      nav(Float64)
    - execution_date 严格递增唯一（每 execution event 恰一条）
    - per-row nav == cash + market_value（exact）；全部 finite >= 0
    - NAV 是货币金额（explicit open marks basis）——不是 normalized index
    """

    frame: pl.DataFrame

    def __post_init__(self) -> None:
        f = self.frame
        if list(f.columns) != _NAV_COLUMNS:
            raise ValueError(
                f"NavSeries.frame 必须严格为 execution_date/cash/market_value/"
                f"nav 四列（收到 {f.columns}）")
        expected = {"execution_date": pl.Date, "cash": pl.Float64,
                    "market_value": pl.Float64, "nav": pl.Float64}
        for col, dtype in expected.items():
            if f.schema[col] != dtype:
                raise ValueError(
                    f"NavSeries.{col} dtype 必须为 {dtype}（收到 {f.schema[col]}）")
        if f.height:
            for col in _NAV_COLUMNS:
                if f[col].null_count():
                    raise ValueError(f"NavSeries.{col} 不允许 null")
            dates = f["execution_date"].to_list()
            if any(a >= b for a, b in zip(dates, dates[1:])):
                raise ValueError("NavSeries.execution_date 必须严格递增")
            bad = f.filter((pl.col("nav")
                            != pl.col("cash") + pl.col("market_value"))
                           | ~pl.col("cash").is_finite()
                           | ~pl.col("market_value").is_finite()
                           | ~pl.col("nav").is_finite()
                           | (pl.col("cash") < 0)
                           | (pl.col("market_value") < 0)
                           | (pl.col("nav") < 0))
            if bad.height:
                raise ValueError(
                    f"NavSeries 行违反 nav == cash + market_value / finite"
                    f" >= 0（{bad['execution_date'].to_list()}）")


@dataclass(frozen=True)
class ExecutionArtifact:
    """单 execution event 的事实记录（primitive 输出快照）。

    - 字段直接引用已关闭 primitive 输出（不重算/不复制计算）
    - cash bridge invariant：post.cash == pre.cash + Σ fills delta
      == accounting.cash_after
    - nav = POST state 在该 execution date 的 open-based marks 估值
    - disposition_counts：(fillable, blocked_suspension, blocked_limit_up,
      blocked_limit_down)——派生计数（只读诊断）
    """

    decision_date: datetime.date
    execution_date: datetime.date
    pre_state: PortfolioState
    orders: OrderBatch
    assessment: OpenFillAssessment
    fills: FillBatch
    post_state: PortfolioState
    accounting: ExecutionAccountingSummary
    nav: PortfolioValuation
    disposition_counts: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        _require_date(self.decision_date, "decision_date")
        _require_date(self.execution_date, "execution_date")
        if self.execution_date <= self.decision_date:
            raise ValueError("execution_date 必须 > decision_date")
        if (self.pre_state.as_of_date != self.execution_date
                or self.post_state.as_of_date != self.execution_date
                or self.fills.execution_date != self.execution_date):
            raise ValueError("artifact 各状态日期必须 == execution_date")
        if self.pre_state.phase is not PortfolioStatePhase.PRE_EXECUTION \
                or self.post_state.phase is not PortfolioStatePhase.POST_EXECUTION:
            raise ValueError("pre/post phase 必须 PRE/POST_EXECUTION")
        if self.orders.decision_date != self.decision_date:
            raise ValueError("orders.decision_date 不匹配")
        if (self.assessment.decision_date != self.decision_date
                or self.assessment.execution_date != self.execution_date):
            raise ValueError("assessment metadata 不匹配")
        if self.accounting.cash_before != self.pre_state.cash:
            raise ValueError("accounting.cash_before != pre_state.cash")
        if self.accounting.cash_after != self.post_state.cash:
            raise ValueError("accounting.cash_after != post_state.cash")
        delta = (self.fills.frame["effective_cash_delta"].sum()
                 if self.fills.frame.height else 0.0)
        if self.post_state.cash != self.pre_state.cash + delta:
            raise ValueError(
                "artifact cash bridge 破坏：post.cash != pre.cash + Σ delta")
        if len(self.disposition_counts) != 4 \
                or any(not isinstance(n, int) or n < 0
                       for n in self.disposition_counts):
            raise ValueError("disposition_counts 必须为 4 个非负 int")
        # nav 应为 POST 估值（日期/phase/cash 一致性）
        if self.nav.as_of_date != self.execution_date \
                or self.nav.phase is not PortfolioStatePhase.POST_EXECUTION \
                or self.nav.cash != self.post_state.cash:
            raise ValueError("artifact.nav 必须为 POST state 的当日估值")


@dataclass(frozen=True)
class BacktestResult:
    """run_backtest 的 memory-only runtime object（无 writer）。

    - artifacts：decision 有序的 ExecutionArtifact tuple
    - nav_series：与 artifacts 一一对应的 NAV 序列
    - final_state：最后 execution event 的 advance_to_next_trading_day 输出
      （PRE @ next open——可能超出 data cutoff，仅 calendar truth）
    """

    artifacts: tuple
    nav_series: NavSeries
    final_state: PortfolioState

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts, tuple):
            raise ValueError("artifacts 必须为 tuple")
        if self.final_state.phase is not PortfolioStatePhase.PRE_EXECUTION:
            raise ValueError("final_state 必须为 PRE_EXECUTION")
        if len(self.artifacts) != self.nav_series.frame.height:
            raise ValueError(
                f"artifacts({len(self.artifacts)}) 与 nav_series rows"
                f"({self.nav_series.frame.height}) 不一致")
        nav_dates = list(self.nav_series.frame["execution_date"].to_list())
        for i, a in enumerate(self.artifacts):
            if not isinstance(a, ExecutionArtifact):
                raise ValueError(f"artifacts[{i}] 必须为 ExecutionArtifact")
            if a.execution_date != nav_dates[i]:
                raise ValueError("nav_series 日期必须与 artifacts 一一对应")
