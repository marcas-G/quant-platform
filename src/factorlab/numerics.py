"""IEEE-754 Float64 ordering primitive（M6-07C2I）。

单一权威的 sign-aware 单调 bit 映射：同一数值（含 +0.0/-0.0）映射相同序值，
相邻可表示 float64 序差 1。QA comparator 与 stable rank 共同复用，
禁止两套不一致的 ULP 定义。
"""

from __future__ import annotations

import numpy as np

_U64_MASK = np.uint64(0x8000000000000000)


def float64_ordered_uint(x: np.ndarray) -> np.ndarray:
    """Float64 → uint64 单调序值（IEEE trick）。

    正数（含 +0.0）| sign-mask；负数 ~bits。+0.0 与 -0.0 映射到**相同**序值
    （0x8000000000000000）。同符号区间保序、跨符号正确。
    """
    bits = np.asarray(x, dtype=np.float64).view(np.uint64)
    return np.where(bits & _U64_MASK != 0, ~bits, bits | _U64_MASK)


def float64_ulp_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """向量化非负整数 ULP distance（a/b 同 shape finite float64 数组）。

    - 相同值（含 +0.0/-0.0）→ 0
    - 相邻可表示 float64 → 1
    - 无符号差值（oa>=ob 时 oa-ob 无回绕；否则反向）——避免 int64 溢出
    NaN/Inf 不保证（调用方应先过滤 finite）。
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    eq = (a == b) | ((a == 0.0) & (b == 0.0))
    oa, ob = float64_ordered_uint(a), float64_ordered_uint(b)
    d = np.where(oa >= ob, oa - ob, ob - oa)
    return np.where(eq, np.uint64(0), d)


def float64_ulp_distance_scalar(a: float, b: float) -> int:
    """标量 ULP distance（非负整数）。"""
    return int(float64_ulp_distance(np.array([a]), np.array([b]))[0])
