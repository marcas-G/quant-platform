---
xname: reversal_20d_four_dim10
formula: |
  signal = cs_rank(corr10) + cs_rank(intraday) + cs_rank(turn) + cs_rank(vol)
tags: [mine_b3r45, reversal, four_dim10, library_best]
params: {}
status: 候选（新全库最强：0.0721/7.40/0.555）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim10 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim10`（= `factor/reversal_20d_four_dim10.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（新全库最强：IC 0.0721/t 7.40/IR 0.555） |
| 标签 | mine_b3r45, reversal, four_dim10, library_best |
| 创建 | 2026-08-18（批次 3 轮次 45，种子 `reversal_20d_volconf`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：corr 谱峰 10 日（轮 44）应用到四维组合——corr 维度窗口升级。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(intraday) + cs_rank(turn) + cs_rank(ts_rank(vol,20))
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
name: reversal_20d_four_dim10
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(turnover) + cs_rank(ts_rank(volume, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim10/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0721（**新全库纪录**） |
| t 值 | 7.40 |
| IR | 0.555 |
| 近 26 周 mean / t | 0.0369 / 1.34 |
| PearsonIC mean | -0.0250（t=-2.89） |

| 项 | 值 |
|----|----|
| spread | 0.00539 |
| D1 / D10 | 0.00308 / -0.00231 |

### 判定

- vs 四维（corr20）：IC 0.0721（0.0719，+0.3%）、t 7.40（7.35）、
  IR 0.555（0.551）、近 26 周 t=1.34（1.30）——**全指标微升**。
- 结论：**候选（新全库最强）**——corr10 谱峰增益传导至组合；
  各维度窗口均取谱峰。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim10`（初始） | 批次 3 轮 45：D2 corr10 | 0.0721 | 7.40 | **候选**：新全库最强 |

## 6. 风险与备注

- **窗口谱应用**：四维组合各维度均取谱峰（corr10/intraday20/turn 当日/vol20）；
  后续窗口级微调边际小。
- 基准 [`reversal_20d_corr_intraday_turn_vol.md`](reversal_20d_corr_intraday_turn_vol.md)
  （corr20 版）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
