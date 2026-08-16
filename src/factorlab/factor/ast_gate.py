from __future__ import annotations

import ast

from factorlab.factor.errors import FactorDSLError


ALLOWED_NODES = {
    ast.Module,
    ast.Import,
    ast.ImportFrom,
    ast.alias,
    ast.FunctionDef,
    ast.ClassDef,
    ast.Assign,
    ast.AnnAssign,
    ast.Expr,
    ast.Return,
    ast.arguments,
    ast.arg,
    ast.Name,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.Attribute,
    ast.IfExp,
    ast.Subscript,
    ast.Tuple,
    ast.List,
    ast.Load,
    ast.Store,
    ast.keyword,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
}

ALLOWED_IMPORT_PREFIXES = (
    "polars",
    "polars_ta.prefix.",
    "factorlab.ops.",
)

FORBIDDEN_CALLS = {"eval", "exec", "open", "compile", "__import__"}

# polars Expr 纯元素级方法白名单（与元素级函数名单同语义——无窗口、无分组、无副作用）。
# 属性调用仅放行「白名单方法 + 基表达式非裸 Name」：ts_delta(x, 1).abs() 合法
# （free-form 设计 §2.1）；np.abs / pl.read_csv / x.rolling_mean 仍被拒。
ALLOWED_EXPR_METHODS = {"abs", "log", "log1p", "sqrt", "exp", "sign", "floor"}


def _is_allowed_import(module: str | None) -> bool:
    return module is not None and module.startswith(ALLOWED_IMPORT_PREFIXES)


def validate_formula(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise FactorDSLError(f"语法错误: {exc.msg}", exc.lineno, exc.offset) from exc

    for node in ast.walk(tree):
        if type(node) not in ALLOWED_NODES:
            raise FactorDSLError(
                f"不支持的语法节点: {type(node).__name__}",
                getattr(node, "lineno", None),
                getattr(node, "col_offset", None),
            )

        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_allowed_import(alias.name):
                    raise FactorDSLError(
                        f"禁止导入模块: {alias.name}",
                        node.lineno,
                        node.col_offset,
                    )

        if isinstance(node, ast.ImportFrom):
            if not _is_allowed_import(node.module):
                raise FactorDSLError(
                    f"禁止导入模块: {node.module}",
                    node.lineno,
                    node.col_offset,
                )

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                raise FactorDSLError(
                    f"禁止调用函数: {node.func.id}",
                    node.lineno,
                    node.col_offset,
                )

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # 仅放行纯元素级方法链在表达式结果上（基表达式非裸 Name——模块/对象属性如
            # np.abs、pl.read_csv 仍属禁止的属性调用）
            if isinstance(node.func.value, ast.Name) or node.func.attr not in ALLOWED_EXPR_METHODS:
                raise FactorDSLError(
                    "禁止属性调用；请使用已导入的算子函数"
                    f"（元素级方法链仅限 {sorted(ALLOWED_EXPR_METHODS)}）",
                    node.lineno,
                    node.col_offset,
                )
