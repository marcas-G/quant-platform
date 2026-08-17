---
xname: momentum_20d_cumret_turn
formula: |
  signal = ts_sum(returns(close), 20) * cs_rank(ts_mean(turnover, 20))
tags: [mine_b3r20, reversal, cumret_turn, no_additive_gain]
params: {}
status: 无效（相对 cumret 新基准无增益）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_cumret_turn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_cumret_turn`（= `factor/momentum_20d_cumret_turn.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——条件化在累计收益核心上无叠加增益 |
| 标签 | mine_b3r20, reversal, cumret_turn, no_additive_gain |
| 创建 | 2026-08-18（批次 3 轮次 20，种子 `momentum_20d_turnrank_avg20`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：cumret 新基准（轮 18，IC 0.0503）× 换手率条件化（turnrank spread+30%）
——两改进叠加检验。

**数学表达**：

```
signal = Σ returns(close) over 20d × cs_rank(MA(turnover, 20))
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
name: momentum_20d_cumret_turn
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
  from polars_ta.prefix.wq import ts_sum, ts_mean, cs_rank
  signal = ts_sum(returns(close), 20) * cs_rank(ts_mean(turnover, 20))
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_cumret_turn/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0492 |
| t 值 | 3.91 |
| IR | 0.293 |
| 近 26 周 mean / t | -0.0168 / -0.55 |
| PearsonIC mean | -0.0282（t=-2.52） |

| 项 | 值 |
|----|----|
| spread | 0.00427 |
| D1 / D10 | 0.00189 / -0.00238 |

### 判定

- vs cumret（新基准）：IC 0.0492（0.0503，-2% 持平）、t 3.91（4.17 略降）、
  spread 0.00427（0.00422 持平）。
- vs turnrank（MA 锚条件化）：IC +17%（0.0419→0.0492）——**条件化增益
  在累计收益核心上消失**（秩次信息已被强核心覆盖）。
- 结论：**无效（相对新基准无增益）**——cumret 核心本身已含条件化
  所捕捉的秩次信息；换手率条件化只在 MA 锚（信息不足）核心上有增益。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `momentum_20d_cumret_turn`（初始） | 批次 3 轮 20：A2 cumret 核心 × 条件化 | 0.0492 | 3.91 | 无效：相对 cumret 无增益 |

## 6. 风险与备注

- **叠加结论**：cumret 是反转家族最优核心（0.0503）；条件化/量能确认等
  增益在 MA 锚上有效、在 cumret 上冗余——**后续反转家族变异以 cumret
  为核心做独立表达探索**，不做条件化叠加。
- 种子 [`momentum_20d_turnrank_avg20.md`](momentum_20d_turnrank_avg20.md)；
  新基准 [`reversal_20d_cumret.md`](reversal_20d_cumret.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
