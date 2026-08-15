from __future__ import annotations

import ast

from factorlab.factor.errors import FactorDSLError
from factorlab.ops import registry

# 元素级纯函数（Python/Polars 语义，无窗口、无分组），不进入算子注册表。
# 名单与 expr_codegen 生成代码的作用域逐一核对：缺失的名字会以 NameError 泄漏。
_ELEMENTWISE = {
    "abs", "log", "log1p", "sqrt", "exp", "sign", "floor", "if_else",
}


def _call_names(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            yield node


def _alias_map(tree: ast.AST) -> dict[str, str]:
    """收集 import 别名：'from mod import ts_delay as d' → {'d': 'ts_delay'}。"""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    return aliases


def validate_partition_calls(source: str) -> None:
    """拒绝未知算子调用；公式内 def 函数、已知 ts_/cs_/gp_/ta_ 算子与平台薄封装、元素级函数放行。

    同时拒绝 def 体内的窗口/截面算子：expr_codegen 把用户 def 当黑盒整体放进
    元素级分区执行，def 内的 ts_/cs_ 调用会在全表上跑窗口，跨资产泄漏。放开条件
    是宏展开器能把窗口语义显式写成顶层 ts_ 调用。
    """
    tree = ast.parse(source)
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    aliases = _alias_map(tree)

    for node in _call_names(tree):
        name = aliases.get(node.func.id, node.func.id)
        if name in defined or name in _ELEMENTWISE:
            continue
        if not registry.has_op(name):
            raise FactorDSLError(f"未知算子: {name}", node.lineno, node.col_offset)

    for fn in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        for node in _call_names(fn):
            name = aliases.get(node.func.id, node.func.id)
            if name in defined or name in _ELEMENTWISE:
                continue
            if registry.has_op(name):
                raise FactorDSLError(
                    f"窗口/截面算子 {node.func.id} 不能在 def 内使用，请直接写在公式顶层",
                    node.lineno,
                    node.col_offset,
                )


def _const_fold(node: ast.expr):
    """常量折叠（仅 int/float 字面量，绝不 eval）；非常量表达式返回 None。"""
    if isinstance(node, ast.Constant):
        value = node.value
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if isinstance(node, ast.UnaryOp):
        value = _const_fold(node.operand)
        if value is None:
            return None
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        left, right = _const_fold(node.left), _const_fold(node.right)
        if left is None or right is None:
            return None
        op = type(node.op)
        try:
            if op is ast.Add:
                return left + right
            if op is ast.Sub:
                return left - right
            if op is ast.Mult:
                return left * right
            if op is ast.Div:
                return left / right
            if op is ast.FloorDiv:
                return left // right
            if op is ast.Mod:
                return left % right
            if op is ast.Pow:
                return left ** right
        except (ZeroDivisionError, OverflowError):
            return None
    return None


def reject_future_shifts(source: str) -> None:
    """拒绝负 lookback：ts_delay/ts_delta 的位移参数不能为负（字面量可折叠）。"""
    tree = ast.parse(source)
    for node in _call_names(tree):
        if node.func.id not in {"ts_delay", "ts_delta"}:
            continue
        shift: int | float | None = None
        if len(node.args) >= 2:
            shift = _const_fold(node.args[1])
        else:
            for kw in node.keywords:
                if kw.arg == "d":
                    shift = _const_fold(kw.value)
        if shift is not None and shift < 0:
            raise FactorDSLError(
                f"{node.func.id} 不允许负位移（lookback 只能取过去）",
                node.lineno,
                node.col_offset,
            )
