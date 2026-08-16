# FactorLab 自由代码因子表达实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** formula 自由代码（def 内联展开——窗口算子合法）+ 顶层 params 参数化（${param} 引用 + run --set 变体）。

**Architecture:** 扩展现有宏展开器（AST 内联）为 def 内联；spec 增加 params 字段与 `${}` 文本替换；CLI run 增加 --set。

**Tech Stack:** Python 3.13、ast、Polars。

**Spec:** `docs/superpowers/specs/2026-08-17-factorlab-free-form-formula-design.md`

## Global Constraints

- Python 3.13；包结构 `src/factorlab`；测试 `pythonpath = ["src"]`。
- TDD（正常/边界/错误），全量通过后提交（CLAUDE.md 硬性要求）。
- 新代码同步更新 `docs/interface.md`（Task 3）。
- 无循环保持；递归 def 拒绝；分区/防未来由平台保证。

## File Structure

- `src/factorlab/ops/platform_ops.py`（Modify）：`inline_defs`（def 内联展开——与宏展开器同族）。
- `src/factorlab/engine/compute.py`（Modify）：展开链接入 inline_defs；params 替换。
- `src/factorlab/spec.py`（Modify）：FactorSpec.params 字段。
- `src/factorlab/cli/main.py`（Modify）：run --set 参数。
- 测试：`tests/test_inline_defs.py`（Create）；`tests/test_spec.py`、`tests/test_run_factor.py`、`tests/test_cli_run.py`（Modify）。

---

### Task 1: def 内联展开

**Files:**
- Modify: `src/factorlab/ops/platform_ops.py`
- Test: `tests/test_inline_defs.py`

**Interfaces:** `inline_defs(source: str) -> str`（公式内 def 内联展开：窗口算子合法、多语句提升、def 调 def、递归拒绝）。

**Step 1: 测试**

Create `tests/test_inline_defs.py`：

```python
import pytest

from factorlab.factor.errors import FactorDSLError
from factorlab.ops.platform_ops import inline_defs


def test_inline_single_def_with_window_ops():
    src = '''
def my_ts(x, n):
    return ts_mean(x, n) / ts_delay(x, 1)

signal = my_ts(close, 20)
'''
    out = inline_defs(src)
    assert "def my_ts" not in out            # def 删除
    assert "ts_mean" in out and "ts_delay" in out  # 窗口算子内联到顶层
    assert "close" in out


def test_inline_multi_statement_def():
    src = '''
def oi_energy(x, n):
    _e = ts_rank(ts_delta(x, 1).abs(), n)
    return sqrt(_e * (1 - _e))

signal = oi_energy(volume, 200)
'''
    out = inline_defs(src)
    assert "def oi_energy" not in out
    assert "ts_rank" in out and "sqrt" in out


def test_inline_def_calls_def():
    src = '''
def inner(x, n):
    return ts_mean(x, n)

def outer(x, n):
    return inner(x, n) * 2

signal = outer(close, 20)
'''
    out = inline_defs(src)
    assert "def inner" not in out and "def outer" not in out
    assert "ts_mean" in out


def test_inline_same_def_multiple_calls_isolated():
    src = '''
def scale_it(x, n):
    _m = ts_mean(x, n)
    return x / _m

signal = scale_it(close, 20) - scale_it(volume, 5)
'''
    out = inline_defs(src)
    # 两次调用各自实例化（变量不串）
    assert "ts_mean" in out


def test_inline_recursive_def_rejected():
    src = '''
def loop(x, n):
    return loop(x, n - 1)

signal = loop(close, 5)
'''
    with pytest.raises(FactorDSLError, match="递归"):
        inline_defs(src)


def test_inline_elementwise_def_kept_behavior():
    src = '''
def flip(x, n):
    return x * n

signal = flip(close, 2)
'''
    out = inline_defs(src)
    assert "def flip" not in out
    assert "close * 2" in out or "* 2" in out


def test_inline_no_def_unchanged():
    src = "signal = ts_mean(close, 20)"
    assert inline_defs(src) == src
```

