"""M8：Execution Runtime 领域层。

M8-01：契约（ExecutionSpec；PortfolioState/OrderBatch/enums 在
factorlab.domain.execution）。
M8-02：calendar resolver（resolve_execution_schedule）+ market-open snapshot
（load_market_open_snapshot）。
M8-03：deterministic net order planning（construct_order_batch）。
M8-04B：conservative open fillability（assess_open_fillability）。
M8-04C..06（funding/fills / accounting / backtest）未实现。
"""

from factorlab.execution.calendar import resolve_execution_schedule
from factorlab.execution.fillability import assess_open_fillability
from factorlab.execution.market import load_market_open_snapshot
from factorlab.execution.orders import construct_order_batch
from factorlab.execution.rules import (SecurityQuantityRules,
                                       is_valid_buy_quantity,
                                       is_valid_sell_quantity,
                                       resolve_security_quantity_rules)
from factorlab.execution.spec import ExecutionSpec

__all__ = ["ExecutionSpec", "resolve_execution_schedule",
           "load_market_open_snapshot", "construct_order_batch",
           "assess_open_fillability",
           "SecurityQuantityRules", "resolve_security_quantity_rules",
           "is_valid_buy_quantity", "is_valid_sell_quantity"]
