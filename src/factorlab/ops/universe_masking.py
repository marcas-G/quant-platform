"""M6-03：cross-sectional universe masking——CS/GP 算子的 active universe 掩码变换。

语义：CS/GP 算子在它真正执行的那个阶段只能看到当日 eligible universe——
TS/TA 算子仍可访问该股票合法的 listed market history。

实现：AST 变换，对 kind=cs/gp 算子的**数据参数**包 `if_else(__universe_active, arg, None)`：
    cs_rank(ts_mean(close, 20))
        → cs_rank(if_else(__universe_active, ts_mean(close, 20), None))
    ts_mean(cs_rank(close), 20)
        → ts_mean(cs_rank(if_else(__universe_active, close, None)), 20)

- 数据参数位置由显式 registry 声明（_CS_GP_MASK_ARGS）——不可扩展的字符串 hack
- multi-argument CS（如 cs_resid(y, x)）：所有数据参数都 mask
- GP：group key 不 mask（分组键语义），factor/value 参数 mask
- 无法确认 mask 语义的 CS/GP 算子 → **fail fast**（ValueError，含 operator name）
- mask 列名由调用方注入（如 __universe_active）；用户不得自行定义
"""

from __future__ import annotations

import ast

from factorlab.ops.registry import get_op, has_op

# CS/GP 算子的"数据参数"位置（参与截面统计、需 active mask 的参数）：
# group key（group_rank/group_mean 的第 0 参）不需要改 null（分组键语义）。
# 新增 CS/GP 算子必须在此声明数据参数位置，否则 fail fast。
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


def apply_universe_masking(source: str, mask_name: str) -> str:
    """对公式中 kind=cs/gp 的算子做 universe mask 变换。

    - 未知算子放行（由 validate_partition_calls 报错）
    - 用户 def 内的 CS/GP 调用不 mask（def 黑盒由 validate_partition_calls 拒绝窗口/截面算子）
    - kind=cs/gp 但 registry 未声明数据参数位置 → ValueError（fail fast，含 operator name）
    """
    from factorlab.ops.polars_ta_wrappers import register_polars_ta_ops
    from factorlab.ops.platform_ops import register_platform_ops
    register_polars_ta_ops()   # 幂等：独立调用时注册表可能为空
    register_platform_ops()
    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    class _Masker(ast.NodeTransformer):
        def visit_Call(self, node: ast.Call) -> ast.expr:
            node = self.generic_visit(node)
            if not isinstance(node.func, ast.Name) or node.func.id in defined:
                return node
            name = node.func.id
            if not has_op(name):
                return node
            op = get_op(name)
            if op.kind not in ("cs", "gp"):
                return node
            positions = _CS_GP_MASK_ARGS.get(name)
            if positions is None:
                raise ValueError(
                    f"无法确认 {op.kind} 算子 {name} 的 universe masking 数据参数位置"
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
