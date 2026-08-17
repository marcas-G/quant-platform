---
xname: reversal_20d_volconf_fwd
formula: |
  signal = (MA(close,20)/close[t-20]-1) * ts_rank(volume,20)   # process + fillna(forward)
tags: [mine_b3r16, reversal, fillna_nan_noop, equivalent]
params: {}
status: 无效（fillna forward 对 NaN 无效果——等价确认）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_volconf_fwd 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_volconf_fwd`（= `factor/reversal_20d_volconf_fwd.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——fillna(method=forward) 未生效（NaN vs null） |
| 标签 | mine_b3r16, reversal, fillna_nan_noop, equivalent |
| 创建 | 2026-08-18（批次 3 轮次 16，种子 `reversal_20d_volconf`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子假设 (V3) 缺失行信息延续——前向填充（逐股票）是否优于剔除。
fill0（常量）已证伪（聚集破坏分层）；forward 无聚集问题。

**数学表达**：

```
signal = (MA(close,20)/close[t-20] - 1) × ts_rank(volume,20)
→ winsorize → standardize → fillna(method=forward)
```

## 3. 参数与实现

### 处理链

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2023-01-01 ~ 2026-07-31
process: [winsorize(quantile=0.99), standardize(), fillna(method=forward)]
target: forward_return_5d
adjustment: qfq
```

### 实现（YAML 全文）

```yaml
name: reversal_20d_volconf_fwd
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
  - fillna(method=forward)
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_delay, ts_rank
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * ts_rank(volume, 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_volconf_fwd/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 174 |
| 平均股票数 | 4875 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0350 |
| t 值 | 3.28 |
| IR | 0.249 |
| 近 26 周 mean / t | 0.0043 / 0.14 |

| 项 | 值 |
|----|----|
| spread | 0.00430 |
| D1 / D10 | 0.00274 / -0.00156 |

### 判定

- 与种子 volconf **逐位一致**（IC 0.0350、t 3.28、spread 0.00430 完全相同）——
  `fillna(method=forward)` **未生效**：standardize 输出的缺失是 **NaN**，
  平台 fillna 只处理 **null**（interface.md §459 已有说明），NaN 不被填充。
- 结论：**无效（无效果确认）**——处理链 fillna 对计算链 NaN 缺失无效；
  缺失行仍由评估层过滤。缺失治理只能走"计算链内处理"（公式层），
  处理链 fillna 是死路（除非平台扩展 NaN 处理）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_volconf_fwd`（初始） | 批次 3 轮 16：V3 前向填充 | 0.0350 | 3.28 | 无效：fillna 对 NaN 无效果 |

## 6. 风险与备注

- **平台行为确认**：fillna 只处理 null 不处理 NaN——缺失治理在公式层
  （如 ts_fill 类算子）而非处理链；未来迭代不在处理链 fillna 方向重复。
- 种子 [`reversal_20d_volconf.md`](reversal_20d_volconf.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
