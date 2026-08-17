---
xname: reversal_20d_corr_intraday
formula: |
  signal = cs_rank(corr(returns, d_vol, 20)) + cs_rank(sum(close/open-1, 20))
tags: [mine_b3r33, reversal, corr_intraday, balanced_best]
params: {}
status: 候选（强候选：综合平衡最优）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_intraday 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_intraday`（= `factor/reversal_20d_corr_intraday.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强候选：综合平衡最优） |
| 标签 | mine_b3r33, reversal, corr_intraday, balanced_best |
| 创建 | 2026-08-18（批次 3 轮次 33，种子 `momentum_20d_turnrank`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量价相关（结构维度，IR 0.477）× 日内核心（幅度维度，IC 0.0591）
正交组合——乘法已证伪（轮 23 符号翻转），采用**秩次加法**（cs_rank 等权相加，
无翻转：背离→做多、量价齐升+日内强→做空）。

**数学表达**：

```
signal = cs_rank(corr(returns, Δvol, 20)) + cs_rank(Σ(close/open - 1) over 20d)
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
name: reversal_20d_corr_intraday
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 20)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_intraday/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0581 |
| t 值 | 6.08 |
| IR | 0.456 |
| 近 26 周 mean / t | 0.0143 / 0.58 |
| PearsonIC mean | -0.0180（t=-2.16） |

| 项 | 值 |
|----|----|
| spread | 0.00378 |
| D1 / D10 | 0.00299 / -0.00079 |

### 判定

- **综合平衡最优**：IC 0.0581（IC 纪录 0.0604 的 96%）、t 6.08（IR 纪录 6.36 的 96%）、
  IR 0.456（IR 纪录 0.477 的 96%）、近 26 周 t=0.58——**三维度同时接近纪录**。
- vs 父本：IC 超 corr（0.0425）37%、t/IR 超 intraday（5.22/0.391）。
- 结论：**候选（强候选）**——量价结构 × 日内幅度的秩次加法组合
  同时获得水平与稳定性；近 26 周仍有效（t=0.58）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_intraday`（初始） | 批次 3 轮 33：M3 秩次加法组合 | 0.0581 | 6.08 | **强候选**：综合平衡最优 |

## 6. 风险与备注

- **组合方法论确认**：秩次加法（cs_rank 等权）优于乘法（符号翻转）——
  后续正交组合一律用秩次加法。
- **待做**：组合 × 换手率条件化（轮 27 增益）或 cs_rank 加权（非等权）。
- 父本 [`reversal_20d_pricevolcorr.md`](reversal_20d_pricevolcorr.md)（IR 纪录）、
  [`reversal_20d_intraday.md`](reversal_20d_intraday.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
