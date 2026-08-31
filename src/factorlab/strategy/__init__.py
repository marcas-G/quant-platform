"""M7：Strategy Runtime 领域层。

M7-01：契约（StrategySpec / SelectionSpec / WeightingSpec）。
M7-02：PortfolioConstructor（construct_target_portfolio）。
M8 Execution Runtime 未实现。
"""

from factorlab.strategy.constructor import construct_target_portfolio
from factorlab.strategy.spec import SelectionSpec, StrategySpec, WeightingSpec

__all__ = ["StrategySpec", "SelectionSpec", "WeightingSpec",
           "construct_target_portfolio"]
