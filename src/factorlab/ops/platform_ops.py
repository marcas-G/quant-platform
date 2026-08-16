from __future__ import annotations

import ast
import copy

import polars as pl

from factorlab.factor.errors import FactorDSLError
from factorlab.ops.registry import factor_op


def returns(close: pl.Expr) -> pl.Expr:
    """单期收益率：close / prev_close - 1。"""
    return close / close.shift(1) - 1


def vwap(high: pl.Expr, low: pl.Expr, close: pl.Expr, volume: pl.Expr) -> pl.Expr:
    """成交量加权均价（累计式）。"""
    typical = (high + low + close) / 3
    return (typical * volume).cum_sum() / volume.cum_sum()


def adv20(volume: pl.Expr) -> pl.Expr:
    """20 日均成交额/量。"""
    return volume.rolling_mean(window_size=20)


def group_rank(key: pl.Expr, x: pl.Expr) -> pl.Expr:
    """组内排名：x 按 key 分组后取 rank。"""
    return x.rank().over(key)


def group_mean(key: pl.Expr, x: pl.Expr) -> pl.Expr:
    """组内均值：x 按 key 分组后取 mean。"""
    return x.mean().over(key)


def register_platform_ops() -> None:
    """幂等注册平台薄封装算子，供分区校验与 op list 使用。"""
    factor_op("returns", kind="ts", version="0.1.0")(returns)
    factor_op("vwap", kind="ts", version="0.1.0")(vwap)
    factor_op("adv20", kind="ts", version="0.1.0")(adv20)
    factor_op("group_rank", kind="gp", version="0.1.0")(group_rank)
    factor_op("group_mean", kind="gp", version="0.1.0")(group_mean)


# ---------------------------------------------------------------------------
# 宏展开：expr_codegen 按源码中函数名前缀（ts_/cs_/gp_）分区，把薄封装直接
# 展开为 ts_ 表达式，让窗口语义真正按 asset 分区，避免全表 shift 跨资产泄漏。
# ---------------------------------------------------------------------------

_MACRO_IMPORTS = ("ts_delay", "ts_mean", "ts_cum_sum")


def _name(id_: str) -> ast.Name:
    return ast.Name(id=id_, ctx=ast.Load())


def _const(value: float | int) -> ast.Constant:
    return ast.Constant(value=value)


def _call(name: str, *args: ast.expr) -> ast.Call:
    return ast.Call(func=_name(name), args=list(args), keywords=[])


def _bin(left: ast.expr, op: type, right: ast.expr) -> ast.BinOp:
    return ast.BinOp(left=left, op=op(), right=right)


def _expanded_returns(x: ast.expr) -> ast.expr:
    return _bin(_bin(x, ast.Div, _call("ts_delay", x, _const(1))), ast.Sub, _const(1))


def _expanded_adv20(x: ast.expr) -> ast.expr:
    return _call("ts_mean", x, _const(20))


def _expanded_vwap(high: ast.expr, low: ast.expr, close: ast.expr, volume: ast.expr) -> ast.expr:
    typical = _bin(_bin(_bin(high, ast.Add, low), ast.Add, close), ast.Div, _const(3))
    return _bin(
        _call("ts_cum_sum", _bin(typical, ast.Mult, volume)),
        ast.Div,
        _call("ts_cum_sum", volume),
    )


_MACROS: dict[str, tuple[callable, int, frozenset[str]]] = {
    "returns": (_expanded_returns, 1, frozenset({"ts_delay"})),
    "adv20": (_expanded_adv20, 1, frozenset({"ts_mean"})),
    "vwap": (_expanded_vwap, 4, frozenset({"ts_cum_sum"})),
}


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """收集 import 别名：'from mod import returns as ret' → {'ret': 'returns'}。"""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    return aliases


