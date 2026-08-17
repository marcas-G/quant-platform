---
xname: reversal_20d_smallcap
formula: |
  signal = (MA(close,20)/close[t-20]-1) * (1 - cs_rank(circ_mv))
tags: [mine_b3r1, reversal, market_cap_conditional, no_gain]
params: {}
status: 无效（相对种子无改善）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_smallcap 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_smallcap`（= `factor/reversal_20d_smallcap.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——市值条件化未增强反转 |
| 标签 | mine_b3r1, reversal, market_cap_conditional, no_gain |
| 创建 | 2026-08-18（挖因子批次 3 轮次 1，种子 `reversal_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子隐含假设 (H4) 反转强度与市值无关。检验"小盘反转更强"
（流动性差→超调大）：`× (1 - cs_rank(circ_mv))` 小市值权重≈1。

**数学表达**：

```
signal = (MA(close,20)/close[t-20] - 1) × (1 - cs_rank(circ_mv))
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
name: reversal_20d_smallcap
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, cs_rank
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * (1 - cs_rank(circ_mv))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_smallcap/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 174 |
| 平均股票数 | 4875 |
| 复权 | qfq |
| 信号缺失率 | 0.0942 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0360 |
| t 值 | 2.90 |
| IR | 0.220 |
| 近 26 周 mean / t | -0.0116 / -0.38 |
| PearsonIC mean | -0.0177（t=-1.79） |

| 项 | 值 |
|----|----|
| spread | 0.00365 |
| D1 / D10 | 0.00301 / -0.00064 |
| 单调性 | False |

### 判定

- 与种子对比：IC 0.0360（0.0409，-12%）、t 2.90（3.47）、IR 0.220（0.260）、
  spread 持平（0.00365 vs 0.00362）。
- 结论：**无效**——在排除 ST 的沪深样本内小市值交互不增强反转；
  市值维度不改变秩次结构（circ_mv 与反转强度无单调交互）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_smallcap`（初始） | 批次 3 轮 1：H4 市值条件化 | 0.0360 | 2.90 | 无效：市值无交互 |

## 6. 风险与备注

- **证伪价值**：市值条件化维度已排除——反转在市值维度同质；
  后续不重复市值条件化方向（除非结合其他条件维度）。
- 种子 [`reversal_20d.md`](reversal_20d.md) 为反转基准。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
