---
xname: momentum_20d_volrank
formula: |
  signal = (MA(close,20)/close[t-20]-1) * cs_rank(ts_std_dev(close,20))
tags: [mine_b3r6, reversal, vol_conditional, proxy_swap, marginal]
params: {}
status: 观察中（边际：与换手率代理等价）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_volrank 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_volrank`（= `factor/momentum_20d_volrank.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（与换手率代理等价） |
| 标签 | mine_b3r6, reversal, vol_conditional, proxy_swap, marginal |
| 创建 | 2026-08-18（批次 3 轮次 6，种子 `momentum_20d_turnrank_avg20`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子假设 (H3) 换手率是活跃度-反转交互的最佳代理。检验波动率
（20 日收益波动横截面 rank）是否更优：代理互换（替代而非叠加）。

**数学表达**：

```
signal = (MA(close,20)/close[t-20] - 1) × cs_rank(ts_std_dev(close, 20))
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
name: momentum_20d_volrank
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, ts_std_dev, cs_rank
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * cs_rank(ts_std_dev(close, 20))
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_volrank/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 174 |
| 平均股票数 | 4875 |
| 信号缺失率 | 0.0942 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0422 |
| t 值 | 3.52 |
| IR | 0.267 |
| 近 26 周 mean / t | 0.0045 / 0.14 |
| PearsonIC mean | -0.0224（t=-2.16） |

| 项 | 值 |
|----|----|
| spread | 0.00424 |
| D1 / D10 | 0.00310 / -0.00114 |

### 判定

- vs turnrank（换手率代理）：IC 0.0422（0.0419，+0.7%）、t 3.52（3.37）、
  IR 0.267（0.255）、spread 0.00424（0.00470，-10%）。
- 结论：**观察中（边际）**——波动率与换手率承载几乎相同的信息
  （两者正相关），代理互换基本等价；IC 微升或为噪声。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `momentum_20d_volrank`（初始） | 批次 3 轮 6：H3 换手率→波动率代理互换 | 0.0422 | 3.52 | 边际：与换手率代理等价 |

## 6. 风险与备注

- **代理等价结论**：活跃度-反转交互的代理（换手率/波动率）信息重叠度高；
  后续在条件化维度上优先探索**正交**代理（如市值已证伪、行业/量能事件）。
- 种子 [`momentum_20d_turnrank_avg20.md`](momentum_20d_turnrank_avg20.md)；
  换手率版基准 [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
