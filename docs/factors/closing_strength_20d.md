---
xname: closing_strength_20d
formula: |
  signal = ts_mean(close/(amount/volume) - 1, 20)
tags: [mine_b4r20, closing_strength, vwap_anchor, marginal]
params: {}
status: 观察中（边际显著；spread 高）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# closing_strength_20d 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `closing_strength_20d`（= `factor/closing_strength_20d.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（t=2.00 边际显著、spread 0.68%/周） |
| 标签 | mine_b4r20, closing_strength, vwap_anchor, marginal |
| 创建 | 2026-08-18（批次 4 轮次 20，种子 `momentum_20d_vwap`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**隐含假设深挖**：VWAP 全天均价锚隐含"收盘相对均价的偏离无信息"——
close vs VWAP 的位置 = **尾盘强度**（尾盘拉升/抛压，A 股特有行为）。

**数学表达**：

```
signal = MA(close/VWAP - 1, 20)   （VWAP = amount/volume）
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
name: closing_strength_20d
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
  signal = ts_mean(close / (amount / volume) - 1, 20)
```

## 4. 验证结果

> 数据快照自 `results/closing_strength_20d/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0175 |
| t 值 | 2.00 |
| IR | 0.150 |
| 近 26 周 mean / t | 0.0115 / 0.76 |
| PearsonIC mean | nan（t=0.00） |

| 项 | 值 |
|----|----|
| spread | 0.00684（0.68%/周） |
| D1 / D10 | 0.00510 / -0.00175 |

### 判定

- vs vwap（动量）：IC -55%（0.039→0.0175）、t 2.00（3.45）——尾盘强度
  弱于动量；**spread 0.68%/周 高**（档位区分强）。
- **边际显著（t=2.00）**：尾盘行为是独立弱信号（与反转/动量相关性待测）。
- 结论：**观察中（边际）**——尾盘强度为新增行为维度（弱但独立）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `closing_strength_20d`（初始） | 批次 4 轮 20：尾盘强度 | 0.0175 | 2.00 | 观察中：边际显著 |

## 6. 风险与备注

- **尾盘行为维度**：收盘相对均价位置携带独立弱信息——
  A 股尾盘行为（拉升/抛压）的新表达。
- 种子 [`momentum_20d_vwap.md`](momentum_20d_vwap.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
