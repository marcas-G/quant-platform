"""平台-owned stable dense-rank（M6-07C2I）。

**函数名 cs_stable_rank（cs_ 前缀）**——expr_codegen 按前缀识别 CS 分区
（生成 .over(_DATE_) 横截面），否则 per-asset 分区语义错误。

cs_rank v2：Float64 近 tie（数值间隔 <= STABLE_RANK_MAX_ULPS ULP）按
**组 anchor** 规则归为一个 dense level——避免 machine-noise 假拆分把
reduction 噪声放大为人工 rank level（C2H：000586/002609 数学 tie 被
1 ULP 拆开 → denominator 变化 → 全截面 normalized rank 平移）。

规则：
- group anchor = 组内第一个（排序序）值；后续值 vs anchor 的 ULP <= tie_ulps
  才加入当前组（**anti-chaining**：A、A+4、A+8 → [A,A+4]、[A+8]）
- tie_ulps=0 → legacy exact-bit dense rank（与 vendor polars_ta.cs_rank 一致）
- 非 Float 输入（Int/UInt/Boolean）→ exact tie 语义（不 fuzzy）
- null → null；+0.0/-0.0 同组；NaN → null
- pct=True：level / max(K-1, 1)（0..1）；pct=False：1..K（UInt32）
- 不修改 vendor；公式预处理把 cs_rank 改写为本实现（见 rewrite_stable_rank）
"""

from __future__ import annotations

import ast

import numpy as np
import polars as pl

from factorlab.numerics import float64_ulp_distance
from factorlab.ops.registry import factor_op

STABLE_RANK_MAX_ULPS = 4


def validate_tie_ulps(tie_ulps: int) -> None:
    """tie_ulps 必须为非负整数（bool 拒绝）。"""
    if isinstance(tie_ulps, bool) or not isinstance(tie_ulps, int) or tie_ulps < 0:
        raise ValueError(
            f"tie_ulps 必须为非负整数（收到 {tie_ulps!r}）——stable cs_rank 不允许")


def _legacy_dense(x: pl.Expr, pct: bool) -> pl.Expr:
    """legacy exact-bit dense rank（vendor polars_ta.cs_rank 等价语义）。"""
    if pct:
        r = x.rank(method="dense") - 1
        return r / max_horizontal(r.max(), 1)
    return x.rank(method="dense")


def max_horizontal(a, b):
    """与 vendor polars_ta.utils 的 max_horizontal 等价的元素级 max（Expr 层）。"""
    from polars import when
    return when(a > b).then(a).otherwise(b)


def _np_stable_levels(vals: np.ndarray, tie_ulps: int) -> np.ndarray:
    """sorted 数组的 stable dense levels（0-based，anchor 规则）。

    vals 必须已按数值升序（有限值）。**性能**：ordered bits 向量化一次
    （float64_ordered_uint），循环内只做 Python int 减法比较——避免逐元素
    numpy 数组构造（§49：stable 不得 >3x legacy wall）。
    """
    from factorlab.numerics import float64_ordered_uint
    n = len(vals)
    levels = np.zeros(n, dtype=np.int64)
    if n == 0:
        return levels
    ob = float64_ordered_uint(vals)
    level, anchor = 0, int(ob[0])
    for i in range(1, n):
        oi = int(ob[i])
        d = oi - anchor if oi >= anchor else anchor - oi
        if d > tie_ulps:
            level += 1
            anchor = oi
        levels[i] = level
    return levels


