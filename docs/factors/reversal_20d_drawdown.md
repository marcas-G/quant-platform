---
xname: reversal_20d_drawdown
formula: |
  signal = close / ts_max(high, 20) - 1   # direction=-1（跌深端做多）
tags: [mine_b3r49, reversal, drawdown, falsified, direction_fix]
params: {}
status: 无效（回撤反转不成立）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_drawdown 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_drawdown`（= `factor/reversal_20d_drawdown.yaml`） |
| 类别 | custom |
| 方向 | `-1`（跌深端=D1 做多档） |
| 状态 | 无效——回撤反转不成立 |
| 标签 | mine_b3r49, reversal, drawdown, falsified, direction_fix |
| 创建 | 2026-08-18（批次 3 轮次 49，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：回撤结构（距 20 日高点距离）独立反转信息——跌深反弹假设。

**实现过程**：
1. 初版 direction=1（错误）：审核 subagent 实测抓出——direction=1 做多
   高信号端（追高），与跌深做多相反；平台实证 IC=-0.85（完美跌深世界）。
2. 修正 direction=-1（跌深端做多）：IC=-0.016（t=-1.20）不显著。

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
name: reversal_20d_drawdown
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
  from polars_ta.prefix.wq import ts_max
  signal = close / ts_max(high, 20) - 1
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_drawdown/summary.json`（direction 修正版，2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0160 |
| t 值 | -1.20 |
| IR | -0.090 |
| 近 26 周 mean / t | -0.0537 / -1.56 |

| 项 | 值 |
|----|----|
| spread | -0.00219 |
| D1 / D10 | 0.00135 / 0.00354 |

### 判定

- direction 修正后 IC=-0.016（t=-1.20）——**回撤反转不成立**：
  跌深股未来收益不反弹（下跌延续），距高点距离与收益维度冗余或反向。
- 结论：**无效（R2' 否定）**——回撤结构不携带独立反转信息；
  反转信息在收益/日内成分维度（距高点距离被收益吸收）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_drawdown`（初始） | 批次 3 轮 49：R2 回撤结构 | -0.0160 | -1.20 | 无效：回撤无反转信息 |

## 6. 风险与备注

- **方向语义经验**：direction=1 做多高信号端——设计"低信号做多"类因子
  必须 direction=-1（审核 subagent 实测确认平台语义）。
- 种子 [`vol_run_energy.md`](vol_run_energy.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
