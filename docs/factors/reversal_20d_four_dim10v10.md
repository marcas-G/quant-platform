---
xname: reversal_20d_four_dim10v10
formula: |
  signal = cs_rank(corr10) + cs_rank(intraday20) + cs_rank(turn) + cs_rank(vol10)
tags: [mine_b3r46, reversal, four_dim10v10, stability_record]
params: {}
status: 观察中（t/IR 新纪录、IC 略降）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim10v10 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim10v10`（= `factor/reversal_20d_four_dim10v10.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（t=7.47/IR=0.560 新纪录、IC 略降） |
| 标签 | mine_b3r46, reversal, four_dim10v10, stability_record |
| 创建 | 2026-08-18（批次 3 轮次 46，种子 `momentum_20d_turnrank`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：four_dim10（全库最强）的 vol 维度窗口谱——20 vs 10。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(intraday20) + cs_rank(turn) + cs_rank(ts_rank(vol,10))
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
name: reversal_20d_four_dim10v10
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(turnover) + cs_rank(ts_rank(volume, 10))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim10v10/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0713 |
| t 值 | 7.47（新纪录） |
| IR | 0.560（新纪录） |
| 近 26 周 mean / t | 0.0390 / 1.38（新高） |
| PearsonIC mean | -0.0247（t=-2.92） |

| 项 | 值 |
|----|----|
| spread | 0.00515 |
| D1 / D10 | 0.00299 / -0.00216 |

### 判定

- vs four_dim10（vol20）：IC 0.0713（0.0721，-1%）、**t 7.47（7.40）**、
  **IR 0.560（0.555）**、近 26 周 t=1.38（1.34）——vol10 微升稳定性。
- 结论：**观察中（边际）**——vol10 与 corr10 同向（短窗增稳定性）；
  four_dim10（vol20）仍综合最优（IC 更高）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim10v10`（初始） | 批次 3 轮 46：V2 vol10 | 0.0713 | 7.47 | 观察中：t/IR 新纪录 |

## 6. 风险与备注

- **窗口谱应用**：corr/vol 短窗（10）增稳定性、intraday 20 日保水平——
  窗口-稳定性-水平平衡；综合最优仍 four_dim10。
- 基准 [`reversal_20d_four_dim10.md`](reversal_20d_four_dim10.md)（全库最强）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