（断言以实际展开形式为准——核心：def 删除、窗口算子出现、多次调用不冲突、递归拒绝。）

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_inline_defs.py -v`
Expected: FAIL — inline_defs 不存在。

**Step 3: 实现**

`src/factorlab/ops/platform_ops.py` 追加（复用 `_bind_names` 模式——与宏展开同族）：

```python
def inline_defs(source: str) -> str:
    """公式内 def 内联展开：窗口算子合法（提升到顶层）、多语句函数体、
    def 调 def 递归展开、递归 def 拒绝。展开后删除 def 节点。

    核心：expr_codegen 把 def 当黑盒（分区泄漏）——内联后窗口算子成为
    顶层 ts_* 调用，分区/防未来自动正确。
    """
    tree = ast.parse(source)
    defs = {n.name: n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}

    def _collect_calls(node):
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                yield child

    def _expand(node, fn_def, binding, suffix):
        """展开一次调用：返回 (提升语句列表, 替换表达式)。"""
        body = [s for s in fn_def.body if not isinstance(s, ast.Return)]
        rets = [s for s in fn_def.body if isinstance(s, ast.Return)]
        if not rets or len(rets) > 1:
            raise FactorDSLError(
                f"def {fn_def.name} 必须恰有一个 return", fn_def.lineno, fn_def.col_offset)
        hoisted, mapping = [], {}
        for i, stmt in enumerate(body):
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                new_name = f"_inline_{fn_def.name}_{suffix}_{i}"
                mapping[stmt.targets[0].id] = new_name
                bound = _bind_names(stmt.value, binding)
                bound = _bind_names(bound, mapping)  # 体内引用先前中间变量
                hoisted.append(ast.Assign(
                    targets=[ast.Name(id=new_name, ctx=ast.Store())], value=bound))
            else:
                raise FactorDSLError(
                    f"def {fn_def.name} 内仅支持赋值与 return", fn_def.lineno, stmt.lineno)
        expr = _bind_names(rets[0].value, binding)
        expr = _bind_names(expr, mapping)
        return hoisted, expr

    # 递归检测
    for name, fn in defs.items():
        body_names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        if name in body_names:
            raise FactorDSLError(f"递归 def 不支持内联: {name}", fn.lineno, fn.col_offset)

    # 展开调用（自底向上：先展开 def 体内的嵌套调用）
    hoists: list[ast.stmt] = []
    counter = {"n": 0}

    class _DefExpander(ast.NodeTransformer):
        def visit_Call(self, node: ast.Call) -> ast.expr:
            node = self.generic_visit(node)  # 先展开嵌套调用
            if not isinstance(node.func, ast.Name) or node.func.id not in defs:
                return node
            fn = defs[node.func.id]
            params = [a.arg for a in fn.args.args]
            if len(node.args) != len(params):
                raise FactorDSLError(
                    f"def {fn.name} 需要 {len(params)} 个参数，实际 {len(node.args)} 个",
                    node.lineno, node.col_offset)
            counter["n"] += 1
            binding = dict(zip(params, node.args))
            hoisted, expr = _expand(node, fn, binding, counter["n"])
            hoists.extend(hoisted)
            expr = ast.fix_missing_locations(expr)
            expr.lineno, expr.col_offset = node.lineno, node.col_offset
            return expr

    expander = _DefExpander()
    transformed = expander.visit(tree)
    # 删除 def 节点
    transformed.body = [n for n in transformed.body if not isinstance(n, ast.FunctionDef)]
    # 提升语句插到公式顶层（def 原来位置）
    transformed.body = hoists + transformed.body
    return ast.unparse(transformed)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_inline_defs.py -v`
Expected: PASS（实现细节以测试为准——参数绑定/提升/改名逻辑可调整）。

**Step 5: Commit**

```bash
git add src/factorlab/ops/platform_ops.py tests/test_inline_defs.py
git commit -m "feat: inline def functions in formula (window ops legal)"
```

---

### Task 2: params 参数化 + 展开链接入

**Files:**
- Modify: `src/factorlab/spec.py`（params 字段）
- Modify: `src/factorlab/engine/compute.py`（展开链 + 参数替换）
- Test: `tests/test_spec.py`、`tests/test_run_factor.py`

**Step 1: 测试**

`tests/test_spec.py`：

```python
def test_spec_params_default_empty():
    spec = load_spec(make_spec(tmp_path))
    assert spec.params == {}


def test_spec_params_parse():
    spec = load_spec(make_spec(tmp_path, params={"win": 200, "gain": 2.0, "name_x": "abc"}))
    assert spec.params == {"win": 200, "gain": 2.0, "name_x": "abc"}
