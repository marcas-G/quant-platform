---
xname: reversal_20d_four_dim_ctfs
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow20) + cs_rank(skew20)
tags: [mine_b3r80, reversal, four_dim_ctfs, skew_redundant]
params: {}
status: 无效（skew 冗余于 corr）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim_ctfs 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim_ctfs`（= `factor/reversal_20d_four_dim_ctfs.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——skew 冗余于 corr |
| 标签 | mine_b3r80, reversal, four_dim_ctfs, skew_redundant |
| 创建 | 2026-08-18（批次 3 轮次 80，种子 `reversal_20d_nowin`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：corr/turn/flow 三维（0.0703）加第四维 skew——彩票维度贡献测试。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow20) + cs_rank(skew20)
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
name: reversal_20d_four_dim_ctfs
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_sum(amount * sign(returns(close)), 20)) + cs_rank(ts_skewness(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim_ctfs/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0696 |
| t 值 | 6.96 |
| IR | 0.522 |
| 近 26 周 mean / t | 0.0439 / 1.47 |

| 项 | 值 |
|----|----|
| spread | 0.00440 |
| D1 / D10 | 0.00314 / -0.00126 |

### 判定

- vs corr_turn_flow（三维）：IC 0.0696（0.0703，-1%）、t 6.96（6.76，+3%）、
  IR 0.522（0.507，+3%）——skew 第四维 IC 略降（与 corr 重叠，轮 52 冗余
  确认）、稳定性微升。
- 结论：**无效（冗余确认）**——skew 与 corr 信息重叠；
  三维 corr/turn/flow（0.0703）为 IC 最优组合之一。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim_ctfs`（初始） | 批次 3 轮 80：F3 四维加法 | 0.0696 | 6.96 | 无效：skew 冗余于 corr |

## 6. 风险与备注

- **组合谱更新**：corr/turn/flow（0.0703）是含 corr 组合的 IC 最优三维；
  skew 只在不含 corr 的组合（turn_skew 0.0633）中有效。
- 基准 [`reversal_20d_corr_turn_flow.md`](reversal_20d_corr_turn_flow.md)（候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
