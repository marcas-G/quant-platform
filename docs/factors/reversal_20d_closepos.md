---
xname: reversal_20d_closepos
formula: |
  signal = ts_mean((close-low)/(high-low+1e-6), 20)
tags: [mine_b3r29, reversal, close_position, no_power, limit_board_nan]
params: {}
status: 无效（收盘位置无预测力）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_closepos 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_closepos`（= `factor/reversal_20d_closepos.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——日内收盘位置无预测力 |
| 标签 | mine_b3r29, reversal, close_position, no_power, limit_board_nan |
| 创建 | 2026-08-18（批次 3 轮次 29，种子 `momentum_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：OHLC 最后未用维度——日内收盘位置（(close-low)/(high-low)，
收在高点=日内强势）。检验收盘位置效应（强势难持续→回落）。

**实现过程**：
1. 首次：无 ε → IC=0.0000（全 NaN——**一字板 high==low → 0/0 → NaN 传播**，
   ts_mean 窗口污染）。
2. 修复：分母 +1e-6（一字板位置=0）→ IC 0.0054（t=0.56）不显著。

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
name: reversal_20d_closepos
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
  from polars_ta.prefix.wq import ts_mean
  signal = ts_mean((close - low) / ((high - low) + 1e-6), 20)  # ε 防一字板 0/0
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_closepos/summary.json`（ε 修复版，2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0711 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0054 |
| t 值 | 0.56 |
| IR | 0.042 |
| 近 26 周 mean / t | -0.0123 / -0.58 |

| 项 | 值 |
|----|----|
| spread | 0.00188 |
| D1 / D10 | 0.00205 / 0.00017 |

### 判定

- IC 0.0054（t=0.56）——**收盘位置无预测力**：日内收盘位置横截面普遍
  集中于 0.4-0.6（涨跌随机），区分度低；收盘位置效应在 A 股 20 日均
  尺度不成立（与日内收益维度的反转形成对照）。
- 结论：**无效（P2' 否定）**——OHLC 位置维度无信息；
  反转信息在收益（尤其日内收益）维度，不在位置维度。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_closepos`（初始） | 批次 3 轮 29：P2 收盘位置 | 0.0054 | 0.56 | 无效：位置维度无信息 |

## 6. 风险与备注

- **平台经验**：high==low（一字板）的除法产生 NaN 并传播——
  公式中涉及 (high-low)/(open-close) 等除法需加 ε 防 0/0（本因子修复
  记录）。后续轮次直接采用 ε 防护。
- 种子 [`momentum_20d.md`](momentum_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
