---
xname: reversal_5d_turn
formula: |
  signal = (close/close[t-5]-1) * cs_rank(turnover)
tags: [mine_b3r24, reversal, near5, turnover_conditional, marginal]
params: {}
status: 观察中（spread 近翻倍、IC 持平）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_5d_turn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_5d_turn`（= `factor/reversal_5d_turn.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（spread +92%、IC 持平） |
| 标签 | mine_b3r24, reversal, near5, turnover_conditional, marginal |
| 创建 | 2026-08-18（批次 3 轮次 24，种子 `reversal_20d_near5`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `reversal_20d_near5`（5 日单点反转弱）的假设 (N2) 5 日超调在
投机子样本（高换手）更强——换手率条件化（20 日核心已证 spread+30%）。

**数学表达**：

```
signal = (close/close[t-5] - 1) × cs_rank(turnover)
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
name: reversal_5d_turn
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
  from polars_ta.prefix.wq import ts_delay, cs_rank
  signal = (close / ts_delay(close, 5) - 1) * cs_rank(turnover)
```

## 4. 验证结果

> 数据快照自 `results/reversal_5d_turn/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 181 |
| 平均股票数 | 4885 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0283 |
| t 值 | 2.32 |
| IR | 0.172 |
| 近 26 周 mean / t | -0.0170 / -0.59 |

| 项 | 值 |
|----|----|
| spread | 0.00292 |
| D1 / D10 | 0.00152 / -0.00140 |

### 判定

- vs near5（无条件化）：IC 0.0283（0.0290 持平）、**spread 0.00292（0.00152，
  **+92%**）**——条件化大幅增强 5 日核心的档位区分（与 20 日核心同构）。
- vs turnrank（20 日）：IC 0.0283（0.0419）仍低——5 日信息上限限制整体。
- 结论：**观察中（边际）**——投机条件化在 5 日核心上同样有效（档位层面），
  但 5 日尺度信息不足（批次 2 轮 3 证伪近端驱动一致）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_5d_turn`（初始） | 批次 3 轮 24：N2 换手率条件化 | 0.0283 | 2.32 | 观察中：spread+92%、IC 持平 |

## 6. 风险与备注

- **条件化普适性**：换手率条件化在 5 日与 20 日核心上都增强档位区分——
  投机-反转交互是跨尺度的；IC 上限由核心尺度决定。
- 种子 [`reversal_20d_near5.md`](reversal_20d_near5.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
