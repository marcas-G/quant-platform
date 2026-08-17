---
xname: reversal_20d_wcorr_tsv10
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(vol10) + 2*cs_rank(corr10) + cs_rank(intraday20)
tags: [mine_b3r73, reversal, wcorr_tsv10, stability_record]
params: {}
status: 观察中（t/IR 全库新纪录、IC 略降）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_wcorr_tsv10 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_wcorr_tsv10`（= `factor/reversal_20d_wcorr_tsv10.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（t=7.65/IR=0.574 全库新纪录、IC 略降） |
| 标签 | mine_b3r73, reversal, wcorr_tsv10, stability_record |
| 创建 | 2026-08-18（批次 3 轮次 73，种子 `reversal_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：tsv10 五维的 corr 双倍权重（高稳定维度加权，轮 42 模式）。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(vol10) + 2×cs_rank(corr10) + cs_rank(intraday20)
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
name: reversal_20d_wcorr_tsv10
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
  from polars_ta.prefix.wq import ts_skewness, ts_rank, ts_corr, ts_delta, ts_sum, cs_rank
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_rank(volume, 10)) + 2 * cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_wcorr_tsv10/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0683 |
| t 值 | 7.65（**全库新纪录**） |
| IR | 0.574（**全库新纪录**） |
| 近 26 周 mean / t | 0.0336 / 1.38 |

| 项 | 值 |
|----|----|
| spread | 0.00465 |
| D1 / D10 | 0.00333 / -0.00131 |

### 判定

- vs tsv10（等权）：IC 0.0683（0.0707，-3%）、**t 7.65（7.58）**、
  **IR 0.574（0.568）**——corr 加权微升稳定性（轮 42 模式）。
- 结论：**观察中（边际）**——t/IR 全库新纪录但 IC 略降；
  等权仍综合最优（skew 加权证伪、corr 加权边际）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_wcorr_tsv10`（初始） | 批次 3 轮 73：C2 corr 双倍 | 0.0683 | 7.65 | 观察中：t/IR 新纪录 |

## 6. 风险与备注

- **加权结论**：corr 加权（稳定性微升）vs skew 加权（稀释）——
  加权方向仅在最高 IR 维度有效；等权仍推荐。
- 基准 [`reversal_20d_five_dim_tsv10.md`](reversal_20d_five_dim_tsv10.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
