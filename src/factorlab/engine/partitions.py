from __future__ import annotations

import ast

from factorlab.factor.errors import FactorDSLError
from factorlab.ops import registry

# 元素级纯函数（Python/Polars 语义，无窗口、无分组），不进入算子注册表。
_ELEMENTWISE = {
    "abs", "log", "log1p", "sqrt", "exp", "sign", "floor", "ceil", "round",
    "where", "if_else", "isnan", "isfinite",
}


def _call_names(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            yield node


def validate_partition_calls(source: str) -> None:
    """拒绝未知算子调用；已知 ts_/cs_/gp_/ta_ 算子与平台薄封装、元素级函数放行。"""
    tree = ast.parse(source)
    for node in _call_names(tree):
        name = node.func.id
        if name in _ELEMENTWISE:
            continue
        if not registry.has_op(name):
            raise FactorDSLError(f"未知算子: {name}", node.lineno, node.col_offset)


def reject_future_shifts(source: str) -> None:
    """拒绝负 lookback：ts_delay/ts_delta 的位移参数不能为负（字面量）。"""
    tree = ast.parse(source)
    for node in _call_names(tree):
        if node.func.id in {"ts_delay", "ts_delta"} and len(node.args) >= 2:
            shift = node.args[1]
            if isinstance(shift, ast.UnaryOp) and isinstance(shift.op, ast.USub):
                raise FactorDSLError(
                    f"{node.func.id} 不允许负位移（lookback 只能取过去）",
                    node.lineno,
                    node.col_offset,
                )
