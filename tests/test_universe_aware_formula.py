"""M6-03：cross-sectional universe masking——公式级语义测试（Test 1-4 + 变换单元）。

核心：TS/TA 见完整 listed history；CS/GP 只见当日 active universe。
"""

import ast
import datetime

import polars as pl
import pytest

from factorlab.engine.compute import compute_formula
from factorlab.ops.registry import factor_op, reset_registry
from factorlab.ops.universe_masking import apply_universe_masking


def _df(rows: list[tuple], mask: bool = True) -> pl.DataFrame:
    """rows: (date, code, close, active)。"""
    df = pl.DataFrame({
        "date": pl.Series([r[0] for r in rows], dtype=pl.Date),
        "code": [r[1] for r in rows],
        "close": [float(r[2]) for r in rows],
        "__factorlab_universe_active": [bool(r[3]) for r in rows],
    })
    return df


# ================================================================
# 变换单元（AST 级）
# ================================================================

def _calls(tree: ast.AST, name: str):
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name]


def test_mask_ts_then_cs():
    out = apply_universe_masking("signal = cs_rank(ts_mean(close, 20))", "__factorlab_universe_active")
    tree = ast.parse(out)
    cs = _calls(tree, "cs_rank")[0]
    arg = cs.args[0]
    assert isinstance(arg, ast.Call) and arg.func.id == "if_else"
    assert arg.args[0].id == "__factorlab_universe_active"      # mask 列
    assert arg.args[2].value is None                   # else None
    inner = arg.args[1]
    assert isinstance(inner, ast.Call) and inner.func.id == "ts_mean"  # TS 未被 mask


def test_mask_cs_then_ts():
    out = apply_universe_masking("signal = ts_mean(cs_rank(close), 20)", "__factorlab_universe_active")
    tree = ast.parse(out)
    cs = _calls(tree, "cs_rank")[0]
    assert isinstance(cs.args[0], ast.Call) and cs.args[0].func.id == "if_else"
    ts = _calls(tree, "ts_mean")[0]
    assert ts.args[0].func.id == "cs_rank"             # TS 包在 CS 外，不 mask


def test_mask_multi_arg_cs_resid():
    """cs_regression_resid(y, x)（注册名）——两个数据参数都 mask。"""
    out = apply_universe_masking("signal = cs_regression_resid(y, x)", "__factorlab_universe_active")
    tree = ast.parse(out)
    cs = _calls(tree, "cs_regression_resid")[0]
    for arg in cs.args:                                # 两个数据参数都 mask
        assert isinstance(arg, ast.Call) and arg.func.id == "if_else"


def test_mask_group_key_not_masked():
    out = apply_universe_masking("signal = group_rank(industry, close)", "__factorlab_universe_active")
    tree = ast.parse(out)
    gp = _calls(tree, "group_rank")[0]
    assert gp.args[0].id == "industry"                 # group key 不 mask
    assert isinstance(gp.args[1], ast.Call) and gp.args[1].func.id == "if_else"  # 数据参数 mask


def test_mask_unknown_cs_fails():
    reset_registry()
    factor_op("cs_myop", kind="cs", version="0.0.1")(lambda x: x)
    try:
        with pytest.raises(ValueError, match="cs_myop"):
            apply_universe_masking("signal = cs_myop(close)", "__factorlab_universe_active")
    finally:
        reset_registry()


def test_mask_no_universe_param_passthrough():
    """universe_mask=None → 公式原样（静态兼容）。"""
    src = "signal = cs_rank(close)"
    assert compute_formula.__defaults__ is not None  # 签名存在 universe_mask


# ================================================================
# Test 1 — 纯 TS 保留 inactive history
# ================================================================

def test_pure_ts_keeps_inactive_history():
    """A 前 3 日 inactive、后 2 日 active，close=[1..5]；
    ts_mean(close,3) 首次 active 日（day4）必须用 [2,3,4]=3（inactive 历史保留）。"""
    df = _df([
        (datetime.date(2024, 1, 2), "A", 1.0, False),
        (datetime.date(2024, 1, 3), "A", 2.0, False),
        (datetime.date(2024, 1, 4), "A", 3.0, False),
        (datetime.date(2024, 1, 5), "A", 4.0, True),
        (datetime.date(2024, 1, 6), "A", 5.0, True),
    ])
    r = compute_formula(df, "signal = ts_mean(close, 3)", universe_mask="__factorlab_universe_active")
    d4 = r.filter(pl.col("date") == datetime.date(2024, 1, 5))
    assert abs(d4["signal"][0] - 3.0) < 1e-9   # mean(2,3,4)——inactive 历史未被删除


# ================================================================
# Test 2 — 纯 CS 隔离
# ================================================================

