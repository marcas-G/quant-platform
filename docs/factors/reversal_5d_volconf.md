---
xname: reversal_5d_volconf
formula: |
  signal = (close/close[t-5]-1) * ts_rank(volume, 20)
tags: [mine_b3r10, reversal, near_end, volume_confirm, improved]
params: {}
status: 观察中（近端+确认改善但未超 20 日家族）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_5d_volconf 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_5d_volconf`（= `factor/reversal_5d_volconf.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（近端反转被量能确认改善） |
| 标签 | mine_b3r10, reversal, near_end, volume_confirm, improved |
| 创建 | 2026-08-18（批次 3 轮次 10，种子 `reversal_20d_near5`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `reversal_20d_near5`（近端反转弱，t=2.44）的假设 (N2)
近端信号弱因缩量样本污染。检验"近端超调需放量确认"：加 `× ts_rank(volume, 20)`。

**数学表达**：

```
signal = (close/close[t-5] - 1) × ts_rank(volume, 20)
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
name: reversal_5d_volconf
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
  from polars_ta.prefix.wq import ts_delay, ts_rank
  signal = (close / ts_delay(close, 5) - 1) * ts_rank(volume, 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_5d_volconf/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 177 |
| 平均股票数 | 4880 |
| 信号缺失率 | 0.0769 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0304 |
| t 值 | 2.84 |
| IR | 0.213 |
| 近 26 周 mean / t | -0.0073 / -0.30 |
| PearsonIC mean | -0.0226（t=-2.52） |

| 项 | 值 |
|----|----|
| spread | 0.00215 |
| D1 / D10 | 0.00082 / -0.00134 |

### 判定

- vs near5（无确认）：IC 0.0304（0.0290，+5%）、t 2.84（2.44，+16%）、
  **spread 0.00215（0.00152，+42%）**、IR 0.213（0.181）。
- vs 20 日家族（reversal_20d 0.0409）：仍弱（-26%）。
- 结论：**观察中**——N2'（缩量污染）部分支持：量能确认改善近端反转
  （尤其档位区分），但 5 日信号的信息上限低于 20 日 MA 锚（与批次 2 轮 3
  证伪结论一致：20 日尺度本身更优，量能确认只能部分补偿）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_5d_volconf`（初始） | 批次 3 轮 10：N2 量能确认 | 0.0304 | 2.84 | 观察中：改善但未超 20 日家族 |

## 6. 风险与备注

- **近端补偿有限**：量能确认只能部分补偿近端信号缺陷——20 日 MA 锚
  （平均成本语义）不可替代。
- 种子 [`reversal_20d_near5.md`](reversal_20d_near5.md)（证伪）；反转基准
  [`reversal_20d.md`](reversal_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
