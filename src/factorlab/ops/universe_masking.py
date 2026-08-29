"""M6-03：cross-sectional universe masking——CS/GP 算子的 active universe 掩码变换。

语义：CS/GP 算子在它真正执行的那个阶段只能看到当日 eligible universe——
TS/TA 算子仍可访问该股票合法的 listed market history。

实现：AST 变换，对 kind=cs/gp 算子的**数据参数**包 `if_else(<mask>, arg, None)`：
    cs_rank(ts_mean(close, 20))
        → cs_rank(if_else(<mask>, ts_mean(close, 20), None))
    ts_mean(cs_rank(close), 20)
        → ts_mean(cs_rank(if_else(<mask>, close, None)), 20)

M6-03A hardening：
- import alias 与 validate_partition_calls 一致解析（`from wq import cs_rank as r` →
  `r(...)` 按 canonical cs_rank 查 metadata；**不改写用户 callable**）
- registry alias 一律经 canonical OperatorDef.name 查 metadata（future aliases 不误判）
- CS/GP keyword invocation → fail fast（M6 v1 只支持 positional——masking 无歧义）
- 内部保留名 `__factorlab_*` 前缀：用户任何定义/绑定 → fail fast

- 数据参数位置由显式 registry 声明（_CS_GP_MASK_ARGS）——不可扩展的字符串 hack
- multi-argument CS（如 cs_resid(y, x)）：所有数据参数都 mask
- GP：group key 不 mask（分组键语义），factor/value 参数 mask
- 无法确认 mask 语义的 CS/GP 算子 → **fail fast**（ValueError，含 operator name）
"""

from __future__ import annotations

import ast

from factorlab.ops.registry import get_op, has_op

# CS/GP 算子的"数据参数"位置（参与截面统计、需 active mask 的参数）：
# group key（group_rank/group_mean 的第 0 参）不需要改 null（分组键语义）。
# 新增 CS/GP 算子必须在此声明数据参数位置，否则 fail fast。
# **key = canonical OperatorDef.name**（registry alias 一律 canonicalize 后查）。
_CS_GP_MASK_ARGS: dict[str, tuple[int, ...]] = {
    "cs_rank": (0,),
    "cs_zscore": (0,),
    "cs_demean": (0,),
    "cs_scale": (0,),
    "cs_quantile": (0,),
    "cs_mad_zscore": (0,),
    "cs_resid": (0, 1),
    "cs_regression_resid": (0, 1),   # cs_resid 的兼容别名
    "group_rank": (1,),
    "group_mean": (1,),
}

# 内部保留前缀：用户定义/赋值/参数/import alias 以该前缀开头 → fail fast
RESERVED_INTERNAL_PREFIX = "__factorlab_"

# ALLOWED_NODES binding audit（M6-03B）：ast_gate.ALLOWED_NODES 允许的节点中，
# 会创建用户名字绑定的完整清单 = {Import/ImportFrom(alias), FunctionDef, ClassDef,
# Assign, AnnAssign, ast.arg}——全部已纳入 validate_reserved_bindings guard。
# Tuple/List 为 destructuring 容器（不绑定自身，递归展开子 Name）。
# For/With/Lambda/NamedExpr/comprehension/ExceptHandler 不在 ALLOWED_NODES（gate 拒绝），
# 无需 guard——审计结论：当前允许 AST 集合内无其他绑定入口。


def _alias_map(tree: ast.AST) -> dict[str, str]:
    """收集 import 别名（与 engine/partitions.validate_partition_calls 一致语义）：
    'from mod import cs_rank as r' → {'r': 'cs_rank'}。"""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    return aliases


def _bound_names(target: ast.AST):
    """递归枚举 target 中所有绑定 Name（M6-03B：统一 binding extractor）。

    支持 Name / Tuple / List 递归（嵌套 destructuring 全部发现）；
    其他 target 类型当前 DSL 不产生名字绑定——不扩大语言能力（AST gate 已拒绝
    For/With/Lambda/NamedExpr/comprehension 等）。
    """
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _bound_names(elt)


