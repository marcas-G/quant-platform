---
xname: reversal_20d_wcorr
formula: |
  signal = 2*cs_rank(corr) + cs_rank(intraday) + cs_rank(turn) + cs_rank(vol)
tags: [mine_b3r42, reversal, weighted, marginal]
params: {}
status: 观察中（t/IR 微升新纪录、IC 略降）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_wcorr 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_wcorr`（= `factor/reversal_20d_wcorr.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（t/IR 微升新纪录、IC 略降） |
| 标签 | mine_b3r42, reversal, weighted, marginal |
| 创建 | 2026-08-18（批次 3 轮次 42，种子 `reversal_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：四维等权组合（全库最强）的加权变体——corr（IR 最高 0.477）
双倍权重放大稳定性。

**数学表达**：

```
signal = 2×cs_rank(corr) + cs_rank(intraday) + cs_rank(turn) + cs_rank(ts_rank(vol,20))
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
name: reversal_20d_wcorr
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, ts_rank, cs_rank
  signal = 2 * cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 20)) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(turnover) + cs_rank(ts_rank(volume, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_wcorr/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0688 |
| t 值 | 7.44（新纪录） |
| IR | 0.557（新纪录） |
| 近 26 周 mean / t | 0.0343 / 1.27 |
| PearsonIC mean | -0.0224（t=-2.75） |

| 项 | 值 |
|----|----|
| spread | 0.00457 |
| D1 / D10 | 0.00319 / -0.00137 |

### 判定

- vs 四维等权（全库最强）：IC 0.0688（0.0719，-4%）、**t 7.44（7.35）**、
  **IR 0.557（0.551）**、近 26 周持平。
- 结论：**观察中（边际）**——corr 加权放大稳定性（t/IR 微升）但稀释
  水平（corr 的 IC 低于 intraday/turn）；等权仍综合最优。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_wcorr`（初始） | 批次 3 轮 42：W2 corr 双倍权重 | 0.0688 | 7.44 | 观察中：t/IR 微升、IC 略降 |

## 6. 风险与备注

- **权重结论**：加权仅微调稳定性-水平平衡——等权已接近最优；
  权重优化边际小。
- 基准 [`reversal_20d_corr_intraday_turn_vol.md`](reversal_20d_corr_intraday_turn_vol.md)
  （全库最强：0.072/7.35/0.551）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
