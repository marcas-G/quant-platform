"""M6-07C2I：stable cs_rank 单元测试（tie_ulps=4 默认；anchor 规则；routing）。"""

import datetime

import numpy as np
import polars as pl
import pytest

from factorlab.numerics import float64_ulp_distance_scalar
from factorlab.ops.stable_rank import (STABLE_RANK_MAX_ULPS, cs_stable_rank,
                                       rewrite_stable_rank, validate_tie_ulps)


def _df(x):
    return pl.DataFrame({"date": [datetime.date(2024, 1, 2)] * len(x),
                         "code": [f"{i:06d}" for i in range(len(x))],
                         "x": x})


def _run(x, pct=True, tie_ulps=STABLE_RANK_MAX_ULPS):
    return _df(x).with_columns(
        r=cs_stable_rank(pl.col("x"), pct, tie_ulps))["r"]


def _legacy(x, pct=True):
    s = pl.Series(x)
    if pct:
        r = s.rank(method="dense") - 1
        return r / max(r.max(), 1)
    return s.rank(method="dense")


# ---------------- tie_ulps validation ----------------

@pytest.mark.parametrize("bad", [-1, 1.5, True, "4", None])
def test_invalid_tie_ulps_rejected(bad):
    with pytest.raises(ValueError, match="tie_ulps"):
        validate_tie_ulps(bad)


def test_tie_ulps_zero_ok():
    validate_tie_ulps(0)


# ---------------- §26/27：legacy compatibility（gap>4 ULP 与 exact ties） ----------------

def test_gap_gt_4_ulp_matches_legacy():
    x = [1.0, 2.0, 3.0, 10.0, 100.0]
    assert _run(x).to_list() == pytest.approx(_legacy(x).to_list())
    assert _run(x, pct=False).to_list() == _legacy(x, pct=False).to_list()


def test_exact_ties_match_legacy():
    x = [1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 10.0]
    assert _run(x).to_list() == pytest.approx(_legacy(x).to_list())
    assert _run(x, pct=False).to_list() == _legacy(x, pct=False).to_list()


# ---------------- §28-31：ULP 边界 ----------------

def test_one_ulp_near_tie_merged():
    a = 1.0
    b = np.nextafter(1.0, 2.0)
    assert float64_ulp_distance_scalar(a, b) == 1
    out = _run([a, b, 2.0])
    # a/b 同 level；2.0 独立
    assert out[0] == out[1]
    assert out[2] != out[0]


def test_four_ulp_merged():
    a = 1.0
    b = np.nextafter(np.nextafter(np.nextafter(np.nextafter(1.0, 2.0), 2.0), 2.0), 2.0)
    assert float64_ulp_distance_scalar(a, b) == 4
    out = _run([a, b])
    assert out[0] == out[1]


def test_five_ulp_separate():
    a = 1.0
    b = np.nextafter(np.nextafter(np.nextafter(np.nextafter(np.nextafter(1.0, 2.0), 2.0), 2.0), 2.0), 2.0)
    assert float64_ulp_distance_scalar(a, b) == 5
    out = _run([a, b])
    assert out[0] != out[1]


def test_anti_chaining():
    """A、A+4、A+8 → [A,A+4] 同组、[A+8] 独立（anchor 规则，非传递合并）。"""
    a = 1.0
    b = np.nextafter(np.nextafter(np.nextafter(np.nextafter(1.0, 2.0), 2.0), 2.0), 2.0)   # +4
    c = np.nextafter(np.nextafter(np.nextafter(np.nextafter(np.nextafter(
        np.nextafter(np.nextafter(np.nextafter(1.0, 2.0), 2.0), 2.0), 2.0), 2.0), 2.0), 2.0), 2.0)  # +8
    out = _run([a, b, c])
    assert out[0] == out[1]          # A 与 A+4 同组
    assert out[2] != out[0]          # A+8 独立


# ---------------- §32：C2H 精确复现 ----------------

def test_c2h_tie_pair_reproduction():
    """8.755999885890212 / 8.755999885890214：ULP=1 → stable 同 level。"""
    a, b = 8.755999885890212, 8.755999885890214
    assert float64_ulp_distance_scalar(a, b) == 1
    out = _run([a, b])
    assert out[0] == out[1]
    # tie_ulps=0 → legacy 拆分
    out0 = _run([a, b], tie_ulps=0)
    assert out0[0] != out0[1]


