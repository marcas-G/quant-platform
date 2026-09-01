"""M8-05A：Execution Cost Model——pure cost functions（security-agnostic）。

```
side + reference_price + quantity + ExecutionCostSpec
        │
        ▼
reference price
   → slippage（BUY ×(1+bps/1e4)、SELL ×(1-bps/1e4)——修改 execution_price，
     不是 fee）
   → execution price
   → gross notional = execution_price × quantity
   → commission（rate==0 → 0；否则 max(gross×rate, minimum_commission)）
   → stamp tax（仅 SELL：gross × stamp_tax_sell_rate）
   → transfer fee（BUY/SELL：gross × transfer_fee_rate）
   → total fees = commission + stamp + transfer
   → effective cash delta（BUY：-(gross+fees)；SELL：+（gross-fees））
```

边界：
- **pure**：不 import duckdb/polars/MarketOpenSnapshot/PortfolioState/
  OrderBatch/TargetPortfolio/DB；只依赖 stdlib + pydantic spec + OrderSide
- **continuous Float64 货币算术**：无 Decimal、无分位 rounding（券商费用
  取整规则尚未建模）
- v1 security-agnostic / time-invariant：不接收 code/market/date
- pathological config（SELL total_fees >= gross、SELL execution_price <= 0）
  → ValueError——不输出 zero/negative proceeds 作为正常结果；BUY 允许
  fees > notional（minimum commission 在小交易上），cash requirement =
  notional + fees
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from factorlab.domain.execution import OrderSide
from factorlab.execution.spec import ExecutionCostSpec


@dataclass(frozen=True)
class ExecutionCostBreakdown:
    """单笔订单的 monetary cost breakdown（纯值对象，非 persistence domain）。

    - 不携带 code/date/strategy/quantity——quantity 是 compute 输入
    - effective_cash_delta：BUY 负（-(gross+fees)）；SELL 正（gross-fees）
    - execution_price：slippage 后的成交价（BUY >= reference、SELL <= reference）
    """

    gross_notional: float
    commission: float
    stamp_tax: float
    transfer_fee: float
    total_fees: float
    effective_cash_delta: float
    execution_price: float

    def __post_init__(self) -> None:
        for name, v in (("gross_notional", self.gross_notional),
                        ("execution_price", self.execution_price)):
            if not math.isfinite(v) or v <= 0:
                raise ValueError(f"{name} 必须 finite > 0（收到 {v!r}）")
        for name, v in (("commission", self.commission),
                        ("stamp_tax", self.stamp_tax),
                        ("transfer_fee", self.transfer_fee),
                        ("total_fees", self.total_fees)):
            if not math.isfinite(v) or v < 0:
                raise ValueError(f"{name} 必须 finite >= 0（收到 {v!r}）")


def compute_execution_cost(
    *,
    side: OrderSide,
    reference_price: float,
    quantity: int,
    spec: ExecutionCostSpec,
) -> ExecutionCostBreakdown:
    """计算单笔订单的成本 breakdown（v1：security-agnostic、time-invariant）。

    Raises:
        TypeError: side 非 OrderSide / quantity 非 int / spec 非 ExecutionCostSpec
        ValueError: price/quantity/slippage 组合非法（SELL price<=0、
          SELL total_fees >= gross、gross notional 溢出等）
    """
    if not isinstance(side, OrderSide):
        raise TypeError(
            f"side 必须为 OrderSide 实例（收到 {type(side).__name__}——"
            f"拒绝字符串第二套 API）")
    if not isinstance(spec, ExecutionCostSpec):
        raise TypeError(
            f"spec 必须为 ExecutionCostSpec 实例（收到 {type(spec).__name__}）"
            f"——dict 不自动转换")
    if isinstance(reference_price, bool) or not isinstance(reference_price,
                                                           (int, float)):
        raise TypeError(f"reference_price 必须为数值（收到 {reference_price!r}）")
    if not math.isfinite(reference_price) or reference_price <= 0:
        raise ValueError(
            f"reference_price 必须 finite > 0（收到 {reference_price!r}）")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise TypeError(f"quantity 必须为 Python int（收到 {quantity!r}）")
    if quantity <= 0:
        raise ValueError(f"quantity 必须 > 0（收到 {quantity!r}）")

    # ---- reference price → slippage → execution price ----
    slip_factor = 1.0 + (spec.slippage_bps / 10_000.0) if side is OrderSide.BUY \
        else 1.0 - (spec.slippage_bps / 10_000.0)
    execution_price = reference_price * slip_factor
    if not math.isfinite(execution_price) or execution_price <= 0:
        raise ValueError(
            f"slippage 后 execution_price 非法（{execution_price!r}——"
            f"SELL slippage_bps >= 10000 或 overflow；不 clipping 到 0.01）")

    # ---- gross notional ----
    gross = execution_price * quantity
    if not math.isfinite(gross) or gross <= 0:
        raise ValueError(f"gross notional 溢出/非法（{gross!r}）")

    # ---- fees ----
    if spec.commission_rate == 0:
        commission = 0.0
    else:
        commission = max(gross * spec.commission_rate, spec.minimum_commission)
    stamp = gross * spec.stamp_tax_sell_rate if side is OrderSide.SELL else 0.0
    transfer = gross * spec.transfer_fee_rate
    total_fees = commission + stamp + transfer

    # ---- effective cash delta ----
    if side is OrderSide.SELL:
        if total_fees >= gross:
            raise ValueError(
                f"SELL total_fees {total_fees} >= gross {gross}——pathological "
                f"cost config，不输出 zero/negative proceeds 作为正常结果")
        cash_delta = gross - total_fees
    else:
        cash_delta = -(gross + total_fees)

    return ExecutionCostBreakdown(
        gross_notional=gross,
        commission=commission,
        stamp_tax=stamp,
        transfer_fee=transfer,
        total_fees=total_fees,
        effective_cash_delta=cash_delta,
        execution_price=execution_price,
    )
