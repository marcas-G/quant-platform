"""M8：Execution Runtime 领域层。

M8-01 只定义契约：ExecutionSpec。PortfolioState/OrderBatch/OrderSide/
PortfolioStatePhase 位于 factorlab.domain.execution。
Execution 算法（calendar resolution / target→orders / fills / accounting）
未实现（M8-02..06）。
"""

from factorlab.execution.spec import ExecutionSpec

__all__ = ["ExecutionSpec"]
