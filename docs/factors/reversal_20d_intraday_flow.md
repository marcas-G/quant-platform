---
xname: reversal_20d_intraday_flow
formula: |
  signal = cs_rank(intraday20) + cs_rank(netflow20)
tags: [mine_b3r57, reversal, intraday_flow, marginal]
params: {}
status: 观察中（IR 超两父本、IC 居中）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_intraday_flow 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_intraday_flow`（= `factor/reversal_20d_intraday_flow.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（IR 0.397 超两父本、IC 居中） |
| 标签 | mine_b3r57, reversal, intraday_flow, marginal |
| 创建 | 2026-08-18（批次 3 轮次 57，种子 `reversal_20d_volconf`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：日内幅度 × 资金流秩次加法（部分重叠——netflow 含 sign(returns)）。

**数学表达**：

```
signal = cs_rank(Σ(close/open-1, 20)) + cs_rank(Σ(amount×sign(returns), 20))
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
name: reversal_20d_intraday_flow
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
  from polars_ta.prefix.wq import ts_sum, cs_rank
  signal = cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(ts_sum(amount * sign(returns(close)), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_intraday_flow/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0559 |
| t 值 | 5.29 |
| IR | 0.397 |
| 近 26 周 mean / t | 0.0072 / 0.25 |

| 项 | 值 |
|----|----|
| spread | 0.00489 |
| D1 / D10 | 0.00272 / -0.00217 |

### 判定

- vs intraday（父 1）：IC 0.0559（0.0591，-5%）、**t 5.29（5.22）**、
  **IR 0.397（0.391）**。
- vs netflow（父 2）：IC +34%、t +6%。
- 结论：**观察中（边际）**——资金流贡献稳定性（IR/t 超两父本）、
  IC 居中；与 intraday_skew（轮 54）模式一致。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_intraday_flow`（初始） | 批次 3 轮 57：N3 秩次加法 | 0.0559 | 5.29 | 观察中：IR 超两父本 |

## 6. 风险与备注

- **组合模式**：intraday 与其他维度组合普遍"IC 略降/IR 微升"——
  四维组合（含 intraday）仍是水平-稳定性最优平衡。
- 基准 [`reversal_20d_intraday.md`](reversal_20d_intraday.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
