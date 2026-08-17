---
xname: reversal_20d_corr_flow
formula: |
  signal = cs_rank(corr10) + cs_rank(netflow20)
tags: [mine_b3r58, reversal, corr_flow, complementary]
params: {}
status: 候选（IC 超两父本）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_flow 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_flow`（= `factor/reversal_20d_corr_flow.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（IC 0.0531 超两父本） |
| 标签 | mine_b3r58, reversal, corr_flow, complementary |
| 创建 | 2026-08-18（批次 3 轮次 58，种子 `momentum_20d_decile`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量维度组合矩阵补全——corr（结构）× netflow（方向加权）。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(Σ(amount×sign(returns), 20))
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
name: reversal_20d_corr_flow
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(amount * sign(returns(close)), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_flow/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0531 |
| t 值 | 6.25 |
| IR | 0.469 |
| 近 26 周 mean / t | 0.0120 / 0.56 |

| 项 | 值 |
|----|----|
| spread | 0.00364 |
| D1 / D10 | 0.00271 / -0.00093 |

### 判定

- vs corr10（父 1）：IC +21%（0.0439→0.0531）、IR 0.469（0.481 略降）。
- vs netflow（父 2）：IC +27%、t +25%。
- **IC 超两父本**——量维度间存在互补（量价结构 vs 资金方向加权）。
- 结论：**候选**——corr×flow 组合有效；量维度组合并非全部冗余
  （轮 39 的 symrun×corr 耦合特例）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_flow`（初始） | 批次 3 轮 58：C3 corr×flow | 0.0531 | 6.25 | 候选：IC 超两父本 |

## 6. 风险与备注

- **组合矩阵修正**：量维度组合（corr×flow）有效——组合可行性的判据是
  结构差异（结构相关 vs 方向累计），非单纯"量 vs 价"。
- 基准 [`reversal_20d_pricevolcorr10.md`](reversal_20d_pricevolcorr10.md)、
  [`reversal_20d_netflow.md`](reversal_20d_netflow.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
