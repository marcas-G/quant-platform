---
xname: momentum_20d_open
formula: |
  signal = ts_mean(open, 20) / ts_delay(open, 20) - 1
tags: [mine_b3r7, reversal, open_anchor, no_gain]
params: {}
status: 无效（open 与 close 动量同构，略弱）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_open 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_open`（= `factor/momentum_20d_open.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——open 与 close 动量同构（略弱） |
| 标签 | mine_b3r7, reversal, open_anchor, no_gain |
| 创建 | 2026-08-18（批次 3 轮次 7，种子 `momentum_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子隐含假设 (H3) close 与 open 携带同样的动量信息。检验 open 口径
（集合竞价/隔夜信息，无尾盘操纵污染）：20 日开盘价 MA 动量（反转方向）。
（原设计 neutralize 处理链变异因数据缺口改用本口径——见 §6。）

**数学表达**：

```
signal = MA(open, 20) / open[t-20] - 1
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
name: momentum_20d_open
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
  from polars_ta.prefix.wq import ts_mean, ts_delay
  signal = ts_mean(open, 20) / ts_delay(open, 20) - 1
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_open/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0386 |
| t 值 | 3.31 |
| IR | 0.248 |
| 近 26 周 mean / t | 0.0146 / 0.44 |
| PearsonIC mean | -0.0184（t=-1.79） |

| 项 | 值 |
|----|----|
| spread | 0.00355 |
| D1 / D10 | 0.00257 / -0.00098 |

### 判定

- vs reversal_20d（close 口径）：IC 0.0386（0.0409，-6%）、t 3.31（3.47）、
  spread 0.00355（0.00362，持平）。近 26 周 t=0.44（close 版 0.05）微好。
- 结论：**无效**——open 与 close 动量同构（20 日尺度上价格口径不改变
  秩次结构）；与批次 2 轮 2（vwap 口径 spread +78%）对照：
  close/vwap 的差异在日内（尾盘操纵在 20 日动量中被平滑）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `momentum_20d_open`（初始） | 批次 3 轮 7：H3 open 口径 | 0.0386 | 3.31 | 无效：与 close 动量同构 |

## 6. 风险与备注

- **数据缺口记录**：原设计 `neutralize(by=industry)` 不可用（stock_basic 行业
  字段覆盖不足 117,776 只）、`neutralize(by=size)` 不可用（daily_basic.total_mv
  缺失 219,225 只）——处理链中性化方向在现有数据上不可实现，后续轮次
  不再尝试（除非数据补齐）。
- 种子 [`momentum_20d.md`](momentum_20d.md)；反转基准
  [`reversal_20d.md`](reversal_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
