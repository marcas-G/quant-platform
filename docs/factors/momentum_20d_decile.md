---
xname: momentum_20d_decile
formula: |
  signal = floor(cs_rank(ts_mean(close,20)/ts_delay(close,20)-1) * 10) / 10
tags: [mine_r5, reversal, decile, rank_only, no_gain]
params: {}
status: 无效（与连续版等价）
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# momentum_20d_decile 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_decile`（= `factor/momentum_20d_decile.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 无效——与连续版完全等价（秩次信息已含全部预测力）；保留作确认性对照 |
| 标签 | mine_r5, reversal, decile, rank_only, no_gain |
| 创建 | 2026-08-17（挖因子批次 2 轮次 5，种子 `momentum_20d`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `momentum_20d` 的隐含假设 (H6) 连续信号、横截面组内差异有价值。
检验"反转预测力是否只需秩次/档位信息"：信号分档
`floor(cs_rank(动量)×10)/10`（值域 11 档含 1.0，见 §6）。

**核心逻辑**：20 日反转 × 横截面秩次分档（幅度函数被替换为档位）。

**数学表达**：

```
signal = floor(cs_rank(MA(close,20)/close[t-20] - 1) × 10) / 10
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
name: momentum_20d_decile
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, cs_rank
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  signal = floor(cs_rank(_mom) * 10) / 10
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_decile/summary.json`（2026-08-17）。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 复权 | qfq |
| 信号缺失率 | 7.23% |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0406 |
| t 值 | 3.45 |
| IR | 0.259 |
| 近 26 周 mean | 0.0014 |
| 近 26 周 t | 0.04 |
| PearsonIC mean（原始信号） | -0.0158（t=-1.57） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00361 |
| 单调性 | false |
| D1 mean_ret | 0.00265 |
| D10 mean_ret | -0.00096 |

### 判定

- 与连续版 `reversal_20d`（IC 0.0409/t 3.47/IR 0.260/spread 0.00362）**完全等价**：
  IC 0.0406/t 3.45/IR 0.259/spread 0.00361——D1/D10 逐位相同。
- 结论：**无效（等价确认）**——反转信号的预测力全部蕴含在横截面秩次中，
  幅度函数（连续值/分档/其他单调变换）不携带额外信息。
  这是对评估方法学的确认：Spearman IC 与分层回测天然只依赖秩次。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`reversal_20d_intraday_tv` | 批次3轮31：L4 双条件化叠加，见 [`reversal_20d_intraday_tv.md`](reversal_20d_intraday_tv.md) | 0.0567 | 5.34 | 观察中：t/IR 创纪录、IC 未超 turn |
| 2026-08-18 | 衍生：`reversal_20d_intraday` | 批次3轮25：D2 日内成分，见 [`reversal_20d_intraday.md`](reversal_20d_intraday.md) | 0.0591 | 5.22 | **最强候选**：IC 全库纪录，日内是反转主驱动 |
| 2026-08-18 | 衍生：`momentum_20d_decile5` | 批次3轮8：D3 5 档粒度，见 [`momentum_20d_decile5.md`](momentum_20d_decile5.md) | 0.0397 | 3.41 | **无效**：10 档有边际信息 |
| 2026-08-17 | `momentum_20d_decile`（初始） | 挖因子轮 5：H6 连续 → 横截面秩次分档 | 0.0406 | 3.45 | 无效：与连续版完全等价 |

## 6. 风险与备注

- **确认价值**：后续迭代不要追求"信号幅度函数的改进"——改进只能来自
  改变秩次结构（如换手率条件化、VWAP 口径，均有效）而非幅度变换。
- **值域说明**：`floor(cs_rank(_mom)*10)/10` 实测值域 (0, 0.1, Ellipsis, 1.0)
  共 11 档（cs_rank pct=True 最大值为 1.0，截面第一落入 1.0 档）——
  秩次单调性不受影响，与 10 档语义等价。
- 种子 [`momentum_20d.md`](momentum_20d.md) 为方向对照；连续版基准
  [`reversal_20d.md`](reversal_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
