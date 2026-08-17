---
xname: momentum_20d_turnrank_vol
formula: |
  signal = (MA(close,20)/close[t-20]-1) * cs_rank(turnover) * ts_rank(volume,20)
tags: [mine_b3r11, reversal, duplicate_commute]
params: {}
status: 无效（与 reversal_20d_volturn 数学等价——重复因子）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_turnrank_vol 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_turnrank_vol`（= `factor/momentum_20d_turnrank_vol.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——与 `reversal_20d_volturn` 数学等价（乘法交换律），重复因子 |
| 标签 | mine_b3r11, reversal, duplicate_commute |
| 创建 | 2026-08-18（批次 3 轮次 11，种子 `momentum_20d_turnrank`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：组合"换手率条件化 × 量能确认"（turnrank 侧对称验证）。
**发现**：`× cs_rank(turnover) × ts_rank(volume, 20)` 与
`× ts_rank(volume, 20) × cs_rank(turnover)`（reversal_20d_volturn）在
乘法交换律下**逐位等价**——本因子为重复因子，验证了组合的交换对称性。

**数学表达**：

```
signal = (MA(close,20)/close[t-20] - 1) × cs_rank(turnover) × ts_rank(volume, 20)
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
name: momentum_20d_turnrank_vol
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
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * cs_rank(turnover) * ts_rank(volume, 20)
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_turnrank_vol/summary.json`（2026-08-18）。

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

- 与 [`reversal_20d_volturn.md`](reversal_20d_volturn.md)（批次 3 轮 2）**逐位一致**
  （IC 0.0366、spread 0.00473、D1/D10 相同）——乘法交换律下数学等价。
- 结论：**无效（重复因子）**——不构成新信息；组合效果的权威记录在
  volturn 档案（观察中：spread 超两父本）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`momentum_20d_vol_extreme` | 批次4轮2：V4 极端放量掩码，见 [`momentum_20d_vol_extreme.md`](momentum_20d_vol_extreme.md) | 0.0221 | 3.84 | **无效**：量能信息连续分布 |
| 2026-08-18 | `momentum_20d_turnrank_vol`（初始） | 批次 3 轮 11：组合对称验证 | 0.0366 | 3.25 | 无效：与 volturn 数学等价（重复） |

## 6. 风险与备注

- **流程教训**：乘法组合因子存在交换对称性——组合类变异需先查已有组合
  （volturn/vwap_turn），避免重复。后续组合轮次只做未测的（如 vwap×vol）。
- 种子 [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
