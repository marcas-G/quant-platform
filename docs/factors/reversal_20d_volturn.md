---
xname: reversal_20d_volturn
formula: |
  signal = (MA(close,20)/close[t-20]-1) * ts_rank(volume,20) * cs_rank(turnover)
tags: [mine_b3r2, reversal, vol_turn_orthogonal, spread_best]
params: {}
status: 观察中（spread 超两父本、IC 居中）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_volturn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_volturn`（= `factor/reversal_20d_volturn.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（spread 超两父本） |
| 标签 | mine_b3r2, reversal, vol_turn_orthogonal, spread_best |
| 创建 | 2026-08-18（批次 3 轮次 2，种子 `reversal_20d_volconf`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `reversal_20d_volconf` 的假设 (V3) 时序量能确认与横截面换手率
条件化正交可叠加——两个维度已验证单独有效（volconf spread+19%、turnrank
spread+30%），叠加检验。

**核心逻辑**：20 日反转 × 时序量能确认 × 横截面换手率条件化（双重条件化）。

**数学表达**：

```
signal = (MA(close,20)/close[t-20] - 1) × ts_rank(volume,20) × cs_rank(turnover)
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
name: reversal_20d_volturn
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, ts_rank, cs_rank
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * ts_rank(volume, 20) * cs_rank(turnover)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_volturn/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 174 |
| 平均股票数 | 4875 |
| 信号缺失率 | 0.0942 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0366 |
| t 值 | 3.25 |
| IR | 0.246 |
| 近 26 周 mean / t | -0.0058 / -0.20 |
| PearsonIC mean | -0.0295（t=-2.99） |

| 项 | 值 |
|----|----|
| spread | 0.00473 |
| D1 / D10 | 0.00243 / -0.00230 |

### 判定

- vs volconf（父 1）：IC 0.0366（0.0350，+5%）、spread 0.00473（0.00430，+10%）。
- vs turnrank（父 2）：IC 0.0366（0.0419，-13%）、spread 0.00473（0.00470，持平）。
- 结论：**观察中**——双重条件化 spread 超两父本（正交叠加有效），
  但 IC 未超 turnrank；两条件化因子组合使两端档位更极端（D10 -0.00230）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_volturn`（初始） | 批次 3 轮 2：V3 换手率条件化叠加 | 0.0366 | 3.25 | 观察中：spread 超两父本 |

## 6. 风险与备注

- 与 [`reversal_20d_volconf.md`](reversal_20d_volconf.md)（父 1）和
  [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md)（父 2）同源。
- 双重条件化后有效样本收窄（两条件同时高的股票），容量注意。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