def validate_reserved_bindings(source: str) -> None:
    """用户 source 的保留名绑定校验：`__factorlab_*` 前缀不得出现在任何用户绑定入口。

    绑定入口（ALLOWED_NODES 审计结论，见模块 docstring）：
    Assign（含 Tuple/List destructuring，递归） / AnnAssign / FunctionDef /
    ClassDef / 函数参数（ast.arg）/ import alias。

    必须在平台 transformation（apply_universe_masking 插入内部引用）**之前**执行——
    只检查用户 source 的"定义/绑定"，不检查变换后对内部名的读取。
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                for name in _bound_names(t):
                    if name.startswith(RESERVED_INTERNAL_PREFIX):
                        raise ValueError(
                            f"reserved internal name cannot be assigned by user: {name!r}"
                            f"（{RESERVED_INTERNAL_PREFIX}* 为平台内部保留）")
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id.startswith(RESERVED_INTERNAL_PREFIX):
            raise ValueError(
                f"reserved internal name cannot be assigned by user: {node.target.id!r}")
        elif isinstance(node, ast.FunctionDef) \
                and node.name.startswith(RESERVED_INTERNAL_PREFIX):
            raise ValueError(
                f"reserved internal name cannot be defined by user: {node.name!r}")
        elif isinstance(node, ast.ClassDef) \
                and node.name.startswith(RESERVED_INTERNAL_PREFIX):
            raise ValueError(
                f"reserved internal name cannot be defined by user: {node.name!r}")
        elif isinstance(node, ast.arg) and node.arg.startswith(RESERVED_INTERNAL_PREFIX):
            raise ValueError(
                f"reserved internal name cannot be used as argument: {node.arg!r}")
        elif isinstance(node, ast.alias) \
                and (node.asname or node.name).startswith(RESERVED_INTERNAL_PREFIX):
            raise ValueError(
                f"reserved internal name cannot be used as import alias: "
                f"{(node.asname or node.name)!r}")


def apply_universe_masking(source: str, mask_name: str) -> str:
    """对公式中 kind=cs/gp 的算子做 universe mask 变换。

    - import alias 与 validate_partition_calls 一致解析（alias → canonical 算子名）
    - registry alias 一律经 canonical OperatorDef.name 查 metadata
    - CS/GP keyword invocation → fail fast（M6 v1 positional-only）
    - 未知算子放行（由 validate_partition_calls 报错）
    - 用户 def 内的 CS/GP 调用不 mask（def 黑盒由 validate_partition_calls 拒绝）
    - kind=cs/gp 但 registry 未声明数据参数位置 → ValueError（fail fast，含 operator name）
    - **不改写用户 callable**：mask 只包数据参数，调用名保持原样（alias 原样）
    """
    from factorlab.ops.polars_ta_wrappers import register_polars_ta_ops
    from factorlab.ops.platform_ops import register_platform_ops
    register_polars_ta_ops()   # 幂等：独立调用时注册表可能为空
    register_platform_ops()
    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    aliases = _alias_map(tree)

    class _Masker(ast.NodeTransformer):
        def visit_Call(self, node: ast.Call) -> ast.expr:
            node = self.generic_visit(node)
            if not isinstance(node.func, ast.Name) or node.func.id in defined:
                return node
            name = aliases.get(node.func.id, node.func.id)   # alias → canonical 调用名
            if not has_op(name):
                return node
            op = get_op(name)
            if op.kind not in ("cs", "gp"):
                return node
            if node.keywords:
                raise ValueError(
                    f"CS/GP operator {op.name} 不支持 keyword arguments"
                    f"（universe masking 无歧义要求 positional invocation，M6 v1）: "
                    f"{[k.arg for k in node.keywords]}")
            canonical = op.name                               # registry alias → canonical
            positions = _CS_GP_MASK_ARGS.get(canonical)
            if positions is None:
                raise ValueError(
                    f"无法确认 {op.kind} 算子 {canonical} 的 universe masking 数据参数位置"
                    f"——请在 _CS_GP_MASK_ARGS 声明或避免使用（fail fast，禁止按错误 universe 计算）")
            for i in positions:
                if i < len(node.args):
                    node.args[i] = ast.Call(
                        func=ast.Name(id="if_else", ctx=ast.Load()),
                        args=[ast.Name(id=mask_name, ctx=ast.Load()),
                              node.args[i],
                              ast.Constant(value=None)],
                        keywords=[],
                    )
            return node

    return ast.unparse(_Masker().visit(tree))
