"""M8：Execution Runtime 领域层。

M8-01：契约（ExecutionSpec；PortfolioState/OrderBatch/enums 在
factorlab.domain.execution）。
M8-02：calendar resolver（resolve_execution_schedule）+ market-open snapshot
（load_market_open_snapshot）。
M8-03：deterministic net order planning（construct_order_batch）。
M8-04B：conservative open fillability（assess_open_fillability）。
M8-05A：execution cost contracts（ExecutionCostSpec + compute_execution_cost）。
M8-04C：cost-aware realized funding（realize_open_fills → FillBatch）。
M8-04D：same-day POST_EXECUTION state transition（apply_fill_batch）。
M8-04E：overnight T+1 inventory release（advance_to_next_trading_day）。
M8-05B：execution accounting + point-in-time valuation
（summarize_execution_accounting / value_portfolio）。
M8-06B：backtest runtime（run_backtest → BacktestResult）。
"""

from factorlab.execution.accounting import summarize_execution_accounting
from factorlab.execution.backtest import MarksPolicy, run_backtest
from factorlab.execution.calendar import resolve_execution_schedule
from factorlab.execution.costs import (ExecutionCostBreakdown,
                                       compute_execution_cost)
from factorlab.execution.fillability import assess_open_fillability
from factorlab.execution.fills import realize_open_fills
from factorlab.execution.market import load_market_open_snapshot
from factorlab.execution.orders import construct_order_batch
from factorlab.execution.overnight import advance_to_next_trading_day
from factorlab.execution.state import apply_fill_batch
from factorlab.execution.valuation import value_portfolio
from factorlab.execution.rules import (SecurityQuantityRules,
                                       is_valid_buy_quantity,
                                       is_valid_sell_quantity,
                                       project_buy_quantity,
                                       project_sell_quantity,
                                       resolve_security_quantity_rules)
from factorlab.execution.spec import ExecutionCostSpec, ExecutionSpec

__all__ = ["ExecutionSpec", "ExecutionCostSpec", "ExecutionCostBreakdown",
           "compute_execution_cost", "resolve_execution_schedule",
           "load_market_open_snapshot", "construct_order_batch",
           "assess_open_fillability", "realize_open_fills",
           "apply_fill_batch", "advance_to_next_trading_day",
           "summarize_execution_accounting", "value_portfolio",
           "MarksPolicy", "run_backtest",
           "project_buy_quantity", "project_sell_quantity",
           "SecurityQuantityRules", "resolve_security_quantity_rules",
           "is_valid_buy_quantity", "is_valid_sell_quantity"]
