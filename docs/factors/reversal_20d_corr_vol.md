---
xname: reversal_20d_corr_vol
formula: |
  signal = cs_rank(corr10) + cs_rank(ts_rank(vol,10))
tags: [mine_b3r75, reversal, corr_vol, marginal]
params: {}
status: 候选（边际：IC 微升、IR 持平）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_vol 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_vol`（= `factor/reversal_20d_corr_vol.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（边际：IC 0.0450 微升） |
| 标签 | mine_b3r75, reversal, corr_vol, marginal |
| 创建 | 2026-08-18（批次 3 轮次 75，种子 `momentum_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量维度组合最后一块——结构（corr）× 事件（vol）。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(ts_rank(volume, 10))
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
name: reversal_20d_corr_vol
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_rank, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_rank(volume, 10))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_vol/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 180 |
| 平均股票数 | 4884 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0450 |
| t 值 | 6.45 |
| IR | 0.481 |
| 近 26 周 mean / t | 0.0145 / 0.86 |

| 项 | 值 |
|----|----|
| spread | 0.00316 |
| D1 / D10 | 0.00381 / 0.00064 |

### 判定

- vs corr10：IC +2.5%（0.0439→0.0450）、IR 持平（0.481）——
  结构×事件部分互补。
- vs vol_flow（轮 74）：IC 略低（0.0450 vs 0.0461）。
- 结论：**候选（边际）**——corr×vol 微增 IC；量维度组合矩阵完成
  （corr×flow、vol×flow、corr×vol 均有效——结构差异决定互补性）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_vol`（初始） | 批次 3 轮 75：C3 corr×vol | 0.0450 | 6.45 | 候选：边际 |

## 6. 风险与备注

- **量维度组合矩阵完成**：corr/vol/flow 两两组合均有效（结构/事件/方向
  差异互补）——量维度内部组合可行性高（与轮 39 的 symrun 耦合特例不同）。
- 基准 [`reversal_20d_pricevolcorr10.md`](reversal_20d_pricevolcorr10.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
