---
xname: reversal_20d_corr_intraday_turn_vol
formula: |
  signal = cs_rank(corr) + cs_rank(intraday) + cs_rank(turnover) + cs_rank(ts_rank(vol,20))
tags: [mine_b3r37, reversal, four_dim, stability_record]
params: {}
status: 候选（t/IR 新纪录：7.35/0.551）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_intraday_turn_vol 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_intraday_turn_vol`（= `factor/reversal_20d_corr_intraday_turn_vol.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（t=7.35/IR=0.551 新纪录） |
| 标签 | mine_b3r37, reversal, four_dim, stability_record |
| 创建 | 2026-08-18（批次 3 轮次 37，种子 `reversal_20d_nowin`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：三维组合（全库最强）加第四维（时序量能确认）——稳定性进一步。

**数学表达**：

```
signal = cs_rank(corr) + cs_rank(intraday) + cs_rank(turnover) + cs_rank(ts_rank(volume, 20))
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
name: reversal_20d_corr_intraday_turn_vol
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 20)) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(turnover) + cs_rank(ts_rank(volume, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_intraday_turn_vol/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0719 |
| t 值 | 7.35（**新纪录**） |
| IR | 0.551（**新纪录**） |
| 近 26 周 mean / t | 0.0380 / 1.30 |
| PearsonIC mean | -0.0243（t=-2.78） |

| 项 | 值 |
|----|----|
| spread | 0.00497（0.50%/周） |
| D1 / D10 | 0.00284 / -0.00213 |

### 判定

- vs 三维（全库最强）：IC 0.0719（0.0724 持平）、**t 7.35（6.79，+8%）**、
  **IR 0.551（0.509，+8%）**、近 26 周 t=1.30（持平）。
- 结论：**候选（t/IR 新纪录）**——第四维推高稳定性（量能与换手率
  信息部分重叠故 IC 持平）；四维为当前稳定性最优。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`reversal_20d_civ_extreme` | 批次4轮3：F3 极端信号替换 turn，见 [`reversal_20d_civ_extreme.md`](reversal_20d_civ_extreme.md) | 0.0668 | 6.66 | **无效**：组合内冗余（正交性>信息密度） |
| 2026-08-18 | `reversal_20d_corr_intraday_turn_vol`（初始） | 批次 3 轮 37：F2 第四维 | 0.0719 | 7.35 | **候选**：t/IR 新纪录 |

## 6. 风险与备注

- **维度饱和观察**：IC 随维度收敛（三维 0.0724 → 四维 0.0719），
  稳定性继续提升——组合维度的边际收益在稳定性而非水平。
- 基准 [`reversal_20d_corr_intraday_turn.md`](reversal_20d_corr_intraday_turn.md)
  （IC 纪录 0.0724）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
