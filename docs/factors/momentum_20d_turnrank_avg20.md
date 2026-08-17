---
xname: momentum_20d_turnrank_avg20
formula: |
  signal = (MA(close,20)/close[t-20]-1) * cs_rank(ts_mean(turnover, 20))
tags: [mine_r10, reversal, turnover_conditional, smoothed, equivalent]
params: {}
status: 无效（与快照版等价）
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# momentum_20d_turnrank_avg20 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_turnrank_avg20`（= `factor/momentum_20d_turnrank_avg20.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 无效——与当日快照版基本等价；确认性对照 |
| 标签 | mine_r10, reversal, turnover_conditional, smoothed, equivalent |
| 创建 | 2026-08-17（挖因子批次 2 轮次 10，种子 `momentum_20d_turnrank`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `momentum_20d_turnrank` 的隐含假设 (H3) 当日换手率快照即投机
强度。检验"投机拥挤是持续状态（20 日均换手更稳）"：条件权重改为
`cs_rank(ts_mean(turnover, 20))`。

**核心逻辑**：20 日反转 × 20 日均换手横截面分位（拥挤度平滑版）。

**数学表达**：

```
signal = (MA(close,20)/close[t-20] - 1) × cs_rank(MA(turnover, 20))
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
name: momentum_20d_turnrank_avg20
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
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * cs_rank(ts_mean(turnover, 20))
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_turnrank_avg20/summary.json`（2026-08-17）。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 174 |
| 平均股票数 | 4875 |
| 复权 | qfq |
| 信号缺失率 | 9.42% |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0416 |
| t 值 | 3.33 |
| IR | 0.252 |
| 近 26 周 mean | -0.0107 |
| 近 26 周 t | -0.35 |
| PearsonIC mean（原始信号） | -0.0251（t=-2.35） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00421 |
| 单调性 | false |
| D1 mean_ret | 0.00283 |
| D10 mean_ret | -0.00138 |

### 判定

- 与种子 `momentum_20d_turnrank` 对比：IC 0.0416（0.0419）、t 3.33（3.37）、
  IR 0.252（0.255）、spread 0.00421（0.00470，-10%）。
- 结论：**无效（等价确认）**——20 日均换手与当日快照基本等价；
  单日噪声在横截面 rank 中已被自然吸收（cs_rank 对日间噪声稳健）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`reversal_20d_corr_turn_intraday` | 批次3轮83：T3 三维加法，见 [`reversal_20d_corr_turn_intraday.md`](reversal_20d_corr_turn_intraday.md) | 0.0744 | 6.99 | **候选**：全库 IC 新纪录 |
| 2026-08-18 | 衍生：`reversal_20d_turn_skew_vol` | 批次3轮65：V3 三维加法，见 [`reversal_20d_turn_skew_vol.md`](reversal_20d_turn_skew_vol.md) | 0.0632 | 6.94 | 候选：三维 t/IR 新纪录 |
| 2026-08-18 | 衍生：`reversal_20d_netflow_pct` | 批次3轮55：F2 占比归一化，见 [`reversal_20d_netflow_pct.md`](reversal_20d_netflow_pct.md) | 0.0283 | 3.30 | **无效**：绝对量更优 |
| 2026-08-18 | 衍生：`reversal_20d_netflow10` | 批次3轮47：N2 netflow10，见 [`reversal_20d_netflow10.md`](reversal_20d_netflow10.md) | 0.0403 | 4.86 | **无效**：netflow 谱峰 20 日 |
| 2026-08-18 | 衍生：`reversal_20d_corr_intraday_turn` | 批次3轮36：T3 三维秩次加法，见 [`reversal_20d_corr_intraday_turn.md`](reversal_20d_corr_intraday_turn.md) | 0.0724 | 6.79 | **候选**：三项全库纪录 |
| 2026-08-18 | 衍生：`momentum_20d_cumret_turn` | 批次3轮20：A2 cumret 核心×条件化，见 [`momentum_20d_cumret_turn.md`](momentum_20d_cumret_turn.md) | 0.0492 | 3.91 | **无效**：相对 cumret 无增益（条件化冗余） |
| 2026-08-18 | 衍生：`momentum_20d_volrank` | 批次3轮6：H3 波动率代理互换，见 [`momentum_20d_volrank.md`](momentum_20d_volrank.md) | 0.0422 | 3.52 | 边际：与换手率代理等价 |
| 2026-08-17 | `momentum_20d_turnrank_avg20`（初始） | 挖因子轮 10：H3 换手率平滑 20 日 | 0.0416 | 3.33 | 无效：与快照版等价 |

## 6. 风险与备注

- **确认价值**：换手率条件化的时间结构（快照 vs 平滑）不影响结果——
  信息在横截面 rank 层面已饱和；未来迭代不要再改换手率平滑窗口。
- 种子 [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md) 为换手率条件化
  反转基准（观察中）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
