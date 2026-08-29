"""M6-03A：Harden Universe-Masking Boundary——alias/keyword/reserved-name 封堵。

三个 bypass：
1. import alias（`from wq import cs_rank as r`）——masker 必须与 partition validator 一致
2. keyword arguments（`cs_rank(x=close)`）——CS/GP fail fast（positional-only）
3. reserved internal mask name overwrite（`__factorlab_*` 用户绑定）——fail fast
"""

import ast
import datetime

import polars as pl
import pytest

from factorlab.engine.compute import compute_formula
from factorlab.ops import universe_masking as um
from factorlab.ops.registry import factor_op, reset_registry


def _df(rows: list[tuple]) -> pl.DataFrame:
    df = pl.DataFrame({
        "date": pl.Series([r[0] for r in rows], dtype=pl.Date),
        "code": [r[1] for r in rows],
        "close": [float(r[2]) for r in rows],
        "__factorlab_universe_active": [bool(r[3]) for r in rows],
    })
    return df


ISO = datetime.date


# ================================================================
# A. CS import alias numerical isolation（实际执行）
# ================================================================

def test_cs_import_alias_numerical_isolation():
    """`from polars_ta.prefix.wq import cs_rank as cs_r; signal = cs_r(close)`——
    alias 被 canonicalize 并 mask：A/B 与只有 A/B 的 baseline 一致（C 不污染）。
    注：无分区前缀的 alias（`as r`）是 expr_codegen 的平台限制（按名前缀分区，
    name[2] 越界）——非 masking 语义问题；带前缀 alias 是平台可执行形式。"""
    rows = [
        (ISO(2024, 1, 2), "A", 1.0, True),
        (ISO(2024, 1, 2), "B", 2.0, True),
        (ISO(2024, 1, 2), "C", 100.0, False),
    ]
    formula = "from polars_ta.prefix.wq import cs_rank as cs_r\nsignal = cs_r(close)"
    r = compute_formula(_df(rows), formula, universe_mask="__factorlab_universe_active")
    base = compute_formula(_df([x for x in rows if x[3]]),
                           "from polars_ta.prefix.wq import cs_rank as cs_r\nsignal = cs_r(close)")
    for c in ("A", "B"):
        v = r.filter(pl.col("code") == c)["signal"][0]
        b = base.filter(pl.col("code") == c)["signal"][0]
        assert v == b, f"{c}: alias masked {v} != baseline {b}（alias bypass masking）"


# ================================================================
# B. GP import alias transformer semantics
# ================================================================

def test_gp_import_alias_transformer():
    """`from factorlab.ops.platform_ops import group_rank as gr; signal = gr(industry, close)`——
    canonical=group_rank：group key 不 mask、数据参数 mask；**callable 名保持 alias 不改写**。"""
    formula = ("from factorlab.ops.platform_ops import group_rank as gr\n"
               "signal = gr(industry, close)")
    out = um.apply_universe_masking(formula, "__factorlab_universe_active")
    tree = ast.parse(out)
    gr_calls = [n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "gr"]
    assert len(gr_calls) == 1
    gp = gr_calls[0]
    assert gp.func.id == "gr"                            # callable 名保持 alias
    assert gp.args[0].id == "industry"                   # group key 不 mask
    assert isinstance(gp.args[1], ast.Call) and gp.args[1].func.id == "if_else"


# ================================================================
# C. registry alias canonical lookup
# ================================================================

def test_registry_alias_canonical_metadata():
    """factor_op(aliases=...) 注册的别名——metadata 经 canonical OperatorDef.name 查询。"""
    reset_registry()
    factor_op("cs_test", kind="cs", version="0.0.1", aliases=("test_alias",))(lambda x: x)
    try:
        um._CS_GP_MASK_ARGS["cs_test"] = (0,)   # canonical 名注册 metadata（测试内 monkeypatch）
        try:
            out = um.apply_universe_masking("signal = test_alias(close)",
                                            "__factorlab_universe_active")
            tree = ast.parse(out)
            calls = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "test_alias"]
            assert len(calls) == 1
            assert isinstance(calls[0].args[0], ast.Call) and calls[0].args[0].func.id == "if_else"
        finally:
            del um._CS_GP_MASK_ARGS["cs_test"]
    finally:
        reset_registry()


def test_registry_alias_unknown_canonical_fails():
    """alias 指向 canonical 无 metadata → fail fast（不因 alias 名误判）。"""
    reset_registry()
    factor_op("cs_test2", kind="cs", version="0.0.1", aliases=("test_alias2",))(lambda x: x)
    try:
        with pytest.raises(ValueError, match="cs_test2"):
            um.apply_universe_masking("signal = test_alias2(close)", "__factorlab_universe_active")
    finally:
        reset_registry()


