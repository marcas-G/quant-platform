---
xname: reversal_20d_five_dim_tsv
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(vol20) + cs_rank(corr10) + cs_rank(intraday20)
tags: [mine_b3r67, reversal, five_dim_tsv, composite_best]
params: {}
status: 候选（综合最优：t/IR 全库纪录 + IC 接近最强）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_five_dim_tsv 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_five_dim_tsv`（= `factor/reversal_20d_five_dim_tsv.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（综合最优：t=7.51/IR=0.563 全库纪录） |
| 标签 | mine_b3r67, reversal, five_dim_tsv, composite_best |
| 创建 | 2026-08-18（批次 3 轮次 67，种子 `reversal_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：tsv 四维（t/IR 纪录）五维扩展——轮 41 五维饱和是 vol 构成
结论；tsv 构成饱和点不同。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(ts_rank(vol,20)) + cs_rank(corr10) + cs_rank(intraday20)
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
name: reversal_20d_five_dim_tsv
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
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_rank(volume, 20)) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_five_dim_tsv/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0712（接近全库最强） |
| t 值 | 7.51（**全库新纪录**） |
| IR | 0.563（**全库新纪录**） |
| 近 26 周 mean / t | 0.0363 / 1.36 |
| PearsonIC mean | -0.0241（t=-2.88） |

| 项 | 值 |
|----|----|
| spread | 0.00511 |
| D1 / D10 | 0.00327 / -0.00183 |

### 判定

- vs tsv 四维：IC +8%（0.0661→0.0712）、t 7.51（7.46）、IR 0.563（0.559）。
- vs four_dim10（IC 纪录）：IC 0.0712（0.0721，-1.2%）、**t/IR 超**。
- **tsv 构成五维不饱和**（vol 构成五维饱和——轮 41 结论修正）；
  **当前综合最优**（IC 第二 + 稳定性第一）。
- 结论：**候选**——五维 tsv 为水平-稳定性平衡最优。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_five_dim_tsv`（初始） | 批次 3 轮 67：E3 五维加法 | 0.0712 | 7.51 | **候选**：综合最优 |

## 6. 风险与备注

- **饱和结论修正**：维度饱和取决于构成（vol 构成 4 维饱和、tsv 构成 5 维
  仍增益）——后续以 tsv 五维为基准探索六维。
- 基准 [`reversal_20d_four_dim_tsv.md`](reversal_20d_four_dim_tsv.md)（t/IR 前纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
