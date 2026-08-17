---
xname: reversal_20d_turn_skew_corr
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(corr10)
tags: [mine_b3r63, reversal, three_dim_tsc, record, recent_strong]
params: {}
status: 候选（强候选：三维 IC 纪录 0.0656）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_turn_skew_corr 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_turn_skew_corr`（= `factor/reversal_20d_turn_skew_corr.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强候选：三维 IC 纪录 0.0656、近 26 周 t=1.72） |
| 标签 | mine_b3r63, reversal, three_dim_tsc, record, recent_strong |
| 创建 | 2026-08-18（批次 3 轮次 63，种子 `momentum_20d_decile`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：投机（turn）× 彩票（skew）× 量价结构（corr10）三维秩次加法。

**数学表达**：

```
signal = cs_rank(turnover) + cs_rank(skewness(returns, 20)) + cs_rank(corr10)
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
name: reversal_20d_turn_skew_corr
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
  from polars_ta.prefix.wq import ts_skewness, ts_corr, ts_delta, cs_rank
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_turn_skew_corr/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0656（三维纪录） |
| t 值 | 6.75 |
| IR | 0.506 |
| 近 26 周 mean / t | 0.0499 / 1.72（**近期最强**） |
| PearsonIC mean | -0.0187（t=-2.31） |

| 项 | 值 |
|----|----|
| spread | 0.00335 |
| D1 / D10 | 0.00304 / -0.00030 |

### 判定

- vs turn_skew（父 1）：IC +4%（0.0633→0.0656）、t 6.75（5.74，+18%）、
  IR 0.506（0.430）。
- vs 原三维纪录（corr_flow_intraday 0.0607）：IC +8%。
- **近 26 周 t=1.72（全库近期最强）**。
- 结论：**候选（强候选）**——投机/彩票/结构三维高度互补；
  近四维组合（0.0721）一步之遥。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_turn_skew_corr`（初始） | 批次 3 轮 63：T3 三维加法 | 0.0656 | 6.75 | **强候选**：三维 IC 纪录 |

## 6. 风险与备注

- **三维最优集**：turn/skew/corr10（投机+彩票+结构）——近期最强；
  四维组合（corr10/intraday/turn/vol）全期最强（0.0721）。
- 基准 [`reversal_20d_turn_skew.md`](reversal_20d_turn_skew.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
