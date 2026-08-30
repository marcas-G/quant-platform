"""Float64 numeric determinism comparator（M6-07C2G）。

两层契约：
- STRUCTURAL_EXACT：schema/dtype/rows/keys/null/NaN/±Inf masks 严格相等。
- FLOAT_REDUCTION_EQUIVALENT：有限值对满足 ULP_DISTANCE <= max_ulp 且
  abs(a-b) <= scaled_eps * EPS_FLOAT64 * max(1, |a|, |b|)（AND Gate）。

ULP distance 为**非负整数**：由 factorlab.numerics 的单一权威 IEEE ordering
primitive 提供（sign-aware 单调 bit 映射；+0.0/-0.0 等价 ULP=0）。
NaN/Inf 不进入 finite comparator（单独分类）。

仅用于 validation/reproducibility 语义——不是 factor value transformation。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from factorlab.numerics import float64_ordered_uint, float64_ulp_distance

EPS_FLOAT64 = float(np.finfo(np.float64).eps)


def ulp_distance_array(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """向量化整数 ULP distance（a/b 同 shape 有限 float64 数组）。

    单一权威 primitive：factorlab.numerics.float64_ulp_distance（与 stable
    cs_rank 共享同一 IEEE ordering 定义——禁止两套 ULP）。
    """
    return float64_ulp_distance(a, b)


@dataclass(frozen=True)
class FloatComparison:
    """全量 finite 行数值比较结果（M6-07C2G）。"""

    rows: int                       # 双方 finite 且 key 匹配的总行数
    exact_mismatch_rows: int        # 位级不同行数（诊断指标，非 failure）
    max_ulp: int                    # 整数最大 ULP
    ulp_histogram: dict             # {ulp: count}（含 0）
    max_abs_diff: float
    max_scaled_eps: float           # abs(a-b) / (EPS*max(1,|a|,|b|)) 最大值
    scaled_violations: int          # scaled_eps > 阈值 的行数
    ulp_violations: int             # ULP > max_ulp 的行数
    violations: int = field(default=0)   # ulp + scaled 违规总数（AND Gate）

    @property
    def pass_contract(self) -> bool:
        return self.ulp_violations == 0 and self.scaled_violations == 0


def compare_float64_series(
    left: pl.Series,
    right: pl.Series,
    *,
    max_ulp: int = 4,
    scaled_eps: int = 8,
) -> FloatComparison:
    """全量（禁止抽样）比较两列同 key 对齐的 finite float64 值。

    仅对双方均 finite 的行做数值比较；NaN/Inf 由调用方单独做 structural
    mask 检查（本函数不吞掉它们——NaN/Inf 行不计入 rows）。
    """
    if left.len() != right.len():
        raise ValueError(f"series 长度不一致: {left.len()} vs {right.len()}")
    l = left.to_numpy()
    r = right.to_numpy()
    finite = np.isfinite(l) & np.isfinite(r)
    a, b = l[finite].astype(np.float64), r[finite].astype(np.float64)
    rows = int(a.size)
    if rows == 0:
        return FloatComparison(rows=0, exact_mismatch_rows=0, max_ulp=0,
                               ulp_histogram={"0": 0}, max_abs_diff=0.0,
                               max_scaled_eps=0.0, scaled_violations=0,
                               ulp_violations=0, violations=0)
    ulp = ulp_distance_array(a, b)
    abs_diff = np.abs(a - b)
    scale = np.maximum(np.maximum(np.abs(a), np.abs(b)), 1.0)
    scaled = abs_diff / (EPS_FLOAT64 * scale)
    # 直方图（整数 ULP 桶：0..max_ulp+1）
    capped = np.minimum(ulp, np.uint64(max_ulp + 1))
    hist = {str(int(k)): int(v) for k, v in
            zip(*np.unique(capped, return_counts=True))}
    hist.setdefault("0", 0)
    hist.setdefault(str(max_ulp + 1), 0)
    ulp_viol = int((ulp > max_ulp).sum())
    scaled_viol = int((scaled > scaled_eps).sum())
    return FloatComparison(
        rows=rows,
        exact_mismatch_rows=int((ulp > 0).sum()),
        max_ulp=int(ulp.max()) if rows else 0,
        ulp_histogram=hist,
        max_abs_diff=float(abs_diff.max()),
        max_scaled_eps=float(scaled.max()),
        scaled_violations=scaled_viol,
        ulp_violations=ulp_viol,
        violations=ulp_viol + scaled_viol,
    )
