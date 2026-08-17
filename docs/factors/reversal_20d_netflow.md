---
xname: reversal_20d_netflow
formula: |
  signal = ts_sum(amount * sign(returns(close)), 20)
tags: [mine_b3r40, reversal, netflow, significant]
params: {}
status: 候选（显著：t=5.01/IR=0.375）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_netflow 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_netflow`（= `factor/reversal_20d_netflow.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（显著：t=5.01/IR=0.375） |
| 标签 | mine_b3r40, reversal, netflow, significant |
| 创建 | 2026-08-18（批次 3 轮次 40，种子 `momentum_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：资金流代理维度（amount 方向加权未测过）——净流入 proxy。

**数学表达**：

```
signal = Σ (amount × sign(returns)) over 20d   （净流入：放量上涨正、放量下跌负）
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
name: reversal_20d_netflow
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
  signal = ts_sum(amount * sign(returns(close)), 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_netflow/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0417 |
| t 值 | 5.01 |
| IR | 0.375 |
| 近 26 周 mean / t | 0.0035 / 0.14 |
| PearsonIC mean | -0.0164（t=-2.32） |

| 项 | 值 |
|----|----|
| spread | 0.00250 |
| D1 / D10 | 0.00149 / -0.00101 |

### 判定

- IC 0.0417（t=5.01 强显著、IR 0.375 优秀、spread 0.25%/周）——
  **资金流代理是有效新维度**（净流入追涨 → 反转做空）。
- 与 corr（0.0425）相当；可作四维组合（0.072/7.35）的潜在第五维。
- 结论：**候选**——资金流维度独立有效。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_netflow`（初始） | 批次 3 轮 40：F2 净流入代理 | 0.0417 | 5.01 | 候选：资金流维度显著 |

## 6. 风险与备注

- **组合方向**：netflow 与四维组合（corr+intraday+turn+vol）的正交性
  待测——资金流可能部分重叠（amount 与 volume 同源）。
- 种子 [`momentum_20d.md`](momentum_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
