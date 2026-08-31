"""M8-01：ExecutionSpec——Execution Runtime 配置契约。

- initial_cash：账户初始现金（positive finite float，bool/str 拒绝）
- lot_size：M8 v1 固定 100（canonical A 股；ETF/期货等另版本化）
- **无成本参数**（commission/stamp_tax/slippage 属 M8-05 Cost Model）；
  **不重复时间语义**（最早执行时点复用 M6 SignalTiming 的
  ExecutionTiming——不建立第二套 timing configuration）
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class ExecutionSpec(BaseModel):
    """执行配置 v1（long-only A 股、整手 100、无成本模型）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_cash: float = 1_000_000.0
    lot_size: Literal[100] = 100

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
