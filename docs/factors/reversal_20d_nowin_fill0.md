---
xname: reversal_20d_nowin_fill0
formula: |
  signal = ts_mean(close, 20) / ts_delay(close, 20) - 1   # process: [standardize(), fillna(0)]
tags: [mine_b3r12, reversal, missing_fill, spread_collapse]
params: {}
status: 无效（fillna(0) 破坏分层）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_nowin_fill0 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_nowin_fill0`（= `factor/reversal_20d_nowin_fill0.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——中性填充破坏分层（缺失剔除是正确的） |
| 标签 | mine_b3r12, reversal, missing_fill, spread_collapse |
| 创建 | 2026-08-18（批次 3 轮次 12，种子 `reversal_20d_nowin`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子假设 (P3) 缺失行（7.23% 停牌补全）应被评估剔除。检验中性填充：
`fillna(value=0)` 把缺失信号填为 0（standardize 后 0=均值）扩大覆盖。

**数学表达**：

```
signal = MA(close,20)/close[t-20] - 1   → standardize → fillna(0)
```

## 3. 参数与实现

### 处理链

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2023-01-01 ~ 2026-07-31
process: [standardize(), fillna(value=0)]
target: forward_return_5d
adjustment: qfq
```

### 实现（YAML 全文）

```yaml
name: reversal_20d_nowin_fill0
category: custom
direction: -1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2023-01-01"
  end: "2026-07-31"
process:
  - standardize()
  - fillna(value=0)
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_delay
  signal = ts_mean(close, 20) / ts_delay(close, 20) - 1
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_nowin_fill0/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 4887 |
| 信号缺失率 | 0.0 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0401 |
| t 值 | 3.48 |
| IR | 0.258 |
| 近 26 周 mean / t | 0.0019 / 0.06 |
| PearsonIC mean | -0.0193（t=-1.94） |

| 项 | 值 |
|----|----|
| spread | -0.00007（**塌缩**） |
| D1 / D10 | 0.00267 / 0.00275（D10 被填充股污染） |

### 判定

- vs nowin（剔除）：IC 0.0401（0.0409）持平、t 3.48 持平、**spread 塌缩至
  ≈0**（0.00363 → -0.00007）：填充的 0 值（7.23% 停牌股）分层时聚集同一
  档位，D10 混入大量中性信号股票（真实未来收益为正），档位区分被破坏。
- 结论：**无效（重要负结果）**——缺失剔除是正确默认；中性填充不适用于
  分层评估（0 值聚集效应）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_nowin_fill0`（初始） | 批次 3 轮 12：P3 缺失填充 | 0.0401 | 3.48 | 无效：fillna(0) 破坏分层 |

## 6. 风险与备注

- **方法论结论**：缺失信号不得填充为同一常量（分层聚集效应）；
  若需扩大覆盖应使用逐股票填充（fillna(method=forward) 等），
  不做同一常量的横截面填充。
- 种子 [`reversal_20d_nowin.md`](reversal_20d_nowin.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