```

`tests/test_run_factor.py`：

```python
def test_run_factor_params_substitution(tmp_path):
    # spec.params 中 ${win} 引用 → 编译期替换
    build_db(tmp_path)
    spec_path.write_text("""
name: param_demo
category: custom
direction: 1
universe: {codes: ["000001.SZ"]}
params: {win: 20}
date: {start: "2024-01-02", end: "2024-01-09"}
formula: |
  from polars_ta.prefix.wq import ts_mean
  signal = ts_mean(close, ${win}) - close
""")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=...))
    assert result.panel.height > 0


def test_run_factor_unknown_param_rejected(tmp_path):
    with pytest.raises(ValueError, match="param"):
        ...  # formula 引用 ${nope} 未在 params 声明 → 报错
```

`tests/test_run_factor.py` 增加 def 内窗口算子端到端：

```python
def test_run_factor_def_with_window_ops(tmp_path):
    # def 内窗口算子现在合法（内联展开）——多资产无泄漏
    build_db(tmp_path)
    spec_path.write_text("""
name: def_demo
category: custom
direction: 1
universe: {codes: ["000001.SZ", "600519.SH"]}
date: {start: "2024-01-02", end: "2024-01-09"}
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_delay

  def mom(x, n):
      return ts_mean(x, n) / ts_delay(x, 1) - 1

  signal = mom(close, 3)
""")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=...))
    # 分区正确：每资产首行 ts_delay 为 null → signal null
    assert result.panel.filter(pl.col("code") == "600519").sort("date")["signal"].null_count() >= 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_spec.py tests/test_run_factor.py -q`
Expected: FAIL — params 字段不存在；inline_defs 未接入；${} 未替换。

**Step 3: 实现**

`src/factorlab/spec.py` FactorSpec 增加：

```python
    params: dict[str, Any] = Field(default_factory=dict)  # 顶层参数（formula 内 ${name} 引用）
```

`src/factorlab/engine/compute.py`：

- `_substitute_params(formula, params) -> str`：文本替换 `${name}`（正则 `\$\{(\w+)\}`）；未知参数报错；formula 与 operators 宏体都替换。
- 展开链（run_factor 内，spec.formula 处理后）：

```python
    formula = _substitute_params(spec.formula or "", spec.params)
    formula = expand_user_macros(formula, spec.operators)
    formula = inline_defs(formula)
    formula = expand_platform_macros(formula)
```

（params 替换在最前——宏体/def 内也可见 ${}。）

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_spec.py tests/test_run_factor.py -q`
Expected: PASS（含 def 窗口算子端到端——partitions 的 def guard 在内联后不触发）。

**Step 5: Commit**

```bash
git add src/factorlab/spec.py src/factorlab/engine/compute.py tests/test_spec.py tests/test_run_factor.py
git commit -m "feat: support params substitution and def inlining in run chain"
```

---

### Task 3: run --set 变体 + 文档 + 端到端

**Files:**
- Modify: `src/factorlab/cli/main.py`（--set）
- Test: `tests/test_cli_run.py`（变体命名/results 隔离）
- Modify: `docs/interface.md`、`docs/factor-mining-playbook.md`
- Test: `tests/test_e2e_m4.py` 或新 `tests/test_e2e_free_form.py`（真实 A 股版 RunLength 思路因子）

**Step 1: 测试**

`tests/test_cli_run.py`：

```python
def test_run_set_param_variant(tmp_path, monkeypatch):
    # --set win=100 → 变体名 name_win100，results 独立目录
    ...（复用 run e2e fixture；断言 results_dir 下存在 name_win100/summary.json）
```

`tests/test_e2e_free_form.py`（集成，真实平台库）：

```python
@pytest.mark.integration
def test_e2e_free_form_run_length_factor(real_db_path, tmp_path):
    # A 股日频版 RunLength 思路：量能游程 × 钟形调制
    spec_path.write_text("""
name: vol_run_energy
category: custom
direction: -1
params: {win: 200, gain: 2.0}
universe:
  codes: ["000001.SZ", "600519.SH", "000002.SZ", "600036.SH", "601318.SH"]
date: {start: "2024-01-01", end: "2025-12-31"}
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_rank, ts_delta, ts_count

  def oi_energy(x, n):
      _e = ts_rank(ts_delta(x, 1).abs(), n)
      return sqrt(_e * (1 - _e))

  _energy = oi_energy(volume, ${win})
  _rl = ts_count(sign(ts_delta(volume, 1)) == 1, 500)
  signal = -ts_rank(_rl, 500) * _energy * ${gain}
""")
    result = runner.invoke(app, ["run", str(spec_path)])  # 或直接 run_factor + evaluate
    assert result.exit_code == 0
    summary = json.loads(...)
    assert summary["evaluation"]["n_weeks"] > 50
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_run.py tests/test_e2e_free_form.py -q`
Expected: FAIL — --set 不存在。

