---
xname: reversal_20d_intraday_tv
formula: |
  signal = ts_sum(close/open - 1, 20) * cs_rank(turnover) * ts_rank(volume, 20)
tags: [mine_b3r31, reversal, intraday_tv, stability_record]
params: {}
status: 观察中（t/IR 创纪录、IC 未超单条件化）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_intraday_tv 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_intraday_tv`（= `factor/reversal_20d_intraday_tv.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（t=5.34/IR=0.401 创纪录；IC 未超 turn） |
| 标签 | mine_b3r31, reversal, intraday_tv, stability_record |
| 创建 | 2026-08-18（批次 3 轮次 31，种子 `momentum_20d_decile`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：日内核心 × 换手率条件化（水平增益）× 量能确认（稳定性增益）
三层叠加——水平+稳定性同时获得检验。

**数学表达**：

```
signal = Σ(close/open - 1) over 20d × cs_rank(turnover) × ts_rank(volume, 20)
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
name: reversal_20d_intraday_tv
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
  from polars_ta.prefix.wq import ts_sum, ts_rank, cs_rank
  signal = ts_sum(close/open - 1, 20) * cs_rank(turnover) * ts_rank(volume, 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_intraday_tv/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0567 |
| t 值 | 5.34（创纪录） |
| IR | 0.401（创纪录） |
| 近 26 周 mean / t | 0.0034 / 0.12 |
| PearsonIC mean | -0.0418（t=-4.31） |

| 项 | 值 |
|----|----|
| spread | 0.00589 |
| D1 / D10 | 0.00258 / -0.00331 |

### 判定

- **t=5.34/IR=0.401 创纪录（连续第三次）**——双条件化叠加稳定性最优；
  IC 0.0567 介于 vol（0.0547）与 turn（0.0604）之间。
- spread 0.00589 略低于 turn（0.00610）。
- 结论：**观察中（边际）**——三层叠加 t/IR 最优但 IC 未超单换手率条件化；
  轮 27（intraday_turn）仍为 IC 纪录（0.0604）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_intraday_tv`（初始） | 批次 3 轮 31：L4 双条件化叠加 | 0.0567 | 5.34 | 观察中：t/IR 创纪录、IC 未超 turn |

## 6. 风险与备注

- **条件化家族结论**：日内核心上——换手率条件化给水平（IC）、量能确认给
  稳定性（t/IR）、双叠加给稳定性纪录；IC 上限 = intraday_turn（0.0604）。
  后续不再做条件化叠加（已饱和），转向核心表达/正交因子探索。
- 基准 [`reversal_20d_intraday.md`](reversal_20d_intraday.md)、
  [`reversal_20d_intraday_turn.md`](reversal_20d_intraday_turn.md)（IC 纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