class _MacroExpander(ast.NodeTransformer):
    """把顶层公式中的平台薄封装调用（含 import 别名）替换为 ts_ 表达式。"""

    def __init__(self, defined: set[str], aliases: dict[str, str]) -> None:
        self.defined = defined
        self.aliases = aliases
        self.used: set[str] = set()

    def visit_Call(self, node: ast.Call) -> ast.expr:
        node = self.generic_visit(node)
        if not isinstance(node.func, ast.Name):
            return node
        name = self.aliases.get(node.func.id, node.func.id)
        if name in self.defined:
            return node
        macro = _MACROS.get(name)
        if macro is None:
            return node
        expand, argc, imports = macro
        if len(node.args) != argc:
            raise FactorDSLError(
                f"{name} 需要 {argc} 个参数，实际 {len(node.args)} 个",
                node.lineno,
                node.col_offset,
            )
        self.used.update(imports)
        return expand(*node.args)


def expand_platform_macros(source: str) -> str:
    """把公式中的 returns/vwap/adv20 调用展开为 ts_ 表达式（分区安全）。

    展开后如需新算子 import，自动在源码头部注入，保证 codegen 作用域可用。
    """
    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    expander = _MacroExpander(defined, _import_aliases(tree))
    transformed = expander.visit(tree)
    if not expander.used:
        return source
    imports = ", ".join(sorted(expander.used))
    return f"from polars_ta.prefix.wq import {imports}\n{ast.unparse(transformed)}"


def expand_user_macros(source: str, operators: dict[str, "OperatorMacro"]) -> str:
    """spec.operators 内联宏展开：name(args) → formula（params 按位置绑定替换）。

    展开在 expand_platform_macros 之前（用户宏公式可引用平台薄封装，如 returns(x)）；
    公式内 def 同名函数优先（不展开）。单遍展开：用户宏公式内嵌套引用其他用户宏
    不支持（沿用未展开名称，由下游 codegen 报未知算子）。
    参数绑定按 AST Name 节点替换（而非字符串 replace），避免短参数名（如 n）误替换
    ts_mean/ts_min 等标识符中的子串。
    """
    if not operators:
        return source
    from factorlab.spec import OperatorMacro  # 延迟导入避免循环

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise FactorDSLError(f"语法错误: {exc.msg}", exc.lineno, exc.offset) from exc
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    def _bind_names(node: ast.AST, binding: dict[str, ast.expr]) -> ast.AST:
        """深度替换表达式树中的参数名 Name 为调用实参（每处实参深拷贝）。"""
        for field, value in ast.iter_fields(node):
            if isinstance(value, ast.AST):
                setattr(node, field, _bind_names(value, binding))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, ast.AST):
                        value[i] = _bind_names(item, binding)
        if isinstance(node, ast.Name) and node.id in binding:
            return copy.deepcopy(binding[node.id])
        return node

    class _UserMacroExpander(ast.NodeTransformer):
        def visit_Call(self, node: ast.Call) -> ast.expr:
            node = self.generic_visit(node)
            if not isinstance(node.func, ast.Name) or node.func.id not in operators:
                return node
            if node.func.id in defined:
                return node
            macro = operators[node.func.id]
            params = macro.params or []
            if len(node.args) != len(params):
                raise FactorDSLError(
                    f"宏 {node.func.id} 需要 {len(params)} 个参数，实际 {len(node.args)} 个",
                    node.lineno,
                    node.col_offset,
                )
            try:
                expr = ast.parse(macro.formula, mode="eval").body
            except SyntaxError as exc:
                raise FactorDSLError(
                    f"宏 {node.func.id} 展开失败: {exc.msg}",
                    node.lineno,
                    node.col_offset,
                ) from exc
            expanded = _bind_names(expr, dict(zip(params, node.args)))
            expanded = ast.fix_missing_locations(expanded)
            expanded.lineno, expanded.col_offset = node.lineno, node.col_offset
            return expanded

    return ast.unparse(_UserMacroExpander().visit(tree))
