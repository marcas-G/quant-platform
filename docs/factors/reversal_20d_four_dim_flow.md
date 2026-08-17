---
xname: reversal_20d_four_dim_flow
formula: |
  signal = cs_rank(corr10) + cs_rank(flow20) + cs_rank(intraday20) + cs_rank(turn)
tags: [mine_b3r60, reversal, four_dim_flow, vol_better]
params: {}
status: 无效（vol 维度更优）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim_flow 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim_flow`（= `factor/reversal_20d_four_dim_flow.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——vol 维度更优 |
| 标签 | mine_b3r60, reversal, four_dim_flow, vol_better |
| 创建 | 2026-08-18（批次 3 轮次 60，种子 `momentum_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：四维构成变体——flow 替换 vol（组合矩阵补全）。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(flow20) + cs_rank(intraday20) + cs_rank(turn)
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
name: reversal_20d_four_dim_flow
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(amount * sign(returns(close)), 20)) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(turnover)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim_flow/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0717 |
| t 值 | 6.77 |
| IR | 0.508 |
| 近 26 周 mean / t | 0.0356 / 1.17 |

| 项 | 值 |
|----|----|
| spread | 0.00519 |
| D1 / D10 | 0.00285 / -0.00233 |

### 判定

- vs four_dim10（vol）：IC 0.0717（0.0721，-1%）、t 6.77（7.40，-9%）、
  IR 0.508（0.555，-8%）——**flow 替换 vol 全面略降**。
- 结论：**无效（维度构成确认）**——vol（量能确认）在组合中贡献
  大于 flow（资金流）；原四维构成（corr10/intraday/turn/vol）保持。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim_flow`（初始） | 批次 3 轮 60：F2 flow 替换 vol | 0.0717 | 6.77 | 无效：vol 更优 |

## 6. 风险与备注

- **四维构成定稿**：corr10/intraday/turn/vol 是最优四维集；
  后续不做维度替换（flow 单独有效但组合中冗余于 vol）。
- 基准 [`reversal_20d_four_dim10.md`](reversal_20d_four_dim10.md)（全库最强）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
