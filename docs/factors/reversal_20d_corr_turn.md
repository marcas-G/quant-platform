---
xname: reversal_20d_corr_turn
formula: |
  signal = cs_rank(corr10) + cs_rank(turnover)
tags: [mine_b3r76, reversal, corr_turn, strong, recent_record]
params: {}
status: 候选（强候选：IC 0.0691、近 26 周 t=1.85 全库最强）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_turn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_turn`（= `factor/reversal_20d_corr_turn.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强候选：IC 0.0691、近 26 周 t=1.85 全库最强） |
| 标签 | mine_b3r76, reversal, corr_turn, strong, recent_record |
| 创建 | 2026-08-18（批次 3 轮次 76，种子 `momentum_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：结构（量价相关）× 投机（换手率）秩次加法——组合矩阵补全。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turnover)
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
name: reversal_20d_corr_turn
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_turn/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 180 |
| 平均股票数 | 4884 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0691 |
| t 值 | 6.33 |
| IR | 0.472 |
| 近 26 周 mean / t | 0.0594 / 1.85（**全库近期最强**） |
| PearsonIC mean | -0.0195（t=-2.14） |

| 项 | 值 |
|----|----|
| spread | 0.00399 |
| D1 / D10 | 0.00307 / -0.00092 |

### 判定

- vs corr10（父 1）：IC **+57%**（0.0439→0.0691）。
- vs turnrank（父 2）：IC **+65%**。
- **近 26 周 t=1.85（全库近期最强纪录）**——结构×投机信号
  2026 年高度有效。
- 结论：**候选（强候选）**——结构×投机高度互补；
  可作为五维组合的替代核心（IC 接近四维 0.0721）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_turn`（初始） | 批次 3 轮 76：C3 corr×turn | 0.0691 | 6.33 | **强候选**：IC 超两父本 |

## 6. 风险与备注

- **组合图景**：corr×turn（结构×投机）与 turn×skew（投机×彩票）均为
  强互补组合——投机维度与其他维度组合价值高。
- 基准 [`reversal_20d_pricevolcorr10.md`](reversal_20d_pricevolcorr10.md)、
  [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
