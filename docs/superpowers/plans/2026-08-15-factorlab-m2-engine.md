# FactorLab M2 引擎与算子适配实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 M1 基础上接入 `polars_ta` 算子族、建立 TS/CS/GP 分区校验和防未来函数断言，使 `factorlab` 能正确运行更多 WorldQuant 风格因子表达式。

**Architecture:** 算子数值实现来自 `polars_ta`；平台注册表负责别名和薄封装。`engine/partitions.py` 在 `expr_codegen` 执行前做静态 AST 校验；`expr_codegen` 继续负责实际分组与代码生成。

**Tech Stack:** Python 3.13、Polars、polars_ta、expr_codegen、pytest。

**Spec:** `docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md`

## Global Constraints

- Python 3.13，包结构 `src/factorlab`。
- 依赖：`polars>=1.38`、`polars-ta>=0.5.17`、`expr-codegen>=0.16.6`。
- 不修改 `C:\Users\ThinkPad\quant-data`。
- 所有测试用 pytest，`pythonpath = ["src"]`。
- 所有算子最终返回 `pl.Expr`，并声明 `el | ts | cs | gp | ta` 类别。
- 任何 PR 必须同时包含实现、接口文档和测试。

## File Structure

- `src/factorlab/ops/polars_ta_wrappers.py`：注册 `polars_ta` 的 `wq/ta/tdx` 算子。
- `src/factorlab/ops/platform_ops.py`：`returns/vwap/adv20` 与分组算子薄封装。
- `src/factorlab/engine/partitions.py`：AST 分区校验与负 lookback 检查。
- `src/factorlab/engine/compute.py`：接入分区校验。
- `docs/interface.md`：补充算子清单和分区规则。

---

### Task 1: 注册 polars_ta 算子族

**Files:**
- Create: `src/factorlab/ops/polars_ta_wrappers.py`
- Test: `tests/test_polars_ta_wrappers.py`

**Interfaces:**
- Produces: `register_polars_ta_ops() -> None`；调用后 `registry.get_op("ts_mean")`、`registry.get_op("cs_rank")` 等可用。

- [ ] **Step 1: Write the failing test**

Create `tests/test_polars_ta_wrappers.py`:

```python
from factorlab.ops import registry
from factorlab.ops.polars_ta_wrappers import register_polars_ta_ops


def test_registers_core_wq_operators():
    registry.reset_registry()
    register_polars_ta_ops()
    for name in ("ts_mean", "ts_std_dev", "ts_sum", "ts_delay", "cs_rank", "cs_zscore"):
        assert registry.get_op(name).kind in {"ts", "cs"}


def test_registers_ta_family_operators():
    registry.reset_registry()
    register_polars_ta_ops()
    assert registry.get_op("ts_RSI").kind == "ta"
    assert registry.get_op("ts_ATR").kind == "ta"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_polars_ta_wrappers.py -v`
Expected: FAIL，原因是模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/ops/polars_ta_wrappers.py`:

```python
from polars_ta.prefix import ta, tdx, wq

from factorlab.ops.registry import factor_op


_WQ_TS = (
    "ts_delay", "ts_delta", "ts_mean", "ts_std_dev", "ts_sum", "ts_product",
    "ts_min", "ts_max", "ts_median", "ts_rank", "ts_zscore",
    "ts_corr", "ts_covariance", "ts_skewness", "ts_kurtosis",
)

_WQ_CS = (
    "cs_rank", "cs_zscore", "cs_demean", "cs_scale", "cs_quantile",
    "cs_mad_zscore", "cs_regression_resid",
)

_TA_NAMES = ("ts_RSI", "ts_ATR", "ts_CCI", "ts_MACD", "ts_WILLR", "ts_TRIX")
_TDX_NAMES = ("ts_BIAS", "ts_KDJ", "ts_BOLL", "ts_RSV")


def register_polars_ta_ops() -> None:
    for name in _WQ_TS:
        factor_op(name, kind="ts", version="0.1.0")(getattr(wq, name))
    for name in _WQ_CS:
        factor_op(name, kind="cs", version="0.1.0")(getattr(wq, name))
    for name in _TA_NAMES:
        factor_op(name, kind="ta", version="0.1.0")(getattr(ta, name))
    for name in _TDX_NAMES:
        factor_op(name, kind="ta", version="0.1.0")(getattr(tdx, name))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_polars_ta_wrappers.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/ops/polars_ta_wrappers.py tests/test_polars_ta_wrappers.py
git commit -m "feat: register polars_ta operator families"
```

---

### Task 2: 平台算子薄封装

**Files:**
- Create: `src/factorlab/ops/platform_ops.py`
- Test: `tests/test_platform_ops.py`

**Interfaces:**
- Produces: `returns(close)`、`vwap(high, low, close, volume)`、`adv20(volume)`、`group_rank(key, x)`、`group_mean(key, x)`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_platform_ops.py`:

```python
import polars as pl

from factorlab.ops.platform_ops import returns, vwap, adv20, group_rank


def test_platform_ops_return_expr():
    assert isinstance(returns(pl.col("close")), pl.Expr)
    assert isinstance(vwap(pl.col("high"), pl.col("low"), pl.col("close"), pl.col("volume")), pl.Expr)
    assert isinstance(adv20(pl.col("volume")), pl.Expr)
    assert isinstance(group_rank(pl.col("industry"), pl.col("close")), pl.Expr)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_platform_ops.py -v`
