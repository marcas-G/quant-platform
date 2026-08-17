---
xname: reversal_20d_corr_turn_flow30
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow30)
tags: [mine_b3r90, reversal, corr_turn_flow30, peak_applied]
params: {}
status: 候选（flow30 微升）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_turn_flow30 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_turn_flow30`（= `factor/reversal_20d_corr_turn_flow30.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（flow30 谱峰应用微升） |
| 标签 | mine_b3r90, reversal, corr_turn_flow30, peak_applied |
| 创建 | 2026-08-18（批次 3 轮次 90，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：flow 谱峰 30 日（轮 89）应用到三维组合。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow30)
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
name: reversal_20d_corr_turn_flow30
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_sum(amount * sign(returns(close)), 30))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_turn_flow30/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0717 |
| t 值 | 6.74 |
| IR | 0.508 |
| 近 26 周 mean / t | 0.0491 / 1.50 |

| 项 | 值 |
|----|----|
| spread | 0.00454 |
| D1 / D10 | 0.00268 / -0.00185 |

### 判定

- vs corr_turn_flow（flow20）：IC +2%（0.0703→0.0717）、近 26 周 1.50（1.49）——
  flow30 谱峰应用有效。
- vs cti 纪录（0.0744）：低 4%——IC 纪录保持。
- 结论：**候选**——flow30 版本为 corr/turn/flow 组合最优。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_turn_flow30`（初始） | 批次 3 轮 90：F3 flow30 | 0.0717 | 6.74 | 候选：flow30 微升 |

## 6. 风险与备注

- **谱峰应用**：flow30 传导 +2%——组合维度窗口取谱峰。
- 基准 [`reversal_20d_corr_turn_intraday.md`](reversal_20d_corr_turn_intraday.md)
  （全库 IC 纪录 0.0744）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
