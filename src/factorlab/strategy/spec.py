"""M7-01：StrategySpec——策略领域契约（Portfolio Construction 输入）。

与 FactorSpec（因子研究）严格分离：StrategySpec 只描述"如何把已有
SignalArtifact 转化为目标组合"，**不包含 formula/process/target/forward 目标**。
Strategy Runtime 只消费 SignalArtifact（LabelArtifact/forward_return_*/legacy
panel 永不进入策略链）。
"""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, field_validator

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _validate_name(value: str, field: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise ValueError(
            f"{field} 必须匹配 ^[A-Za-z_][A-Za-z0-9_]{{0,63}}$（收到 {value!r}）")
    return value


def _validate_gross_exposure(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("gross_exposure 不能是 bool")
    if not isinstance(value, (int, float)):
        raise ValueError(f"gross_exposure 必须为数值（收到 {value!r}）")
    if not math.isfinite(value):
        raise ValueError("gross_exposure 必须 finite")
    if not 0 < value <= 1:
        raise ValueError(f"gross_exposure 必须 0 < x <= 1（收到 {value!r}）")
    return float(value)


def _validate_strict_int(value: int, field: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} 必须为 strict int（bool 拒绝，收到 {value!r}）")
    if value < minimum:
        raise ValueError(f"{field} 必须 >= {minimum}（收到 {value!r}）")
    return value


class SelectionSpec(BaseModel):
    """证券选择契约（M7 v1：top_k）。

    - k：strict int >= 1（bool 拒绝）
    - tie_breaker：code_asc（cutoff 处相同 signal 按 code 升序——输入行序
      不影响 Top-K 结果）
    - null_policy：drop（signal null 不进入 candidate ranking）
    - on_insufficient：use_available（全部可用）/ all_cash（该日显式 0 仓位）
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["top_k"] = "top_k"
    k: StrictInt          # strict int：拒绝 "30"/1.5/True/False（bool subclass of int 显式拦截）
    tie_breaker: Literal["code_asc"] = "code_asc"
    null_policy: Literal["drop"] = "drop"
    on_insufficient: Literal["use_available", "all_cash"] = "use_available"

    @field_validator("k")
    @classmethod
    def _k_valid(cls, v: int) -> int:
        return _validate_strict_int(v, "k", minimum=1)


class WeightingSpec(BaseModel):
    """权重契约（M7 v1：equal_weight only）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["equal_weight"] = "equal_weight"


class StrategySpec(BaseModel):
    """策略契约 v1：把 SignalArtifact 转为 TargetPortfolio 的完整声明。

    - name：策略名（^[A-Za-z_][A-Za-z0-9_]{0,63}$）
    - signal_name：期望消费的 SignalArtifact.meta.name（M7-02 实际检查）
    - direction：±1（signal 越大越优 / 越小越优）
    - selection / weighting：选择与加权子契约
    - gross_exposure：0 < x <= 1（有限、非 bool；剩余为隐式现金）
    - rebalance_frequency：M7 v1 仅 daily（调仓日历语义属 M7-03）
    **禁止**：target/forward_return/label/commission/slippage 等字段
    （extra="forbid" fail fast）。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    signal_name: str
    direction: Literal[1, -1]
    selection: SelectionSpec
    weighting: WeightingSpec
    gross_exposure: float = 1.0
    rebalance_frequency: Literal["daily", "weekly", "monthly"] = "daily"

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        return _validate_name(v, "name")

    @field_validator("signal_name")
    @classmethod
    def _signal_name_valid(cls, v: str) -> str:
        return _validate_name(v, "signal_name")

    @field_validator("direction", mode="before")
    @classmethod
    def _direction_valid(cls, v) -> int:
        if isinstance(v, bool):
            raise ValueError("direction 不能是 bool（True==1 的 int 子类陷阱）")
        return v

    @field_validator("gross_exposure", mode="before")
    @classmethod
    def _gross_valid(cls, v) -> float:
        return _validate_gross_exposure(v)