def test_c2h_denominator_stable():
    """近 tie 对 + 大量 unique 值：denominator 不因假拆分变化。"""
    xs = list(np.linspace(0.0, 100.0, 100)) + [8.755999885890212, 8.755999885890214]
    out = _run(xs)
    k = int(out.max() * 100)  # pct normalized；max=1（K>1）
    assert out.max() == pytest.approx(1.0)
    # 与 legacy 比：legacy 会拆分 → 2 个 level；stable 合并
    n_legacy = len(set(_legacy(xs).to_list()))
    n_stable = len(set(out.to_list()))
    assert n_stable == n_legacy - 1


# ---------------- §14/21/24：zero/null/nonfloat/pct=False ----------------

def test_zero_sign_same_group():
    out = _run([0.0, -0.0, 1.0])
    assert out[0] == out[1]


def test_null_preserved():
    out = _run([None, 1.0, 2.0])
    assert out[0] is None
    assert out[1] == 0.0 and out[2] == 1.0


def test_non_float_exact_tie():
    """Int 输入不 fuzzy（1、1 同组；与 legacy 一致）。"""
    out = _run([1, 1, 2, 3])
    assert out[0] == out[1]


def test_pct_false_dense_integer():
    out = _run([1.0, 1.0, 2.0, 3.0], pct=False)
    assert out.dtype == pl.UInt32
    assert out.to_list() == [1, 1, 2, 3]


def test_pct_false_near_tie_shared():
    a, b = 1.0, np.nextafter(1.0, 2.0)
    out = _run([a, b, 2.0], pct=False)
    assert out[0] == out[1] == 1
    assert out[2] == 2


def test_nan_behavior():
    """NaN → null（与 vendor rank 的 NaN→null 语义一致，characterized）。"""
    out = _run([float("nan"), 1.0, 2.0])
    assert out[0] is None
    assert out[1] == 0.0


def test_inf_ordering():
    """-inf/有限/+inf 各自独立 dense level（pct 归一化 [0, 0.5, 1]）。"""
    out = _run([-float("inf"), 1.0, float("inf")])
    assert out[0] == 0.0 and out[1] == 0.5 and out[2] == 1.0


# ---------------- §33/15：真实 compute_formula 路径 ----------------

def test_compute_formula_uses_stable_implementation():
    from factorlab.engine.compute import compute_formula
    df = _df([1.0, np.nextafter(1.0, 2.0), 5.0])
    # rewrite 在 compute_formula 内生效
    out1 = compute_formula(df, "signal = cs_rank(x)")
    out2 = compute_formula(df, "signal = cs_rank(x, True, 0)")
    # stable（默认 4 ULP）：1.0 与 nextafter 同 level → 值 0/0/1
    assert out1["signal"].to_list() == pytest.approx([0.0, 0.0, 1.0])
    # legacy（0 ULP）：拆开 → 0/0.5/1
    assert out2["signal"].to_list() == pytest.approx([0.0, 0.5, 1.0])


def test_alias_cannot_bypass_stable_rank():
    from factorlab.engine.compute import compute_formula
    df = _df([1.0, np.nextafter(1.0, 2.0), 5.0])
    out = compute_formula(df, "from polars_ta.prefix.wq import cs_rank as r\nsignal = r(x)")
    assert out["signal"].to_list() == pytest.approx([0.0, 0.0, 1.0])  # stable 生效


def test_user_defined_cs_rank_precedence():
    from factorlab.engine.compute import compute_formula
    df = _df([1.0, 2.0, 5.0])
    out = compute_formula(df, "def cs_rank(x):\n    return x * 2\nsignal = cs_rank(x)")
    assert out["signal"].to_list() == pytest.approx([2.0, 4.0, 10.0])


def test_rewrite_idempotent():
    src = rewrite_stable_rank("signal = cs_rank(x)")
    assert rewrite_stable_rank(src) == src


# ---------------- §34：row-order independent ----------------

def test_group_anchor_from_sorted_order_not_row_order():
    """同一 (code, value) 映射、不同输入行序 → (code→rank) 必须相同。"""
    a, b = 1.0, np.nextafter(1.0, 2.0)
    rows1 = [("A", a), ("B", b), ("C", 5.0)]
    rows2 = [("B", b), ("C", 5.0), ("A", a)]   # 行序 shuffle，code 跟随值
    df1 = pl.DataFrame({"code": [r[0] for r in rows1], "x": [r[1] for r in rows1]})
    df2 = pl.DataFrame({"code": [r[0] for r in rows2], "x": [r[1] for r in rows2]})
    m1 = dict(zip(df1["code"].to_list(),
                  df1.with_columns(r=cs_stable_rank(pl.col("x")))["r"].to_list()))
    m2 = dict(zip(df2["code"].to_list(),
                  df2.with_columns(r=cs_stable_rank(pl.col("x")))["r"].to_list()))
    assert m1 == m2