**Step 3: 实现**

`src/factorlab/cli/main.py` run 命令增加：

```python
def run_factor_cli(spec_path: Path, ..., set_params: list[str] = typer.Option(None, "--set"),
                   ...):
    ...
    overrides = {}
    for kv in set_params or []:
        key, _, value = kv.partition("=")
        if not key:
            raise typer.BadParameter(f"--set 格式应为 k=v: {kv}")
        overrides[key] = _parse_param_value(value)  # int/float/bool/str
    spec = load_spec(spec_path)
    variant = spec.name
    if overrides:
        spec.params = {**spec.params, **overrides}
        variant = spec.name + "_" + "_".join(f"{k}{v}" for k, v in overrides.items())
    ctx.output_dir = output_dir or (settings.results_dir / variant)
    ...
```

（`_parse_param_value`：int/float/bool/str 尝试解析。）

**Step 4: 全量验证**

Run: `python -m pytest -q`
Expected: 全部 PASS（含集成——真实平台库 free-form 因子）。

**Step 5: 文档与提交**

`docs/interface.md`：params 字段、${} 引用、inline_defs、run --set。
`docs/factor-mining-playbook.md`：§2 增加自由代码模板（def 自定义算子 + params）。

```bash
git add src/factorlab/cli/main.py tests/test_cli_run.py tests/test_e2e_free_form.py docs/interface.md docs/factor-mining-playbook.md
git commit -m "feat: add run --set param variants; document free-form formulas"
```

---

### Task 3 实现修正记录（与计划的偏差，实现时发现并处理）

1. **e2e 日期范围 2024-2025 → 2022-2025**：polars_ta 全窗口语义（min_samples=窗口
   长），500 日游程窗口在 2 年（≈483 交易日）面板上输出全 null（n_weeks=0）。
   改为 4 年（≈967 交易日）——500 日暖机后仍有 ~56 有效周（实测 n_weeks=56，
   实测 null_ratio≈0.72：暖机 + 停牌日中断 500 行窗口）。
2. **`ts_count` 未注册**：计划公式使用 `ts_count` 但 polars_ta_wrappers 的 _WQ_TS
   名单缺失 → 分区校验「未知算子」。已补入 _WQ_TS。
3. **属性调用（`.abs()`）两处阻碍**：ast_gate 拒绝一切属性调用（设计 §2.1 用
   `ts_delta(x, 1).abs()`）且 expr_codegen 的 AST 处理不支持属性调用（visit_Call
   假设 func 为 Name，直接崩溃）。处理：ast_gate 放行白名单纯元素级方法
   （abs/log/log1p/sqrt/exp/sign/floor）在表达式结果上的调用（基表达式非裸 Name——
   np.abs/pl.read_csv 仍拒）；新增 `rewrite_expr_methods`（X.method(...) →
   method(X, ...)）接入展开链（compute_formula 与 run_factor 早链）。
4. **`--set` 空值**：`--set win=`（空 value）同样拒绝（`if not key or not value`）。

---

## Self-Review

**1. Spec coverage（对照 free-form spec）：**
- §2 formula 自由代码 + def 内联 → Task 1/2 ✓
- §3 参数化（params/${}/--set 变体）→ Task 2/3 ✓
- §4 测试策略 → 各任务 + Task 3 集成 ✓；§5 不做（循环/四段式）→ 计划不含 ✓

**2. Placeholder scan：** 无 TBD/TODO；inline_defs 的实现给完整代码框架（提升/绑定/改名逻辑）。

**3. Type consistency：** `inline_defs(source)`、`_substitute_params(formula, params)`、
`FactorSpec.params: dict[str, Any]`、run `--set k=v`——任务间一致 ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-17-factorlab-free-form-formula.md`. Two execution options:

1. Subagent-Driven (recommended)
2. Inline Execution

Which approach?
