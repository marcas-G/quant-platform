---
xname: reversal_20d_flow_skew
formula: |
  signal = cs_rank(flow20) + cs_rank(skew20)
tags: [mine_b3r61, reversal, flow_skew, complementary]
params: {}
status: 候选（IC 超两父本）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_flow_skew 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_flow_skew`（= `factor/reversal_20d_flow_skew.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（IC 0.0464 超两父本） |
| 标签 | mine_b3r61, reversal, flow_skew, complementary |
| 创建 | 2026-08-18（批次 3 轮次 61，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：资金流（方向加权）× 偏度（矩）秩次加法——组合矩阵补全。

**数学表达**：

```
signal = cs_rank(Σ(amount×sign(returns), 20)) + cs_rank(skewness(returns, 20))
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
name: reversal_20d_flow_skew
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
  from polars_ta.prefix.wq import ts_sum, ts_skewness, cs_rank
  signal = cs_rank(ts_sum(amount * sign(returns(close)), 20)) + cs_rank(ts_skewness(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_flow_skew/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0464 |
| t 值 | 5.75 |
| IR | 0.431 |
| 近 26 周 mean / t | 0.0093 / 0.42 |

| 项 | 值 |
|----|----|
| spread | 0.00323 |
| D1 / D10 | 0.00295 / -0.00028 |

### 判定

- vs flow（父 1）：IC +11%（0.0417→0.0464）、t +15%、IR 0.431（0.375）。
- vs skew（父 2）：IC +89%。
- 结论：**候选**——资金流与偏度部分互补（方向加权 vs 矩分布）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_flow_skew`（初始） | 批次 3 轮 61：F3 flow×skew | 0.0464 | 5.75 | 候选：IC 超两父本 |

## 6. 风险与备注

- **组合矩阵**：flow×skew 互补（方向 vs 矩）——与 corr×skew（冗余）
  对照：信息源差异决定组合可行性。
- 基准 [`reversal_20d_netflow.md`](reversal_20d_netflow.md)、
  [`reversal_20d_skew.md`](reversal_20d_skew.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
