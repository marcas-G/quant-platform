"""M8-05B：execution accounting + point-in-time valuation domain contracts。

- ExecutionAccountingSummary：单 execution event 的 realized accounting
  （只聚合 FillBatch——cash/fee 唯一 authority；不含 position valuation）
- PortfolioMarkSnapshot：显式 per-share valuation mark authority
  （caller 提供；与 PortfolioState.quantity 同一 share-unit basis；
  不说明价格来源——M8-05B 只做 valuation arithmetic，不做 price sourcing）
- PortfolioValuation：point-in-time account equity（NAV = cash + Σ
  quantity×mark——货币金额，不是 normalized index；不做 PnL/cost basis）

依赖边界：stdlib + polars + domain.codes + domain.execution（PortfolioStatePhase）
——不 import execution.* / duckdb / strategy / engine。
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass

import polars as pl

from factorlab.domain.codes import is_canonical_stock_code
from factorlab.domain.execution import PortfolioStatePhase


def _require_date(value, field: str) -> datetime.date:
    if not isinstance(value, datetime.date) or isinstance(value, datetime.datetime):
        raise ValueError(
            f"{field} 必须为 datetime.date（datetime.datetime/str 拒绝，"
            f"收到 {value!r}）")
    return value


# ---------------------------------------------------------------------------
# ExecutionAccountingSummary
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionAccountingSummary:
    """单 execution event 的 realized accounting summary（纯聚合，不重算）。

    - cash_before = PRE state.cash；cash_after = POST state.cash；
      net_cash_delta = Σ FillBatch.effective_cash_delta（唯一 authority）
    - buy/sell gross 与四项费用全部直接聚合 FillBatch 列
      （total_fees 按固定顺序 = commission + stamp_tax + transfer_fee——
      与 FillBatch 每行 total 同表达式结构；禁止按 rates 反算）
    - 不携带 strategy/signal/weight 字段；不含 market_value/NAV/PnL
      （属 PortfolioValuation）
    """

    execution_date: datetime.date
    cash_before: float
    buy_gross_notional: float
    sell_gross_notional: float
    commission: float
    stamp_tax: float
    transfer_fee: float
    total_fees: float
    net_cash_delta: float
    cash_after: float

    def __post_init__(self) -> None:
        _require_date(self.execution_date, "execution_date")
        for name, v in (("cash_before", self.cash_before),
                        ("cash_after", self.cash_after)):
            if not math.isfinite(v) or v < 0:
                raise ValueError(f"{name} 必须 finite >= 0（收到 {v!r}）")
        for name, v in (("buy_gross_notional", self.buy_gross_notional),
                        ("sell_gross_notional", self.sell_gross_notional),
                        ("commission", self.commission),
                        ("stamp_tax", self.stamp_tax),
                        ("transfer_fee", self.transfer_fee),
                        ("total_fees", self.total_fees)):
            if not math.isfinite(v) or v < 0:
                raise ValueError(f"{name} 必须 finite >= 0（收到 {v!r}）")
        if not math.isfinite(self.net_cash_delta):
            raise ValueError("net_cash_delta 必须 finite")
        if self.total_fees != self.commission + self.stamp_tax \
                + self.transfer_fee:
            raise ValueError(
                f"total_fees {self.total_fees} != commission + stamp_tax + "
                f"transfer_fee（{self.commission + self.stamp_tax + self.transfer_fee}）"
                f"——固定 aggregation order 不变量")


# ---------------------------------------------------------------------------
# PortfolioMarkSnapshot
# ---------------------------------------------------------------------------

_MARK_COLUMNS = ["code", "mark_price"]


@dataclass(frozen=True)
class PortfolioMarkSnapshot:
    """显式 per-share valuation mark authority（point-in-time）。

    - 严格两列：code(String) / mark_price(Float64)
    - code canonical + unique + 稳定排序；mark finite > 0（null/NaN/Inf/
      zero/negative 拒绝）；typed empty 合法
    - 不携带 daily/open/close/qfq/hfq/adj_factor/provider——mark_price 由
      caller 提供，假设与 PortfolioState.quantity 同一 share-unit basis
      （M8-05B kernel 不负责 price sourcing / corporate-action 修正）
    """

    as_of_date: datetime.date
    frame: pl.DataFrame

    def __post_init__(self) -> None:
        _require_date(self.as_of_date, "as_of_date")
        f = self.frame
        if list(f.columns) != _MARK_COLUMNS:
            raise ValueError(
                f"PortfolioMarkSnapshot.frame 必须严格为 code/mark_price 两列"
                f"（收到 {f.columns}）")
        if f.schema["code"] != pl.String:
            raise ValueError(f"marks.code dtype 必须为 String")
        if f.schema["mark_price"] != pl.Float64:
            raise ValueError(f"marks.mark_price dtype 必须为 Float64")
        if f.height:
            dup = f.group_by("code").len().filter(pl.col("len") > 1)
            if dup.height:
                raise ValueError(f"marks code 重复 {dup.height} 组")
            bad_code = f.filter(~pl.col("code").map_elements(
                is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False))
            if bad_code.height:
                raise ValueError(
                    f"marks 含非 canonical code: {bad_code['code'].unique().to_list()}")
            bad_p = f.filter(~pl.col("mark_price").is_finite()
                             | (pl.col("mark_price") <= 0)
                             | pl.col("mark_price").is_null())
            if bad_p.height:
                raise ValueError(
                    f"marks.mark_price 必须 finite > 0"
                    f"（{bad_p['code'].to_list()}——null/NaN/Inf/zero/negative 拒绝）")
            if not f.equals(f.sort("code")):
                raise ValueError("marks 必须按 code 稳定排序——不自动排序")


# ---------------------------------------------------------------------------
# PortfolioValuation
# ---------------------------------------------------------------------------

_VALUATION_COLUMNS = ["code", "quantity", "mark_price", "market_value"]


@dataclass(frozen=True)
class PortfolioValuation:
    """point-in-time account equity（explicit marks）。

    - NAV = cash + market_value（**货币金额**，如 1,112,200 RMB-like units；
      **不是** normalized cumulative NAV index——normalized/unit_nav/returns
      属 M8-06）
    - frame 严格四列：code(String)/quantity(Int64>0)/mark_price(Float64>0)/
      market_value(Float64>0)——position MV == quantity×mark（exact）；
      total MV == frame sum；NAV == cash + total MV（全部 exact 校验，
      不做 tolerance repair）
    - 资产所有权基于 quantity（sellable_quantity 不参与估值）
    - 无 realized/unrealized PnL / cost basis（PortfolioState 无 cost
      basis/lot ledger）
    """

    as_of_date: datetime.date
    phase: PortfolioStatePhase
    cash: float
    market_value: float
    nav: float
    frame: pl.DataFrame

    def __post_init__(self) -> None:
        _require_date(self.as_of_date, "as_of_date")
        if not isinstance(self.phase, PortfolioStatePhase):
            raise ValueError(
                f"phase 必须为 PortfolioStatePhase 实例（收到 "
                f"{type(self.phase).__name__}）")
        if not math.isfinite(self.cash) or self.cash < 0:
            raise ValueError(f"cash 必须 finite >= 0（收到 {self.cash!r}）")
        f = self.frame
        if list(f.columns) != _VALUATION_COLUMNS:
            raise ValueError(
                f"PortfolioValuation.frame 必须严格为 code/quantity/mark_price/"
                f"market_value 四列（收到 {f.columns}）"
                f"——禁止 sellable_quantity/avg_cost/cost_basis 等")
        expected = {"code": pl.String, "quantity": pl.Int64,
                    "mark_price": pl.Float64, "market_value": pl.Float64}
        for col, dtype in expected.items():
            if f.schema[col] != dtype:
                raise ValueError(
                    f"valuation.{col} dtype 必须为 {dtype}（收到 {f.schema[col]}）")
        if f.height:
            dup = f.group_by("code").len().filter(pl.col("len") > 1)
            if dup.height:
                raise ValueError(f"valuation code 重复 {dup.height} 组")
            bad_code = f.filter(~pl.col("code").map_elements(
                is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False))
            if bad_code.height:
                raise ValueError(
                    f"valuation 含非 canonical code: {bad_code['code'].unique().to_list()}")
            bad_q = f.filter(pl.col("quantity") <= 0)
            if bad_q.height:
                raise ValueError(
                    f"valuation.quantity 必须 Int64 > 0"
                    f"（{bad_q['quantity'].unique().to_list()}）")
            bad_m = f.filter(~pl.col("mark_price").is_finite()
                             | (pl.col("mark_price") <= 0)
                             | pl.col("mark_price").is_null())
            if bad_m.height:
                raise ValueError(
                    f"valuation.mark_price 必须 finite > 0"
                    f"（{bad_m['code'].to_list()}）")
            bad_mv = f.filter(~pl.col("market_value").is_finite()
                              | (pl.col("market_value") <= 0))
            if bad_mv.height:
                raise ValueError(
                    f"valuation.market_value 必须 finite > 0"
                    f"（{bad_mv['code'].to_list()}）")
            bad_pp = f.filter(pl.col("market_value")
                              != pl.col("quantity") * pl.col("mark_price"))
            if bad_pp.height:
                raise ValueError(
                    f"position market_value 必须 == quantity × mark_price"
                    f"（{bad_pp['code'].to_list()}——exact，不 tolerance repair）")
            if not f.equals(f.sort("code")):
                raise ValueError("valuation 必须按 code 稳定排序——不自动排序")
        if not math.isfinite(self.market_value) or self.market_value < 0:
            raise ValueError(
                f"market_value 必须 finite >= 0（收到 {self.market_value!r}）")
        frame_mv = f["market_value"].sum() if f.height else 0.0
        if self.market_value != frame_mv:
            raise ValueError(
                f"market_value {self.market_value} != frame 总和 {frame_mv}"
                f"（exact）")
        if not math.isfinite(self.nav) or self.nav < 0:
            raise ValueError(f"nav 必须 finite >= 0（收到 {self.nav!r}）")
        if self.nav != self.cash + self.market_value:
            raise ValueError(
                f"nav {self.nav} != cash + market_value "
                f"（{self.cash + self.market_value}——exact）")
