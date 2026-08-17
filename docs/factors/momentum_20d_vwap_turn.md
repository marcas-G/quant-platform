---
xname: momentum_20d_vwap_turn
formula: |
  signal = (MA(vwap,20)/vwap[t-20]-1) * cs_rank(turnover)
tags: [mine_b3r9, reversal, vwap_turn_combo, spread_record]
params: {}
status: 候选（spread 全库最高）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_vwap_turn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_vwap_turn`（= `factor/momentum_20d_vwap_turn.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（spread 0.76%/周 全库最高） |
| 标签 | mine_b3r9, reversal, vwap_turn_combo, spread_record |
| 创建 | 2026-08-18（批次 3 轮次 9，种子 `momentum_20d_vwap`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `momentum_20d_vwap` 的假设 (V3) VWAP 口径与换手率条件化正交
可叠加——两维度单独有效（vwap spread+78%、turnrank spread+30%），叠加检验。

**核心逻辑**：20 日 VWAP 反转 × 横截面换手率条件化（尾盘操纵免疫 + 投机
强度聚焦双重精确化）。

**数学表达**：

```
signal = (MA(amount/volume, 20) / vwap[t-20] - 1) × cs_rank(turnover)
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
name: momentum_20d_vwap_turn
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
  _vwap = amount / volume
  signal = (ts_mean(_vwap, 20) / ts_delay(_vwap, 20) - 1) * cs_rank(turnover)
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_vwap_turn/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 174 |
| 平均股票数 | 4875 |
| 信号缺失率 | 0.0942 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0411 |
| t 值 | 3.41 |
| IR | 0.259 |
| 近 26 周 mean / t | -0.0114 / -0.47 |
| PearsonIC mean | nan（t=0.00） |

| 项 | 值 |
|----|----|
| spread | 0.00756（0.76%/周，全库最高） |
| D1 / D10 | 0.00410 / -0.00346 |

### 判定

- vs vwap（父 1）：IC 0.0411（0.0390，+5%）、spread 0.00756（0.00646，+17%）。
- vs turnrank（父 2）：IC 0.0411（0.0419，-2%）、spread 0.00756（0.00470，**+61%**）。
- **spread 全库最高（0.76%/周，阈值 0.2% 的 3.8 倍）**；IC 0.041 显著。
- 近 26 周 t=-0.47（与 20 日反转家族同步衰减）。
- 结论：**候选**——VWAP 口径 × 换手率条件化叠加有效，档位区分最强；
  下一步正交性/容量分析。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `momentum_20d_vwap_turn`（初始） | 批次 3 轮 9：V3 换手率条件化叠加 | 0.0411 | 3.41 | **候选**：spread 全库最高 |

## 6. 风险与备注

- **近 26 周衰减**：t=-0.47，与反转家族一致。
- **双重条件化容量**：vwap 口径 + 高换手条件化后有效样本收窄。
- 与 [`momentum_20d_vwap.md`](momentum_20d_vwap.md)（父 1）、
  [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md)（父 2）、
  [`reversal_20d_volturn.md`](reversal_20d_volturn.md)（同构组合）相关。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
