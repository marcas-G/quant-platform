from __future__ import annotations

import ast

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