Expected: FAIL，原因是模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/ops/platform_ops.py`:

```python
import polars as pl


def returns(close: pl.Expr) -> pl.Expr:
    return close / close.shift(1) - 1


def vwap(high: pl.Expr, low: pl.Expr, close: pl.Expr, volume: pl.Expr) -> pl.Expr:
    typical = (high + low + close) / 3
    return (typical * volume).cum_sum() / volume.cum_sum()


def adv20(volume: pl.Expr) -> pl.Expr:
    return volume.rolling_mean(window_size=20)


def group_rank(key: pl.Expr, x: pl.Expr) -> pl.Expr:
    return x.rank().over(key)


def group_mean(key: pl.Expr, x: pl.Expr) -> pl.Expr:
    return x.mean().over(key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_platform_ops.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/ops/platform_ops.py tests/test_platform_ops.py
git commit -m "feat: add platform operator thin wrappers"
```

---

### Task 3: TS/CS/GP 分区与防未来函数校验

**Files:**
- Create: `src/factorlab/engine/partitions.py`
- Test: `tests/test_partitions.py`

**Interfaces:**
- Produces: `validate_partition_calls(source: str) -> None`；`reject_future_shifts(source: str) -> None`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_partitions.py`:

```python
import pytest

from factorlab.engine.partitions import reject_future_shifts, validate_partition_calls


def test_allows_known_prefixed_calls():
    validate_partition_calls("signal = ts_mean(close, 20) + cs_rank(close)")


def test_rejects_unknown_operator():
    with pytest.raises(ValueError):
        validate_partition_calls("signal = not_real_operator(close)")


def test_rejects_negative_delay():
    with pytest.raises(ValueError):
        reject_future_shifts("signal = ts_delay(close, -1)")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_partitions.py -v`
Expected: FAIL，原因是模块不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/engine/partitions.py`:

```python
from __future__ import annotations

import ast

from factorlab.factor.errors import FactorDSLError
from factorlab.ops import registry


def _call_names(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            yield node


def validate_partition_calls(source: str) -> None:
    tree = ast.parse(source)
    for node in _call_names(tree):
        name = node.func.id
        if name not in registry._REGISTRY and name not in registry._ALIASES:
            raise FactorDSLError(f"未知算子: {name}", node.lineno, node.col_offset)


def reject_future_shifts(source: str) -> None:
    tree = ast.parse(source)
    for node in _call_names(tree):
        if node.func.id in {"ts_delay", "ts_delta"} and len(node.args) >= 2:
            shift = node.args[1]
            if isinstance(shift, ast.UnaryOp) and isinstance(shift.op, ast.USub):
                raise FactorDSLError("禁止负 lookback", node.lineno, node.col_offset)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_partitions.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/engine/partitions.py tests/test_partitions.py
git commit -m "feat: add partition and lookback validation"
```

---

### Task 4: 接入 compute_formula

**Files:**
- Modify: `src/factorlab/engine/compute.py`
- Test: `tests/test_compute.py`

**Interfaces:**
- Consumes: `validate_partition_calls`、`reject_future_shifts`。

- [ ] **Step 1: Write the failing test**

Add to `tests/test_compute.py`:

```python
def test_compute_rejects_unknown_operator():
    with pytest.raises(ValueError):
        compute_formula(pl.DataFrame({"date": [], "code": [], "close": []}), "signal = nope(close)")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compute.py::test_compute_rejects_unknown_operator -v`
Expected: FAIL，因为当前 compute_formula 只做 AST 白名单。

- [ ] **Step 3: Write minimal implementation**

Modify `src/factorlab/engine/compute.py`:

```python
from factorlab.engine.partitions import reject_future_shifts, validate_partition_calls


def compute_formula(df, formula, asset="code", date="date"):
    validate_formula(formula)
    validate_partition_calls(formula)
    reject_future_shifts(formula)
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_compute.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/engine/compute.py tests/test_compute.py
git commit -m "feat: wire partition checks into compute path"
```

---

### Task 5: M2 接口文档更新

**Files:**
- Modify: `docs/interface.md`

- [ ] **Step 1: Update operator and partition documentation**

Add a subsection under `## 3. 因子脚本`:

```markdown
### 分区与 lookback

- `ts_*` 按 asset 排序并只使用历史窗口。
- `cs_*` 按 date 分组。
- `gp_*` 按 date + group key 分组。
- `ts_delay(x, n)` 和 `ts_delta(x, n)` 的 `n` 不能为负数。
- 未知算子会在执行前被拒绝。
```

- [ ] **Step 2: Verify docs and full tests**

Run:
```powershell
python -m pytest -q
```
Expected: 全部 PASS。

- [ ] **Step 3: Commit**

```bash
git add docs/interface.md
git commit -m "docs: document M2 partition rules"
```

---

## Self-Review

- Spec coverage: 覆盖 spec 的 `polars_ta 算子适配/别名`、`TS/CS/GP 分区验证`、`防未来函数断言`。
- Placeholder scan: 无 TODO/TBD。
- Type consistency: `register_polars_ta_ops`、`returns/vwap/adv20/group_rank/group_mean`、`validate_partition_calls/reject_future_shifts` 在任务间一致。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-15-factorlab-m2-engine.md`. Two execution options:

1. Subagent-Driven (recommended)
2. Inline Execution

Which approach?