# ================================================================
# D/E. CS / GP keyword fail-fast
# ================================================================

def test_cs_keyword_fails():
    with pytest.raises(ValueError, match="keyword arguments"):
        um.apply_universe_masking("signal = cs_rank(x=close)", "__factorlab_universe_active")


def test_gp_keyword_fails():
    with pytest.raises(ValueError, match="keyword arguments"):
        um.apply_universe_masking("signal = group_rank(key=industry, x=close)",
                                  "__factorlab_universe_active")


# ================================================================
# F. TS keyword unaffected
# ================================================================

def test_ts_keyword_unaffected():
    """TS operator 的 keyword 不被全局禁止（M6-03A 只限制 CS/GP）。"""
    out = um.apply_universe_masking("signal = ts_delay(close, d=1)", "__factorlab_universe_active")
    assert "ts_delay(close, d=1)" in out or "ts_delay" in out


# ================================================================
# G/H. reserved namespace
# ================================================================

def test_reserved_assignment_fails():
    with pytest.raises(ValueError, match="reserved internal name"):
        um.validate_reserved_bindings(
            "__factorlab_universe_active = True\nsignal = cs_rank(close)")


def test_reserved_annassign_fails():
    with pytest.raises(ValueError, match="reserved internal name"):
        um.validate_reserved_bindings(
            "__factorlab_universe_active: bool = True\nsignal = cs_rank(close)")


def test_reserved_function_name_fails():
    with pytest.raises(ValueError, match="reserved internal name"):
        um.validate_reserved_bindings(
            "def __factorlab_universe_active(x):\n    return x\nsignal = cs_rank(close)")


def test_reserved_argument_fails():
    with pytest.raises(ValueError, match="reserved internal name"):
        um.validate_reserved_bindings(
            "def foo(__factorlab_universe_active):\n    return 1\nsignal = cs_rank(close)")


def test_reserved_import_alias_fails():
    with pytest.raises(ValueError, match="reserved internal name"):
        um.validate_reserved_bindings(
            "from x import y as __factorlab_universe_active\nsignal = cs_rank(close)")


def test_reserved_via_compute_formula_path():
    """reserved 校验在真实 compute_formula 路径（macro/def 展开后）同样生效。"""
    df = _df([(ISO(2024, 1, 2), "A", 1.0, True)])
    with pytest.raises(ValueError, match="reserved internal name"):
        compute_formula(df, "__factorlab_universe_active = True\nsignal = cs_rank(close)",
                        universe_mask="__factorlab_universe_active")


# ================================================================
# I. normal formula unaffected
# ================================================================

def test_normal_formula_unaffected():
    out = um.apply_universe_masking("signal = cs_rank(close)", "__factorlab_universe_active")
    assert "if_else" in out
    um.validate_reserved_bindings("signal = cs_rank(close)")   # 无保留名 → 不抛


# ================================================================
# M6-03B：reserved binding completeness（destructuring / ClassDef）
# ================================================================

def test_reserved_tuple_destructuring_fails():
    with pytest.raises(ValueError, match="reserved internal name"):
        um.validate_reserved_bindings(
            "__factorlab_x, y = (1, 2)\nsignal = cs_rank(close)")


def test_reserved_nested_tuple_destructuring_fails():
    with pytest.raises(ValueError, match="reserved internal name"):
        um.validate_reserved_bindings(
            "a, (b, __factorlab_x) = (1, (2, 3))\nsignal = cs_rank(close)")


def test_reserved_list_destructuring_fails():
    with pytest.raises(ValueError, match="reserved internal name"):
        um.validate_reserved_bindings(
            "[a, __factorlab_y] = [1, 2]\nsignal = cs_rank(close)")


def test_reserved_classdef_fails():
    with pytest.raises(ValueError, match="reserved internal name"):
        um.validate_reserved_bindings(
            "class __factorlab_universe_active:\n    pass\nsignal = cs_rank(close)")


def test_normal_destructuring_not_rejected():
    """普通非 reserved destructuring 不被 validator 误伤（只测 validator contract）。"""
    um.validate_reserved_bindings("a, b = (1, 2)\nsignal = cs_rank(close)")
    um.validate_reserved_bindings("a, (b, c) = (1, (2, 3))\nsignal = cs_rank(close)")


def test_reserved_destructuring_real_compute_path():
    """真实 compute_formula(universe_mask=...) 路径同样 fail fast。"""
    df = _df([(ISO(2024, 1, 2), "A", 1.0, True)])
    with pytest.raises(ValueError, match="reserved internal name"):
        compute_formula(df, "__factorlab_x, y = (1, 2)\nsignal = cs_rank(close)",
                        universe_mask="__factorlab_universe_active")
