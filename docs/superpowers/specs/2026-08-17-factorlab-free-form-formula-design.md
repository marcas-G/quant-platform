# FactorLab 自由代码因子表达设计文档

日期：2026-08-17
状态：待评审
前置：M1-M5（引擎/评估/回测/Web 全链路）

## 1. 背景与目标

用户希望平台的因子**像写代码一样定义**（参考 RunLengthEnergyModulation.h 的表达方式）：
一个因子 = 一个自包含的代码单元（名字 + 参数 + 自定义逻辑），而不是在算子列表里拼装。

**核心目标**：
1. **formula 即自由代码**：可 `def` 自定义算子（含窗口算子）、中间变量、多步组合、条件逻辑。
2. **顶层参数化**：`params:` + 公式内 `${param}` 引用 + `run --set` 变体生成。
3. **自包含**：一个 spec 文件 = 完整因子（元数据 + 参数 + 自由代码）。

**边界**（用户确认）：组合自由 + 向量化表达（无循环）；缺的算子走插件。

## 2. formula 自由代码

### 2.1 表达形态

```yaml
name: vol_run_energy
category: custom
direction: -1
params: {win: 200, gain: 2.0}
universe:
  rules: {exclude_st: true}
date: {start: "2020-01-01", end: "2026-07-31"}
formula: |
  # 自定义算子（def 内可用窗口算子——内联展开保证分区安全）
  def oi_energy(x, n):
      _e = ts_rank(ts_delta(x, 1).abs(), n)
      return sqrt(_e * (1 - _e))

  def run_length(x, n):
      return ts_count(sign(ts_delta(x, 1)) == 1, n)

  _energy = oi_energy(volume, ${win})
  _rl = run_length(volume, 500)
  signal = -ts_rank(_rl, 500) * _energy * ${gain}
```

### 2.2 def 内联展开（技术路径）

- **现状**：`def` 内窗口算子被拒（expr_codegen 把 def 当黑盒，分区泄漏）。
- **方案**：扩展现有宏展开器（AST 内联）为 **def 内联**：
  - 收集公式中的 `FunctionDef`（非递归、非下划线命名约定不变）；
  - 调用点展开：函数体语句（中间变量赋值）参数绑定后**提升到公式顶层**（唯一命名防冲突），
    `return` 表达式参数绑定后替换调用点；
  - 展开后删除 def 节点——expr_codegen 看到顶层 `ts_*` 直接调用，分区/防未来自动正确。
- **组合自由**：def 调 def（递归展开）、def 内调用户宏、多语句函数体、条件逻辑。
- **边界**：递归 def 拒绝（检测自引用）；无循环保持（向量化 + 插件）。

### 2.3 展开链

```
validate_formula（原始源码校验）
→ expand_user_macros（spec.operators 宏）
→ inline_defs（def 内联展开——窗口算子合法化）
→ expand_platform_macros（平台薄封装）
→ validate_partition_calls / reject_future_shifts（展开后校验）
→ codegen_exec
```

## 3. 顶层参数化

### 3.1 spec 语法

```yaml
params: {win: 200, gain: 2.0}
formula: |
  signal = ts_rank(volume, ${win}) * ${gain}
```

- `params` 为 `dict[str, number|str|bool]`（可选字段，缺省空）。
- 公式（含 operators 宏体）内 `${name}` 文本引用 → 编译期替换为字面量。
- 未知参数名 → 校验报错。

### 3.2 run --set 变体

```bash
factorlab run spec.yaml                     # 用默认参数
factorlab run spec.yaml --set win=100       # 参数覆盖 → 变体
```

- `--set k=v`（可多次）覆盖 params；变体名 `name_kv`（如 `vol_run_energy_win100`），
  与默认变体并存（results 独立目录）。
- 默认变体名保持 `name`（不带参数后缀——兼容现有 list/show/serve）。

## 4. 测试策略

- **def 内联**：基本展开（def 含窗口算子 → 分区正确——多资产验证无泄漏）、多语句提升、
  def 调 def、def 内调用户宏、同一 def 多次调用（变量隔离）、递归拒绝、
  元素级 def（既有行为保持）。
- **params**：默认引用、--set 覆盖、未知参数报错、变体命名与 results 隔离。
- **端到端**：A 股日频版 RunLength 思路因子（vol_run_energy）跑通 + 评估合理。
- **防回归**：M1-M5 全部测试（def guard 相关测试更新——def 内窗口算子现在合法）。

## 5. 明确不做

- Python 循环放开（性能/防未来）。
- 类式四段语法（YAML 保持；formula 自由化已满足表达）。
- 参数类型校验体系（v1 支持 number/str/bool 字面量替换）。