def _stable_series(s: pl.Series, pct: bool, tie_ulps: int) -> pl.Series:
    """组内（per over-partition）Series → stable dense rank Series。

    非 Float 输入（Int/UInt/Boolean）→ exact tie（np.unique inverse——
    与 vendor exact-bit dense 语义一致，不 fuzzy）。
    """
    out = np.full(len(s), np.nan)
    if not s.dtype.is_float():
        # exact tie dense level（数值升序的 dense 编号）
        arr = s.to_numpy()
        valid = ~pd_isna(arr)
        pos = np.where(valid)[0]
        if pos.size:
            _, inv = np.unique(arr[pos], return_inverse=True)
            lev = inv.astype(np.float64)
            if pct:
                k = int(lev.max()) if len(lev) else 0
                lev = lev / max(k, 1)
            else:
                lev = lev + 1.0
            out[pos] = lev
        return pl.Series(s.name, out, dtype=pl.Float64 if pct else pl.UInt32).fill_nan(None)
    vals = s.cast(pl.Float64).to_numpy()   # null → nan
    valid = ~np.isnan(vals)
    pos = np.where(valid)[0]
    if pos.size:
        fv = vals[pos]
        order = np.argsort(fv, kind="stable")
        levels = _np_stable_levels(fv[order], tie_ulps)
        lev = np.empty(len(fv), dtype=np.float64)
        lev[order] = levels
        if pct:
            k = int(levels.max()) if len(levels) else 0
            lev = lev / max(k, 1)
        else:
            lev = lev + 1.0
        out[pos] = lev
    return pl.Series(s.name, out, dtype=pl.Float64 if pct else pl.UInt32).fill_nan(None)


def pd_isna(arr) -> np.ndarray:
    """对象/数值数组的 null 掩码（Int 列 to_numpy → object with None）。"""
    arr = np.asarray(arr)
    if arr.dtype == object:
        return np.array([v is None for v in arr])
    return np.isnan(arr.astype(np.float64))


def cs_stable_rank(x: pl.Expr, pct: bool = True, tie_ulps: int = STABLE_RANK_MAX_ULPS) -> pl.Expr:
    """横截面 stable dense rank（平台 owned，M6-07C2I v2 生产语义）。

    - 默认 tie_ulps=4（M6 已验证的 ts_mean(close,20) machine-noise envelope）
    - tie_ulps=0 → legacy exact-bit tie（显式迁移选项）
    - 非 Float 输入自动 exact tie（不 fuzzy）
    """
    validate_tie_ulps(tie_ulps)
    if tie_ulps == 0:
        return _legacy_dense(x, pct)
    return x.map_batches(
        lambda s: _stable_series(s, pct, tie_ulps),
        return_dtype=pl.Float64 if pct else pl.UInt32,
    )


# ---------------------------------------------------------------------------
# Formula rewrite：cs_rank(...) → stable_cs_rank(...)（routing，非 monkeypatch）
# ---------------------------------------------------------------------------

def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    return aliases


def rewrite_stable_rank(source: str) -> str:
    """把公式中的 cs_rank 调用改写为平台 cs_stable_rank（+ 注入 import）。

    **命名必须以 cs_ 前缀开头**：expr_codegen 按函数名前缀识别 CS 分区
    （生成代码 .over(_DATE_) 横截面）；非 cs_ 前缀会被当作 TS/普通表达式
    包成 per-asset 分区（错误语义）。

    - canonical `cs_rank(...)`（或 import alias 引用）→ stable_cs_rank(...)
    - 模块限定 `wq.cs_rank(...)`（Attribute）→ stable_cs_rank(...)
    - 用户 def cs_rank 优先（不改写，§18 precedence）
    - 幂等：已改写/无 cs_rank 原样返回
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    aliases = _import_aliases(tree)

    class _Rewriter(ast.NodeTransformer):
        def __init__(self):
            self.used = False

        def visit_Call(self, node: ast.Call) -> ast.Call:
            node = self.generic_visit(node)
            name = None
            if isinstance(node.func, ast.Name):
                name = aliases.get(node.func.id, node.func.id)
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "cs_rank":
                name = "cs_rank"
            if name == "cs_rank" and name not in defined:
                node.func = ast.Name(id="cs_stable_rank", ctx=ast.Load())
                self.used = True
            return node

    rewriter = _Rewriter()
    out = ast.unparse(rewriter.visit(tree))
    if rewriter.used:
        out = "from factorlab.ops.stable_rank import cs_stable_rank\n" + out
    return out


def register_stable_rank_ops() -> None:
    """幂等注册 cs_stable_rank（kind=cs、version 0.2.0——v2 stable tie 语义）。

    显式函数而非模块顶层装饰：registry 可能被 reset_registry() 清空（测试
    fixture），compute_formula 每次调用都执行本函数保证分区校验可用。
    universe_masking 的 _CS_GP_MASK_ARGS 同步识别该名字。
    """
    factor_op("cs_stable_rank", kind="cs", version="0.2.0")(cs_stable_rank)
