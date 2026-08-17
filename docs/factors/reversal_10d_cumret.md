---
xname: reversal_10d_cumret
formula: |
  signal = ts_sum(returns(close), 10)
tags: [mine_b3r22, reversal, cumret_10d, spectrum_peak]
params: {}
status: 无效（20 日是 cumret 谱峰）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_10d_cumret 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_10d_cumret`（= `factor/reversal_10d_cumret.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——20 日确认是 cumret 谱峰 |
| 标签 | mine_b3r22, reversal, cumret_10d, spectrum_peak |
| 创建 | 2026-08-18（批次 3 轮次 22，种子 `momentum_20d_turnrank`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：cumret（累计收益）定义下的窗口谱峰定位——MA 锚谱已测（20-60 日），
累计收益更纯可能峰更短。检验 10 日。

**数学表达**：

```
signal = Σ returns(close) over 10d
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
name: reversal_10d_cumret
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
  signal = ts_sum(returns(close), 10)
```

## 4. 验证结果

> 数据快照自 `results/reversal_10d_cumret/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 180 |
| 平均股票数 | 4884 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0394 |
| t 值 | 3.36 |
| IR | 0.251 |
| 近 26 周 mean / t | -0.0303 / -1.07 |

| 项 | 值 |
|----|----|
| spread | 0.00214 |
| D1 / D10 | 0.00122 / -0.00092 |

### 判定

- vs cumret20（谱峰候选）：IC 0.0394（0.0503，**-22%**）、t 3.36（4.17）、
  spread 0.00214（0.00422，-49%）。
- 结论：**无效（谱峰确认）**——**20 日是累计收益定义下的谱峰**；
  10 日累计收益噪声大（10 日内日收益波动的噪声未充分平均）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_10d_cumret`（初始） | 批次 3 轮 22：C2 10 日累计 | 0.0394 | 3.36 | 无效：20 日是谱峰 |

## 6. 风险与备注

- **谱峰结论**：cumret 定义下 20 日最优（与 MA 锚谱的 20 日峰一致）；
  反转谱峰在两个定义下均为 ~20 日。窗口变异收束于 20 日。
- 基准 [`reversal_20d_cumret.md`](reversal_20d_cumret.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