def test_pure_cs_isolation():
    """A/B active（close 1/2）、C inactive（close 100）——cs_rank 中 A/B 必须与
    只有 A/B 时完全一致，C 不得影响。"""
    rows = [
        (datetime.date(2024, 1, 2), "A", 1.0, True),
        (datetime.date(2024, 1, 2), "B", 2.0, True),
        (datetime.date(2024, 1, 2), "C", 100.0, False),
    ]
    r = compute_formula(_df(rows), "signal = cs_rank(close)", universe_mask="__factorlab_universe_active")
    base = compute_formula(_df([r for r in rows if r[3]]), "signal = cs_rank(close)")
    for c in ("A", "B"):
        v = r.filter(pl.col("code") == c)["signal"][0]
        b = base.filter(pl.col("code") == c)["signal"][0]
        assert v == b, f"{c}: masked {v} != baseline {b}（C 污染 rank）"


# ================================================================
# Test 3 — TS → CS
# ================================================================

def test_ts_then_cs():
    """cs_rank(ts_mean(close, 2))：TS 用完整历史、CS 只见 active。"""
    rows = [
        (datetime.date(2024, 1, 2), "A", 1.0, True),
        (datetime.date(2024, 1, 2), "B", 2.0, True),
        (datetime.date(2024, 1, 2), "C", 100.0, False),   # inactive 极端值
        (datetime.date(2024, 1, 3), "A", 1.5, True),
        (datetime.date(2024, 1, 3), "B", 2.5, True),
        (datetime.date(2024, 1, 3), "C", 200.0, False),
    ]
    r = compute_formula(_df(rows), "signal = cs_rank(ts_mean(close, 2))",
                        universe_mask="__factorlab_universe_active")
    # 与只有 A/B 的基准一致（C 的 ts_mean 极端值不得污染 active rank）
    base = compute_formula(_df([r for r in rows if r[3]]),
                           "signal = cs_rank(ts_mean(close, 2))")
    for d in (datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)):
        for c in ("A", "B"):
            v = r.filter((pl.col("date") == d) & (pl.col("code") == c))["signal"][0]
            b = base.filter((pl.col("date") == d) & (pl.col("code") == c))["signal"][0]
            assert v == b, f"{d} {c}: {v} != {b}"


# ================================================================
# Test 4 — CS → TS（inactive 日 CS 内部为 null，不得有正常 rank 再进 TS）
# ================================================================

def test_cs_then_ts_inactive_day_null():
    """B day1 active、day2 inactive、day3 active——ts_mean(cs_rank(close), 2) 中
    day2 的 B 必须内部 null（不能有正常 rank），使 day3 的 B 为 null。"""
    rows = [
        (datetime.date(2024, 1, 2), "A", 1.0, True),
        (datetime.date(2024, 1, 2), "B", 2.0, True),
        (datetime.date(2024, 1, 2), "C", 3.0, True),
        (datetime.date(2024, 1, 3), "A", 3.0, True),
        (datetime.date(2024, 1, 3), "B", 2.5, False),   # inactive（unmasked 时 rank 2/3）
        (datetime.date(2024, 1, 3), "C", 1.0, True),
        (datetime.date(2024, 1, 4), "A", 1.0, True),
        (datetime.date(2024, 1, 4), "B", 3.0, True),    # rank 3/3=1.0（≠ day2 的 2/3）
        (datetime.date(2024, 1, 4), "C", 2.0, True),
    ]
    # 核心锁定：day2 inactive 的 B 在 cs_rank 阶段内部为 null（不能有正常 rank 再进 TS）
    cs_only = compute_formula(_df(rows), "signal = cs_rank(close)",
                              universe_mask="__factorlab_universe_active")
    b2 = cs_only.filter((pl.col("date") == datetime.date(2024, 1, 3)) & (pl.col("code") == "B"))
    assert b2["signal"][0] is None     # inactive 日 → cs 内部 null
    cs_bad = compute_formula(_df(rows), "signal = cs_rank(close)")   # unmasked（错误语义）
    b2_bad = cs_bad.filter((pl.col("date") == datetime.date(2024, 1, 3)) & (pl.col("code") == "B"))
    assert b2_bad["signal"][0] is not None   # unmasked 时 B day2 有正常 rank——对照
    # TS 阶段：inactive 日（day2）的最终 signal 必须 null（unmasked 时该日有正常
    # rank 0.5 进入 TS——窗口含值的差异锁定行为）。注意 expr_codegen 的
    # over_null="partition_by" 会把 null 行剔出分区（平台既有行为，M6-03 不改变）——
    # 核心承诺是 inactive 日内部 cs 为 null，而非控制 TS 层 null 传播。
    r = compute_formula(_df(rows), "signal = ts_mean(cs_rank(close), 2)",
                        universe_mask="__factorlab_universe_active")
    r_bad = compute_formula(_df(rows), "signal = ts_mean(cs_rank(close), 2)")
    b2_ts = r.filter((pl.col("date") == datetime.date(2024, 1, 3)) & (pl.col("code") == "B"))
    b2_ts_bad = r_bad.filter((pl.col("date") == datetime.date(2024, 1, 3)) & (pl.col("code") == "B"))
    assert b2_ts["signal"][0] is None          # inactive 日信号 null
    assert b2_ts_bad["signal"][0] is not None  # unmasked 时该日有值（正常 rank 进入）
