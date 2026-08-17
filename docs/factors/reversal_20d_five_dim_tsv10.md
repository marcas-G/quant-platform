---
xname: reversal_20d_five_dim_tsv10
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(vol10) + cs_rank(corr10) + cs_rank(intraday20)
tags: [mine_b3r70, reversal, five_dim_tsv10, stability_record]
params: {}
status: 候选（t/IR 全库新纪录：7.58/0.568）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_five_dim_tsv10 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_five_dim_tsv10`（= `factor/reversal_20d_five_dim_tsv10.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（t=7.58/IR=0.568 全库新纪录） |
| 标签 | mine_b3r70, reversal, five_dim_tsv10, stability_record |
| 创建 | 2026-08-18（批次 3 轮次 70，种子 `reversal_20d_volconf`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：五维 tsv 的 vol10 变体（短窗稳定性微调，轮 46 模式应用）。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(ts_rank(vol,10)) + cs_rank(corr10) + cs_rank(intraday20)
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
name: reversal_20d_five_dim_tsv10
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
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_rank(volume, 10)) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_five_dim_tsv10/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0707 |
| t 值 | 7.58（**全库新纪录**） |
| IR | 0.568（**全库新纪录**） |
| 近 26 周 mean / t | 0.0381 / 1.39 |

| 项 | 值 |
|----|----|
| spread | 0.00498 |
| D1 / D10 | 0.00313 / -0.00185 |

### 判定

- vs five_dim_tsv（vol20）：IC 0.0707（0.0712，-1%）、**t 7.58（7.51）**、
  **IR 0.568（0.563）**——vol10 微调稳定性（全库新纪录）。
- 结论：**候选**——tsv10 五维为当前稳定性最优；
  IC 纪录仍 four_dim10（0.0721）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_five_dim_tsv10`（初始） | 批次 3 轮 70：F2 vol10 | 0.0707 | 7.58 | 候选：t/IR 全库新纪录 |

## 6. 风险与备注

- **稳定性最优**：tsv10 五维（0.0707/7.58/0.568）——短窗（corr10/vol10）
  构成稳定性最强。
- 基准 [`reversal_20d_five_dim_tsv.md`](reversal_20d_five_dim_tsv.md)
  （综合最优 0.0712/7.51/0.563）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
