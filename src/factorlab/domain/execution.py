"""M8-01：Execution Domain Contracts——PortfolioState / OrderBatch / enums。

架构边界：TargetPortfolio（ideal weights，M7）≠ PortfolioState（actual
cash/share inventory）。二者之间必须经过 Execution Runtime（M8-02..06）。

- PortfolioState：as_of_date + phase（PRE/POST_EXECUTION——同一天开盘前/后
  不是同一个 state）+ cash + sparse positions（quantity / sellable_quantity，
  Int64；T+1 transition 属后续 Execution state transition，本任务只定义关系）
- OrderBatch：一个 TargetPortfolio decision 在一个实际执行日期/时点的**净**
  订单集合（decision_date → execution_date > decision_date；ExecutionTiming
  复用 M6；orders 严格 code/side/quantity，每 code 至多 1 行）
- 不定义 Fill/Trade/PnL/NAV/MarketSnapshot（M8-04/05 之前锁定这些 contract
  过早）；不读取行情/DB；不实现任何执行算法
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass
from enum import Enum

import polars as pl

from factorlab.domain.codes import is_canonical_stock_code
from factorlab.domain.timing import ExecutionTiming


class OrderSide(Enum):
    """订单方向（M8 v1 long-only：仅 BUY/SELL，无 SHORT/COVER）。"""

    BUY = "buy"
    SELL = "sell"


class PortfolioStatePhase(Enum):
    """实际组合状态时点（同一天开盘交易前 vs 交易后不是同一 state）。"""

    PRE_EXECUTION = "pre_execution"
    POST_EXECUTION = "post_execution"


_POSITIONS_COLUMNS = ["code", "quantity", "sellable_quantity"]
_ORDERS_COLUMNS = ["code", "side", "quantity"]


def _require_date(value, field: str) -> datetime.date:
    if not isinstance(value, datetime.date) or isinstance(value, datetime.datetime):
        raise ValueError(
            f"{field} 必须为 datetime.date（datetime.datetime/str/int 均拒绝，"
            f"收到 {value!r}）")
    return value


def _check_positions_schema(frame: pl.DataFrame) -> None:
    if list(frame.columns) != _POSITIONS_COLUMNS:
        raise ValueError(
            f"positions 必须严格为 code/quantity/sellable_quantity 三列"
            f"（收到 {frame.columns}）——禁止 weight/price/market_value/cost 等")
    if frame.schema["code"] != pl.String:
        raise ValueError(f"positions.code dtype 必须为 String（收到 {frame.schema['code']}）")
    if frame.schema["quantity"] != pl.Int64:
        raise ValueError(f"positions.quantity dtype 必须为 Int64（收到 {frame.schema['quantity']}）")
    if frame.schema["sellable_quantity"] != pl.Int64:
        raise ValueError(
            f"positions.sellable_quantity dtype 必须为 Int64（收到 {frame.schema['sellable_quantity']}）")


def _check_positions_content(frame: pl.DataFrame) -> None:
    if not frame.height:
        return
    dup = frame.group_by("code").len().filter(pl.col("len") > 1)
    if dup.height:
        raise ValueError(f"positions code 重复 {dup.height} 组——不 dedup/合并")
    bad_code = frame.filter(~pl.col("code").map_elements(
        is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False))
    if bad_code.height:
        raise ValueError(
            f"positions 含非 canonical code: {bad_code['code'].unique().to_list()}")
    bad_q = frame.filter((pl.col("quantity") <= 0))
    if bad_q.height:
        raise ValueError(
            f"positions.quantity 必须 > 0（{bad_q['quantity'].unique().to_list()}）"
            f"——sparse holdings 不保存 0 行")
    bad_s = frame.filter((pl.col("sellable_quantity") < 0)
                         | (pl.col("sellable_quantity") > pl.col("quantity")))
    if bad_s.height:
        raise ValueError(
            f"sellable_quantity 必须 0 <= s <= quantity"
            f"（{bad_s['sellable_quantity'].unique().to_list()}）")
    if not frame.equals(frame.sort("code")):
        raise ValueError("positions 必须按 code 稳定排序——不自动排序"
                         "（artifact diff/hash/reproducibility）")


@dataclass(frozen=True)
class PortfolioState:
    """实际组合状态（actual holdings）：as_of_date + phase + cash + sparse 持股。

    - cash：可用于证券交易的账户现金（>=0 finite float；可提现/结算现金
      语义未区分）
    - positions：sparse holdings——code String / quantity Int64 >0 /
      sellable_quantity Int64 ∈ [0, quantity]；code unique + canonical +
      稳定排序；无日期列（共享 as_of_date/phase）；空 typed frame 合法
      （cash-only state）
    - 不保存 weights/price/market_value/cost_basis（估值属 M8-05）
    """

    as_of_date: datetime.date
    phase: PortfolioStatePhase
    cash: float
    positions: pl.DataFrame

    def __post_init__(self) -> None:
        _require_date(self.as_of_date, "as_of_date")
        if not isinstance(self.phase, PortfolioStatePhase):
            raise ValueError(
                f"phase 必须为 PortfolioStatePhase 实例（收到 {type(self.phase).__name__}）")
        c = self.cash
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            raise ValueError(f"cash 必须为数值（收到 {c!r}）")
        if not math.isfinite(c) or c < 0:
            raise ValueError(f"cash 必须 finite 且 >= 0（收到 {c!r}）")
        _check_positions_schema(self.positions)
        _check_positions_content(self.positions)


def _check_orders_schema(frame: pl.DataFrame) -> None:
    if list(frame.columns) != _ORDERS_COLUMNS:
        raise ValueError(
            f"orders 必须严格为 code/side/quantity 三列（收到 {frame.columns}）"
            f"——禁止 target_weight/signal/price/cost 等")
    if frame.schema["code"] != pl.String:
        raise ValueError(f"orders.code dtype 必须为 String（收到 {frame.schema['code']}）")
    if frame.schema["side"] != pl.String:
        raise ValueError(f"orders.side dtype 必须为 String（收到 {frame.schema['side']}）")
    if frame.schema["quantity"] != pl.Int64:
        raise ValueError(f"orders.quantity dtype 必须为 Int64（收到 {frame.schema['quantity']}）")


def _check_orders_content(frame: pl.DataFrame) -> None:
    if not frame.height:
        return
    dup = frame.group_by("code").len().filter(pl.col("len") > 1)
    if dup.height:
        raise ValueError(
            f"orders code 重复 {dup.height} 组——OrderBatch 是净订单，每 code "
            f"至多 1 行（buy/sell 同 code 必须先 net）")
    bad_code = frame.filter(~pl.col("code").map_elements(
        is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False))
    if bad_code.height:
        raise ValueError(
            f"orders 含非 canonical code: {bad_code['code'].unique().to_list()}")
    bad_side = frame.filter(pl.col("side").is_null()
                           | ~pl.col("side").is_in(["buy", "sell"]))
    if bad_side.height:
        raise ValueError(
            f"orders.side 仅允许 'buy'/'sell'（OrderSide.value；收到 "
            f"{bad_side['side'].unique().to_list()}——BUY/long/short/cover 拒绝）")
    bad_q = frame.filter(pl.col("quantity") <= 0)
    if bad_q.height:
        raise ValueError(
            f"orders.quantity 必须 > 0（{bad_q['quantity'].unique().to_list()}）")
    if not frame.equals(frame.sort("code")):
        raise ValueError("orders 必须按 code 稳定排序——不自动排序")


@dataclass(frozen=True)
class OrderBatch:
    """净订单集合（一个 TargetPortfolio decision 的 execution 意图）。

    - decision_date：策略决策日（未来对应 TargetPortfolio.decision_dates）
    - execution_date：calendar resolver 解析出的真实交易日期（> decision_date；
      本任务不负责计算）
    - execution_timing：复用 M6 ExecutionTiming（NEXT_OPEN/NEXT_CLOSE——
      不新建 OrderTiming/ExecutionPoint）
    - orders：严格 code String / side String("buy"/"sell") / quantity Int64>0；
      code unique（净订单）；稳定排序；空 typed batch 合法（目标==当前，
      execution event 存在但 0 orders）
    - 不携带 target_weight/signal/price/cost（share-space action）
    """

    decision_date: datetime.date
    execution_date: datetime.date
    execution_timing: ExecutionTiming
    orders: pl.DataFrame

    def __post_init__(self) -> None:
        _require_date(self.decision_date, "decision_date")
        _require_date(self.execution_date, "execution_date")
        if self.execution_date <= self.decision_date:
            raise ValueError(
                f"execution_date 必须 > decision_date（收到 decision="
                f"{self.decision_date} execution={self.execution_date}）")
        if not isinstance(self.execution_timing, ExecutionTiming):
            raise ValueError(
                f"execution_timing 必须为 ExecutionTiming 实例（收到 "
                f"{type(self.execution_timing).__name__}）")
        _check_orders_schema(self.orders)
        _check_orders_content(self.orders)


# ---------------------------------------------------------------------------
# M8-02：ExecutionSchedule（calendar resolver 输出）
# ---------------------------------------------------------------------------

_SCHEDULE_COLUMNS = ["decision_date", "execution_date", "execution_timing"]


@dataclass(frozen=True)
class ExecutionSchedule:
    """decision_date → execution_date 映射（每 portfolio decision 恰一个
    execution event）。

    - 严格三列：decision_date(Date) / execution_date(Date) /
      execution_timing(String = ExecutionTiming.value)
    - decision_date unique；execution_date > decision_date（严格）；
      decision ASC 且 execution 随 decision 序列严格递增（NEXT_OPEN/
      NEXT_CLOSE 均解析到下一交易日）；不自动 sort
    - 空 typed schedule 合法（schema 保持）
    """

    frame: pl.DataFrame

    def __post_init__(self) -> None:
        f = self.frame
        if list(f.columns) != _SCHEDULE_COLUMNS:
            raise ValueError(
                f"ExecutionSchedule.frame 必须严格为 decision_date/execution_date/"
                f"execution_timing 三列（收到 {f.columns}）")
        if f.schema["decision_date"] != pl.Date:
            raise ValueError(
                f"decision_date dtype 必须为 Date（收到 {f.schema['decision_date']}）")
        if f.schema["execution_date"] != pl.Date:
            raise ValueError(
                f"execution_date dtype 必须为 Date（收到 {f.schema['execution_date']}）")
        if f.schema["execution_timing"] != pl.String:
            raise ValueError(
                f"execution_timing dtype 必须为 String（收到 {f.schema['execution_timing']}）")
        if f.height:
            # M8-02A：三列均 non-null（不依赖 sorted() 偶然 TypeError）
            for col in ("decision_date", "execution_date", "execution_timing"):
                nulls = f.filter(pl.col(col).is_null())
                if nulls.height:
                    raise ValueError(
                        f"ExecutionSchedule.{col} 不允许 null"
                        f"（{nulls.height} 行——non-null contract）")
            dup = f.group_by("decision_date").len().filter(pl.col("len") > 1)
            if dup.height:
                raise ValueError(
                    f"decision_date 重复 {dup.height} 组——每 portfolio decision "
                    f"恰一个 execution event")
            bad = f.filter(pl.col("execution_date") <= pl.col("decision_date"))
            if bad.height:
                raise ValueError(
                    f"execution_date 必须 > decision_date（{bad.height} 行违规）")
            for v in f["execution_timing"].unique().to_list():
                try:
                    ExecutionTiming(v)
                except ValueError as exc:
                    raise ValueError(
                        f"execution_timing 必须为 ExecutionTiming.value"
                        f"（收到 {v!r}——open/close/NEXT_OPEN/tomorrow 拒绝）") from exc
            # M8-02A：严格递增（相邻 <），不依赖 sorted(list) 表达 strict
            dec = f["decision_date"].to_list()
            ex = f["execution_date"].to_list()
            if any(a >= b for a, b in zip(dec, dec[1:])):
                raise ValueError(
                    "decision_date 必须严格递增（相邻 <）——不自动排序")
            if any(a >= b for a, b in zip(ex, ex[1:])):
                raise ValueError(
                    "execution_date 必须严格递增（相邻 <）——不自动排序")


# ---------------------------------------------------------------------------
# M8-02：MarketOpenSnapshot（execution_date 的市场开盘证据）
# ---------------------------------------------------------------------------

_SNAPSHOT_COLUMNS = ["code", "open", "pre_close", "up_limit", "down_limit",
                     "has_daily", "has_limit", "has_suspend_record"]


@dataclass(frozen=True)
class MarketOpenSnapshot:
    """execution_date 的市场开盘证据（不是 tradability/fill 判定）。

    - 严格 8 列：code(String) / open(Float64) / pre_close(Float64) /
      up_limit(Float64) / down_limit(Float64) / has_daily(Boolean) /
      has_limit(Boolean) / has_suspend_record(Boolean)
    - code canonical + unique + 稳定排序；无 date 列（共享 execution_date）
    - has_daily=True → open/pre_close non-null finite >0；False → null
    - has_limit=True → up/down non-null finite >0 且 down <= up；False → null
    - has_suspend_record = suspend_d 存在性证据（raw evidence flag——
      **不是** is_suspended_at_open / is_tradable；M8-04 定义 fill 语义）
    - 价格是 raw daily.open（禁止 qfq/hfq 复权价作成交价）
    """

    execution_date: datetime.date
    frame: pl.DataFrame

    def __post_init__(self) -> None:
        if not isinstance(self.execution_date, datetime.date) \
                or isinstance(self.execution_date, datetime.datetime):
            raise ValueError(
                f"execution_date 必须为 datetime.date（收到 {self.execution_date!r}）")
        f = self.frame
        if list(f.columns) != _SNAPSHOT_COLUMNS:
            raise ValueError(
                f"MarketOpenSnapshot.frame 必须严格为 8 列（收到 {f.columns}）"
                f"——禁止 is_tradable/can_buy 等推断字段")
        expected = {"code": pl.String, "open": pl.Float64, "pre_close": pl.Float64,
                    "up_limit": pl.Float64, "down_limit": pl.Float64,
                    "has_daily": pl.Boolean, "has_limit": pl.Boolean,
                    "has_suspend_record": pl.Boolean}
        for col, dtype in expected.items():
            if f.schema[col] != dtype:
                raise ValueError(
                    f"snapshot.{col} dtype 必须为 {dtype}（收到 {f.schema[col]}）")
        if f.height:
            dup = f.group_by("code").len().filter(pl.col("len") > 1)
            if dup.height:
                raise ValueError(f"snapshot code 重复 {dup.height} 组")
            bad_code = f.filter(~pl.col("code").map_elements(
                is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False))
            if bad_code.height:
                raise ValueError(
                    f"snapshot 含非 canonical code: {bad_code['code'].unique().to_list()}")
            if not f.equals(f.sort("code")):
                raise ValueError("snapshot 必须按 code 稳定排序——不自动排序")
            # M8-02A：三个 evidence flags 必须 non-null Boolean（无第三
            # "unknown" 状态——数据覆盖 uncertainty 由 global coverage gates
            # 单独表达；null 穿透 Polars 三值逻辑会绕过 conditional invariants）
            for flag in ("has_daily", "has_limit", "has_suspend_record"):
                nulls = f.filter(pl.col(flag).is_null())
                if nulls.height:
                    raise ValueError(
                        f"snapshot.{flag} 不允许 null（{nulls.height} 行）"
                        f"——evidence 必须非空 Boolean（True=有证据/False=无证据）")
            bad_daily = f.filter(pl.col("has_daily")
                                 & (~pl.col("open").is_finite()
                                    | (pl.col("open") <= 0)
                                    | pl.col("open").is_null()
                                    | ~pl.col("pre_close").is_finite()
                                    | (pl.col("pre_close") <= 0)
                                    | pl.col("pre_close").is_null()))
            if bad_daily.height:
                raise ValueError(
                    f"has_daily=True 要求 open/pre_close non-null finite >0"
                    f"（{bad_daily['code'].to_list()}）")
            bad_no_daily = f.filter(~pl.col("has_daily")
                                    & (pl.col("open").is_not_null()
                                       | pl.col("pre_close").is_not_null()))
            if bad_no_daily.height:
                raise ValueError(
                    f"has_daily=False 要求 open/pre_close 为 null"
                    f"（{bad_no_daily['code'].to_list()}）")
            bad_limit = f.filter(pl.col("has_limit")
                                 & (pl.col("up_limit").is_null()
                                    | ~pl.col("up_limit").is_finite()
                                    | (pl.col("up_limit") <= 0)
                                    | pl.col("down_limit").is_null()
                                    | ~pl.col("down_limit").is_finite()
                                    | (pl.col("down_limit") <= 0)
                                    | (pl.col("down_limit") > pl.col("up_limit"))))
            if bad_limit.height:
                raise ValueError(
                    f"has_limit=True 要求 up/down non-null finite >0 且 down<=up"
                    f"（{bad_limit['code'].to_list()}）")
            bad_no_limit = f.filter(~pl.col("has_limit")
                                    & (pl.col("up_limit").is_not_null()
                                       | pl.col("down_limit").is_not_null()))
            if bad_no_limit.height:
                raise ValueError(
                    f"has_limit=False 要求 up/down_limit 为 null"
                    f"（{bad_no_limit['code'].to_list()}）")
