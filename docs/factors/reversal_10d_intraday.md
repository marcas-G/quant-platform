---
xname: reversal_10d_intraday
formula: |
  signal = ts_sum(close/open - 1, 10)
tags: [mine_b3r28, reversal, intraday_10d, spectrum_peak]
params: {}
status: 无效（日内谱峰同为 20 日）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_10d_intraday 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_10d_intraday`（= `factor/reversal_10d_intraday.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——日内谱峰同为 20 日 |
| 标签 | mine_b3r28, reversal, intraday_10d, spectrum_peak |
| 创建 | 2026-08-18（批次 3 轮次 28，种子 `reversal_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：日内反转（高开低走）是超短期现象，可能比混合累计（20 日峰）
更短——日内谱峰定位（10 日）。

**数学表达**：

```
signal = Σ (close/open - 1) over 10d
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
name: reversal_10d_intraday
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
  from polars_ta.prefix.wq import ts_sum
  signal = ts_sum(close/open - 1, 10)
```

## 4. 验证结果

> 数据快照自 `results/reversal_10d_intraday/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 180 |
| 平均股票数 | 4884 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0503 |
| t 值 | 4.49 |
| IR | 0.335 |
| 近 26 周 mean / t | -0.0248 / -0.93 |

| 项 | 值 |
|----|----|
| spread | 0.00442 |
| D1 / D10 | 0.00228 / -0.00214 |

### 判定

- vs intraday20（纪录）：IC 0.0503（0.0591，-15%）、t 4.49（5.22）、
  spread 0.00442（0.00556，-20%）。
- 结论：**无效（谱峰确认）**——日内成分的谱峰同为 **20 日**（与混合累计
  cumret 一致）：日内反转信号也需要 ~20 日累计来平滑日间噪声；
  10 日累计噪声大。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`reversal_10d_intraday_extreme` | 批次4轮4：I3 极端换手聚焦，见 [`reversal_10d_intraday_extreme.md`](reversal_10d_intraday_extreme.md) | 0.0537 | 8.20 | **强候选**：t/IR 近翻倍、spread 全库纪录 |
| 2026-08-18 | `reversal_10d_intraday`（初始） | 批次 3 轮 28：I2 10 日日内 | 0.0503 | 4.49 | 无效：日内谱峰同为 20 日 |

## 6. 风险与备注

- **谱峰统一结论**：混合/日内成分谱峰均为 20 日——窗口收束 20 日，
  后续不做窗口变异。
- 基准 [`reversal_20d_intraday.md`](reversal_20d_intraday.md)（纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
