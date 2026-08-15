# FactorLab M1 接口文档

本文件描述 M1 已交付的 CLI、Spec、因子脚本和 Python API。实现与设计文档冲突时以
`docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md` 为准。

## 1. CLI

安装 editable 包后，命令入口为 `factorlab`。

| 命令 | 说明 |
|------|------|
| `factorlab version` | 打印包版本 |
| `factorlab lint <spec.yaml>` | 校验 Spec 与因子脚本 AST，失败时以非 0 退出 |
| `factorlab op list` | 列出已注册算子 |
| `factorlab op doc <name>` | 查看算子名称、类别、版本与 docstring |
| `factorlab op add <plugin.py> [--force]` | 校验并注册用户插件；同名冲突需 `--force` |
| `factorlab op remove <name>` | 禁用用户插件，保留已计算历史结果 |

## 2. Spec 文件

Spec 为 YAML。最小单因子示例：

```yaml
name: demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
date:
  start: "2020-01-01"
  end: "2021-01-01"
formula: |
  from polars_ta.prefix.wq import ts_delay
  signal = ts_delay(close, 1)
```

字段：

- `name`：必填，`^[A-Za-z_][A-Za-z0-9_]{0,63}$`。
- `category`：必填，`ohlcv_core | ohlcv_retail | valuation | custom`。
- `direction`：必填，`1` 或 `-1`。
- `universe.codes` 与 `universe.rules`：二选一。
- `date.start` / `date.end`：可选，`YYYY-MM-DD`。
- `target`：`forward_return_5d | forward_return_20d`，默认 `forward_return_5d`。
- `process`：可选字符串列表。
- `operators`：可选 DSL 宏映射。
- `formula` 或 `factors`：二选一。
- 使用 `factors` 时必须提供 `combine`。
- `combine.method`：`ic_weight | equal_weight | weight_sum`；`weight_sum` 时
  `weights` 非空且数量等于 `factors` 数量。

多因子示例：

```yaml
name: composite_demo
category: custom
direction: 1
universe:
  rules: {exclude_st: true, min_list_days: 120}
factors:
  - name: a
    formula: "signal = close / open - 1"
  - name: b
    formula: "signal = close - open"
combine:
  method: equal_weight
```

## 3. 因子脚本

`formula` 是受白名单限制的 Python 代码块，最终保留输出列 `signal`。

允许：

- 赋值
- `def` 自定义函数
- `class`
- 白名单 `import`
- 表达式、算术、比较、布尔、`a if cond else b`
- 下标 `x[0]`
- `#` 注释

禁止：

- `for` / `while`
- 副作用、文件/网络/子进程/系统调用
- `eval`、`exec`、`open`、`compile`、`__import__`
- 属性调用，例如 `pl.read_csv(...)`
- 白名单以外的 `import`

白名单 import 前缀：

- `polars`
- `polars_ta.prefix.`
- `factorlab.ops.`

## 4. Python API

### `factorlab.spec.load_spec(path) -> FactorSpec`

读取 YAML 并返回 Pydantic `FactorSpec`。校验失败抛出 `pydantic.ValidationError`。

### `factorlab.factor.ast_gate.validate_formula(source: str) -> None`

校验因子脚本。失败抛出 `factorlab.factor.errors.FactorDSLError`。

### `factorlab.engine.compute.compute_formula(df, formula, asset="code", date="date") -> pl.DataFrame`

在小样本 Polars DataFrame 上执行因子脚本，返回按 `date, asset` 排序的
`[date, asset, signal]` 面板。当前 M1 不加载 DuckDB。

### 算子注册

```python
import polars as pl
from factorlab.ops.registry import factor_op

@factor_op("tail_ratio", kind="ts", version="0.1.0")
def tail_ratio(x: pl.Expr, n: int) -> pl.Expr:
    spread = x.rolling_quantile(0.9, window_size=n) - x.rolling_quantile(0.1, window_size=n)
    return spread / x.rolling_std(window_size=n)
```

`kind` 取值：`el | ts | cs | gp | ta`。

### 插件管理

用户插件放在 `~/.factorlab/plugins/`。插件文件必须只定义纯函数，并通过
`factor_op` 注册算子。`op add` 会做 AST 安全扫描。

## 5. 测试

运行：

```powershell
python -m pytest
```

当前 M1 覆盖 Spec 校验、AST 白名单、算子插件生命周期、最小计算路径和 CLI smoke。
