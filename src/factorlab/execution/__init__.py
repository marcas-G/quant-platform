"""M8：Execution Runtime 领域层。

M8-01：契约（ExecutionSpec；PortfolioState/OrderBatch/enums 在
factorlab.domain.execution）。
M8-02：calendar resolver（resolve_execution_schedule）+ market-open snapshot
（load_market_open_snapshot）。
M8-03..06（target→orders / fills / accounting / backtest）未实现。
"""

from factorlab.execution.calendar import resolve_execution_schedule
from factorlab.execution.market import load_market_open_snapshot
from factorlab.execution.spec import ExecutionSpec

__all__ = ["ExecutionSpec", "resolve_execution_schedule",
           "load_market_open_snapshot"]
