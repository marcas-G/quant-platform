"""M6-07C2G：Float64 numeric determinism comparator 单元测试。"""

import numpy as np
import polars as pl

from factorlab.qa.numeric_determinism import (EPS_FLOAT64, compare_float64_series,
                                              ulp_distance_array)


def test_adjacent_float64_ulp_is_one():
    a = np.array([1.0])
    b = np.array([np.nextafter(1.0, 2.0)])
    assert ulp_distance_array(a, b)[0] == 1


def test_same_value_ulp_zero():
    assert ulp_distance_array(np.array([3.14]), np.array([3.14]))[0] == 0


def test_zero_sign_ulp_zero():
    """+0.0 与 -0.0 数值等价 → ULP=0（§4）。"""
    assert ulp_distance_array(np.array([0.0]), np.array([-0.0]))[0] == 0


def test_ulp_is_nonnegative_integer():
    a = np.linspace(-1e6, 1e6, 100000).astype(np.float64)
    b = np.nextafter(a, a + 1)
    d = ulp_distance_array(a, b)
    assert d.dtype == np.uint64
    assert (d <= 1).all()


def test_cross_sign_ordering():
    """跨符号单调：-max 与 +max 的距离为全范围（非溢出/回绕）。"""
    a = np.array([-np.finfo(np.float64).max, 0.0])
    b = np.array([np.finfo(np.float64).max, np.finfo(np.float64).max])
    d = ulp_distance_array(a, b)
    assert d[0] > 2 ** 62   # 全范围距离（无 int64 溢出/回绕）
    assert d[1] > 2 ** 62


def test_compare_series_all_exact():
    s = pl.Series(np.linspace(1.0, 100.0, 10000))
    c = compare_float64_series(s, s.clone())
    assert c.exact_mismatch_rows == 0
    assert c.max_ulp == 0
    assert c.pass_contract


def test_compare_series_small_ulp_passes():
    a = np.linspace(1.0, 100.0, 10000)
    b = np.nextafter(a, a + 1)
    c = compare_float64_series(pl.Series(a), pl.Series(b), max_ulp=4, scaled_eps=8)
    assert c.ulp_violations == 0
    assert c.scaled_violations == 0
    assert c.pass_contract


def test_compare_series_ulp_violation():
    a = np.linspace(1.0, 100.0, 100)
    b = np.nextafter(np.nextafter(np.nextafter(np.nextafter(np.nextafter(a, a + 1), a + 1), a + 1), a + 1), a + 1)
    c = compare_float64_series(pl.Series(a), pl.Series(b), max_ulp=4, scaled_eps=8)
    assert c.ulp_violations == 100
    assert not c.pass_contract


def test_compare_series_scaled_violation():
    """大相对差异 → scaled bound 违规（即使 ULP 检查是次要信号）。"""
    a = np.array([1.0])
    b = np.array([1.0 + 100 * EPS_FLOAT64])
    c = compare_float64_series(pl.Series(a), pl.Series(b), max_ulp=4, scaled_eps=8)
    assert c.scaled_violations == 1
    assert c.max_scaled_eps > 8.0
    assert not c.pass_contract


def test_compare_series_nan_inf_excluded():
    """NaN/Inf 不计入 finite comparator（structural mask 由调用方检查）。"""
    a = np.array([1.0, np.nan, np.inf, -np.inf])
    b = np.array([1.0, np.nan, np.inf, -np.inf])
    c = compare_float64_series(pl.Series(a), pl.Series(b))
    assert c.rows == 1   # 只有 1.0 是 finite
    assert c.exact_mismatch_rows == 0


def test_compare_series_length_mismatch_raises():
    import pytest
    with pytest.raises(ValueError, match="长度不一致"):
        compare_float64_series(pl.Series([1.0]), pl.Series([1.0, 2.0]))


# ================================================================
# M6-07C2J：signed-zero 压缩零映射
# ================================================================

from factorlab.numerics import float64_ordered_uint


def test_ordered_uint_signed_zero_identical():
    """+0.0 与 -0.0 的 ordered representation 真正相等（§1）。"""
    assert float64_ordered_uint(np.array([0.0]))[0] == \
        float64_ordered_uint(np.array([-0.0]))[0]


def test_zero_neighborhood_ulp():
    """ULP(-min_subnormal, ±0.0) = 1 且 ULP(±0.0, +min_subnormal) = 1（§2）。"""
    from factorlab.numerics import float64_ulp_distance
    mn = np.nextafter(0.0, 1.0)        # min positive subnormal
    nz = -0.0
    pz = 0.0
    assert float64_ulp_distance(np.array([-mn]), np.array([nz]))[0] == 1
    assert float64_ulp_distance(np.array([-mn]), np.array([pz]))[0] == 1
    assert float64_ulp_distance(np.array([nz]), np.array([mn]))[0] == 1
    assert float64_ulp_distance(np.array([pz]), np.array([mn]))[0] == 1


def test_ordered_uint_positive_adjacent_still_one():
    """压缩映射不破坏正数区间相邻性（+min_sub 与 +2min_sub 差 1）。"""
    mn = np.nextafter(0.0, 1.0)
    a, b = float64_ordered_uint(np.array([mn]))[0], \
        float64_ordered_uint(np.array([mn * 2]))[0]
    assert int(b) - int(a) == 1


def test_ordered_uint_negative_adjacent_still_one():
    mn = np.nextafter(0.0, 1.0)
    a, b = float64_ordered_uint(np.array([-mn * 2]))[0], \
        float64_ordered_uint(np.array([-mn]))[0]
    assert int(b) - int(a) == 1


def test_ulp_signed_zero_still_zero():
    """ULP(+0.0, -0.0) = 0（压缩映射本身保证，特判仅防御）。"""
    from factorlab.numerics import float64_ulp_distance
    assert float64_ulp_distance(np.array([0.0]), np.array([-0.0]))[0] == 0
