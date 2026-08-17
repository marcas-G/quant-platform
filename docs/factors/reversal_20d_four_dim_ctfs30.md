---
xname: reversal_20d_four_dim_ctfs30
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(skew20) + cs_rank(flow30)
tags: [mine_b3r96, reversal, four_dim_ctfs30, marginal]
params: {}
status: 候选（flow30 版 ctfs 微升）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim_ctfs30 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim_ctfs30`（= `factor/reversal_20d_four_dim_ctfs30.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（flow30 版 ctfs 微升） |
| 标签 | mine_b3r96, reversal, four_dim_ctfs30, marginal |
| 创建 | 2026-08-18（批次 3 轮次 96，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：ctfs 四维（flow20）换 flow30 谱峰。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(skew20) + cs_rank(flow30)
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
name: reversal_20d_four_dim_ctfs30
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, ts_skewness, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_sum(amount * sign(returns(close)), 30))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim_ctfs30/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0706 |
| t 值 | 6.91 |
| IR | 0.521 |
| 近 26 周 mean / t | 0.0468 / 1.48 |

| 项 | 值 |
|----|----|
| spread | 0.00436 |
| D1 / D10 | 0.00320 / -0.00116 |

### 判定

- vs ctfs（flow20）：IC +1.4%（0.0696→0.0706）、t/IR 持平——flow30 微升。
- vs turn_skew_flow30（三维）：IC +1.3%、t 6.91（6.31，+9%）。
- 结论：**候选**——ctfs30 为含 corr+skew 四维最优。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim_ctfs30`（初始） | 批次 3 轮 96：F3 flow30 | 0.0706 | 6.91 | 候选：微升 |

## 6. 风险与备注

- **flow30 系列定稿**：flow30 在全部组合中传导有效——
  后续组合统一 flow30。
- 基准 [`reversal_20d_four_dim_ctfs.md`](reversal_20d_four_dim_ctfs.md)（flow20 版）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
