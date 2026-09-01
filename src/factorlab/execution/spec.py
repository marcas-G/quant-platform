"""M8-01B / M8-05A：ExecutionSpec——Execution Runtime 配置契约。

- initial_cash：账户初始现金（positive finite float，bool/str 拒绝）
- cost_model：嵌套 ExecutionCostSpec（M8-05A）——**默认 zero-cost**；
  zero default 不代表真实 A 股成本为零——生产 backtest 必须显式配置
  （后续 M8-06 Gate 再 enforce，当前不 enforce nonzero）
- **不拥有 per-security quantity rules**（M8-01B：SecurityQuantityRule 是
  唯一数量权威——全局 lot_size 已移除，传入 lot_size 即 extra=forbid fail）
- **成本参数必须嵌套在 cost_model**（root 直接传 commission/slippage/
  stamp_tax 等即 extra=forbid fail——避免第二套扁平 cost API）
- **不重复时间语义**（最早执行时点复用 M6 SignalTiming 的
  ExecutionTiming——不建立第二套 timing configuration）
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExecutionCostSpec(BaseModel):
    """v1 交易成本模型配置（security-agnostic / time-invariant / 显式保守）。

    - commission_rate：券商佣金比例（0 <= r < 1；0 时 minimum_commission 不生效）
    - minimum_commission：比例佣金被启用后的下限（finite >= 0）
    - stamp_tax_sell_rate：印花税（仅 SELL；0 <= r < 1）
    - transfer_fee_rate：过户费（BUY+SELL 均按名义金额；0 <= r < 1；
      v1 不做 SH/SZ/时代条件化——需历史费率版本化时升 CostModel v2）
    - slippage_bps：确定性价格滑点（bps，10_000 bps = 100%；finite >= 0；
      修改 execution_price，不是 fee）
    - 默认全零 = zero-cost model；真实费率 broker-dependent / 历史变化 /
      market-rule dependent——平台不未经版本化声称"真实 A 股成本"
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    commission_rate: float = 0.0
    minimum_commission: float = 0.0
    stamp_tax_sell_rate: float = 0.0
    transfer_fee_rate: float = 0.0
    slippage_bps: float = 0.0

    @field_validator("commission_rate", "stamp_tax_sell_rate",
                     "transfer_fee_rate", mode="before")
    @classmethod
    def _proportional_rate(cls, v, info) -> float:
        if isinstance(v, bool):
            raise ValueError(f"{info.field_name} 不能是 bool")
        if not isinstance(v, (int, float)):
            raise ValueError(
                f"{info.field_name} 必须为数值（string 不自动 cast，收到 {v!r}）")
        if not math.isfinite(v):
            raise ValueError(f"{info.field_name} 必须 finite")
        if not 0 <= v < 1:
            raise ValueError(
                f"{info.field_name} 必须 0 <= r < 1（收到 {v!r}）")
        return float(v)

    @field_validator("minimum_commission", "slippage_bps", mode="before")
    @classmethod
    def _nonnegative(cls, v, info) -> float:
        if isinstance(v, bool):
            raise ValueError(f"{info.field_name} 不能是 bool")
        if not isinstance(v, (int, float)):
            raise ValueError(
                f"{info.field_name} 必须为数值（string 不自动 cast，收到 {v!r}）")
        if not math.isfinite(v):
            raise ValueError(f"{info.field_name} 必须 finite")
        if v < 0:
            raise ValueError(f"{info.field_name} 必须 >= 0（收到 {v!r}）")
        return float(v)


class ExecutionSpec(BaseModel):
    """执行配置（long-only A 股、嵌套成本模型、无全局数量规则）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_cash: float = 1_000_000.0
    # default_factory：每个 ExecutionSpec 实例独立 cost_model（frozen 对象
    # 虽不可变，仍避免 pydantic 默认值实例共享）
    cost_model: ExecutionCostSpec = Field(default_factory=ExecutionCostSpec)

    @field_validator("initial_cash", mode="before")
    @classmethod
    def _cash_valid(cls, v) -> float:
        if isinstance(v, bool):
            raise ValueError("initial_cash 不能是 bool")
        if not isinstance(v, (int, float)):
            raise ValueError(
                f"initial_cash 必须为数值（string 不自动 cast，收到 {v!r}）")
        if not math.isfinite(v):
            raise ValueError("initial_cash 必须 finite")
        if v <= 0:
            raise ValueError(f"initial_cash 必须 > 0（收到 {v!r}）")
        return float(v)
