---
xname: reversal_20d_netflow_pct
formula: |
  signal = ts_sum(amount*sign(returns), 20) / ts_sum(amount, 20)
tags: [mine_b3r55, reversal, netflow_pct, abs_better]
params: {}
status: 无效（绝对量资金流更优）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_netflow_pct 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_netflow_pct`（= `factor/reversal_20d_netflow_pct.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——绝对量版更优 |
| 标签 | mine_b3r55, reversal, netflow_pct, abs_better |
| 创建 | 2026-08-18（批次 3 轮次 55，种子 `momentum_20d_turnrank_avg20`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：净流入占比（剔除规模）是否比绝对量更纯。

**数学表达**：

```
signal = Σ(amount×sign(returns), 20) / Σ(amount, 20)
```

## 3. 参数与实现

### 处理链

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2023-01-01 ~ 2026-07-31
process: winsorize(quantile=0.99) → standardize()
target: forward_return_5d
adjustment: qfq
```

### 实现（YAML 全文）

```yaml
name: reversal_20d_netflow_pct
category: custom
direction: -1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2023-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_sum
  signal = ts_sum(amount * sign(returns(close)), 20) / ts_sum(amount, 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_netflow_pct/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0283 |
| t 值 | 3.30 |
| IR | 0.247 |
| 近 26 周 mean / t | -0.0027 / -0.11 |

| 项 | 值 |
|----|----|
| spread | 0.00169 |
| D1 / D10 | 0.00218 / 0.00049 |

### 判定

- vs netflow（绝对量）：IC 0.0283（0.0417，-32%）、t 3.30（5.01）——
  **占比版显著劣化**。
- 结论：**无效（F2' 否定）**——**绝对量资金流更优**：规模信息本身有值
  （大盘股资金流绝对量携带更多信息）；占比归一化引入噪声。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_netflow_pct`（初始） | 批次 3 轮 55：F2 占比归一化 | 0.0283 | 3.30 | 无效：绝对量更优 |

## 6. 风险与备注

- **资金流结论**：绝对量净流入（含规模信息）是最优表达——
  归一化方向不再重复。
- 基准 [`reversal_20d_netflow.md`](reversal_20d_netflow.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
