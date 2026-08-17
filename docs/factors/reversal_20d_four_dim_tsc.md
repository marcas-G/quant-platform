---
xname: reversal_20d_four_dim_tsc
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(corr10) + cs_rank(intraday20)
tags: [mine_b3r64, reversal, four_dim_tsc, near_record]
params: {}
status: 候选（接近全库最强，近 26 周更强）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim_tsc 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim_tsc`（= `factor/reversal_20d_four_dim_tsc.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（IC 0.0710 接近全库最强；近 26 周更强） |
| 标签 | mine_b3r64, reversal, four_dim_tsc, near_record |
| 创建 | 2026-08-18（批次 3 轮次 64，种子 `reversal_20d_near5`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：四维替代构成——turn/skew/corr10/intraday（skew 替代 vol）。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(corr10) + cs_rank(intraday20)
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
name: reversal_20d_four_dim_tsc
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
  from polars_ta.prefix.wq import ts_skewness, ts_corr, ts_delta, ts_sum, cs_rank
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim_tsc/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0710 |
| t 值 | 7.11 |
| IR | 0.533 |
| 近 26 周 mean / t | 0.0417 / 1.42 |
| PearsonIC mean | -0.0220（t=-2.51） |

| 项 | 值 |
|----|----|
| spread | 0.00429 |
| D1 / D10 | 0.00312 / -0.00117 |

### 判定

- vs turn_skew_corr（三维）：IC +8%（0.0656→0.0710）。
- vs four_dim10（原纪录）：IC 0.0710（0.0721，-1.5%）、t 7.11（7.40）、
  IR 0.533（0.555）——**接近全库最强**；**近 26 周 t=1.42（1.34）更强**。
- 结论：**候选**——skew 替代 vol 构成：全期略低、近期更强；
  两构成互为补充（近/全期偏好）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim_tsc`（初始） | 批次 3 轮 64：F3 替代四维 | 0.0710 | 7.11 | 候选：接近全库最强 |

## 6. 风险与备注

- **构成对照**：vol 构成全期最优、skew 构成近期更强——
  实盘化按近期环境选择；五维（+skew）已证饱和（轮 41）。
- 基准 [`reversal_20d_four_dim10.md`](reversal_20d_four_dim10.md)（全库最强）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
