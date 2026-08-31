"""M7-01：TargetPortfolio 领域契约（Portfolio Construction 输出）。

TargetPortfolio = **理想目标权重**（Strategy Decision Artifact）：
- decision_date=t：使用 t 日可得 SignalArtifact、在该 signal available 时点
  形成的理想目标组合——**不代表 t close 成交**（默认 EOD 信号最早 t+1 open
  执行；execution_date 解析属 M8）。
- 不是 actual holdings：T+1/停牌/涨跌停/整手/费用/滑点/部分成交等全部属
  M8 Execution Runtime。
- 现金是**隐式 residual**（cash = 1 - securities weight sum），不创建
  CASH pseudo-security。

Strategy Runtime 只消费 SignalArtifact——本模块不依赖 LabelArtifact /
forward_return_* / legacy panel。
"""

from __future__ import annotations

import datetime
import math
import re
from dataclasses import dataclass, field

import polars as pl

from factorlab.domain.codes import is_canonical_stock_code
from factorlab.domain.timing import SignalTiming

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_GROSS_TOL = 1e-12


def _validate_meta_name(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise ValueError(
            f"{field_name} 必须匹配 ^[A-Za-z_][A-Za-z0-9_]{{0,63}}$（收到 {value!r}）")
    return value


@dataclass(frozen=True)
class TargetPortfolioMeta:
    """目标组合元数据：来源策略/信号/时间语义/暴露。

    source_timing 直接复用 M6 SignalTiming（信息截止 → 可得 → 最早执行），
    不新建 Strategy/Portfolio/DecisionTiming。
    """

    strategy_name: str
    source_signal_name: str
    source_timing: SignalTiming
    gross_exposure: float
    frequency: str = "1d"

    def __post_init__(self) -> None:
        _validate_meta_name(self.strategy_name, "strategy_name")
        _validate_meta_name(self.source_signal_name, "source_signal_name")
        if not isinstance(self.source_timing, SignalTiming):
            raise ValueError(
                f"source_timing 必须为 SignalTiming 实例（收到 {type(self.source_timing).__name__}）")
        if self.frequency != "1d":
            raise ValueError(f"frequency 当前仅支持 '1d'（收到 {self.frequency!r}）")
        g = self.gross_exposure
        if isinstance(g, bool) or not isinstance(g, (int, float)):
            raise ValueError(f"gross_exposure 必须为数值（收到 {g!r}）")
        if not math.isfinite(g) or not 0 < g <= 1:
            raise ValueError(f"gross_exposure 必须 finite 且 0 < x <= 1（收到 {g!r}）")


@dataclass(frozen=True)
class TargetPortfolio:
    """目标组合（Strategy Decision Artifact）。

    - frame：严格 3 列（decision_date pl.Date / code pl.String /
      target_weight pl.Float64），(decision_date, code) 唯一，按
      (decision_date, code) 稳定排序（validator 要求已排序，不自动重排）
    - decision_dates：严格递增唯一日期元组——**与 sparse frame 分离**
      （某日 0 rows = 显式 all-cash target，≠ 无决策）
    - meta：来源元数据（gross_exposure invariant：有仓位日 sum(weight)
      ≈ meta.gross_exposure（1e-12）；all-cash 日豁免）
    """

    frame: pl.DataFrame
    decision_dates: tuple[datetime.date, ...]
    meta: TargetPortfolioMeta

    def __post_init__(self) -> None:
        self._validate_frame()
        self._validate_dates()
        self._validate_invariant()

    # ---- frame schema / dtype ----
    def _validate_frame(self) -> None:
        f = self.frame
        expected = {"decision_date": pl.Date, "code": pl.String,
                    "target_weight": pl.Float64}
        if list(f.columns) != ["decision_date", "code", "target_weight"]:
            raise ValueError(
                f"TargetPortfolio.frame 必须严格为 decision_date/code/target_weight"
                f" 三列（收到 {f.columns}）——禁止 signal/forward/label 等附加列")
        for col, dtype in expected.items():
            if f.schema[col] != dtype:
                raise ValueError(
                    f"frame.{col} dtype 必须为 {dtype}（收到 {f.schema[col]}）")
        if f.height:
            # (decision_date, code) 唯一（fail fast，不 dedup）
            dup = f.group_by(["decision_date", "code"]).len().filter(pl.col("len") > 1)
            if dup.height:
                raise ValueError(f"(decision_date, code) 重复 {dup.height} 组——不静默去重")
            # canonical stock code（复用 domain.codes 单一权威）
            bad_code = f.filter(~pl.col("code").map_elements(
                is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False))
            if bad_code.height:
                raise ValueError(
                    f"code 必须为 canonical stock code（收到 {bad_code['code'].unique().to_list()}）"
                    f"——CASH/alias/纯数字均拒绝")
            # target_weight：finite、>0、<=1（zero position 不创建 row）
            bad_w = f.filter(~pl.col("target_weight").is_finite()
                             | (pl.col("target_weight") <= 0)
                             | (pl.col("target_weight") > 1))
            if bad_w.height:
                raise ValueError(
                    f"target_weight 必须 finite 且 0 < w <= 1（收到 {bad_w['target_weight'].unique().to_list()}）"
                    f"——zero position 不应创建 row")
            # 稳定排序 invariant（要求已排序，不自动重排——artifact 确定性）
            if not f.equals(f.sort(["decision_date", "code"])):
                raise ValueError(
                    "frame 必须按 (decision_date, code) 稳定排序——不自动重排"
                    "（artifact diff/hash/reproducibility 依赖稳定顺序）")

    # ---- decision_dates ----
    def _validate_dates(self) -> None:
        dates = self.decision_dates
        if not isinstance(dates, tuple):
            raise ValueError(f"decision_dates 必须为 tuple（收到 {type(dates).__name__}）")
        for i, d in enumerate(dates):
            if not isinstance(d, datetime.date) or isinstance(d, datetime.datetime):
                raise ValueError(
                    f"decision_dates 元素必须为 datetime.date（收到 {d!r}）")
            if i and d <= dates[i - 1]:
                raise ValueError(
                    f"decision_dates 必须严格递增唯一（{dates[i - 1]} -> {d}）"
                    f"——不自动 sort/dedup")
        # frame date ⊆ decision_dates
        if self.frame.height:
            known = set(dates)
            bad = self.frame.filter(
                ~pl.col("decision_date").map_elements(
                    lambda d: d in known, return_dtype=pl.Boolean))
            if bad.height:
                raise ValueError(
                    f"frame.decision_date 不在 decision_dates 中: "
                    f"{bad['decision_date'].unique().to_list()}")

    # ---- gross exposure invariant ----
    def _validate_invariant(self) -> None:
        if not self.frame.height:
            return
        sums = (self.frame.group_by("decision_date")
                .agg(pl.col("target_weight").sum().alias("_sum"))
                .filter((pl.col("_sum") - pl.lit(self.meta.gross_exposure)).abs() > _GROSS_TOL))
        if sums.height:
            raise ValueError(
                f"gross exposure invariant 失败：{sums['decision_date'].to_list()} 日"
                f" sum(weight)={sums['_sum'].to_list()} != gross_exposure="
                f"{self.meta.gross_exposure}（validator 只检查不 renormalize；"
                f"all-cash 日 0 rows 为显式例外）")
