"""M7：Strategy Runtime 领域层。

M7-01 只定义契约：StrategySpec / SelectionSpec / WeightingSpec。
PortfolioConstructor（M7-02）与 Execution Runtime（M8）未实现。
"""

from factorlab.strategy.spec import SelectionSpec, StrategySpec, WeightingSpec

__all__ = ["StrategySpec", "SelectionSpec", "WeightingSpec"]
