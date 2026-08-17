---
xname: reversal_20d_four_dim_tsv
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(ts_rank(vol,20)) + cs_rank(corr10)
tags: [mine_b3r66, reversal, four_dim_tsv, stability_record]
params: {}
status: 候选（t/IR 全库新纪录：7.46/0.559）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim_tsv 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim_tsv`（= `factor/reversal_20d_four_dim_tsv.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（t=7.46/IR=0.559 全库新纪录） |
| 标签 | mine_b3r66, reversal, four_dim_tsv, stability_record |
| 创建 | 2026-08-18（批次 3 轮次 66，种子 `reversal_20d_volconf`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：四维构成补全——turn/skew/vol/corr10（tsv 三维 + 结构维度）。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(ts_rank(vol,20)) + cs_rank(corr10)
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
name: reversal_20d_four_dim_tsv
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
  from polars_ta.prefix.wq import ts_skewness, ts_rank, ts_corr, ts_delta, cs_rank
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_rank(volume, 20)) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim_tsv/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0661 |
| t 值 | 7.46（**全库新纪录**） |
| IR | 0.559（**全库新纪录**） |
| 近 26 周 mean / t | 0.0426 / 1.69（**近期最强**） |
| PearsonIC mean | -0.0217（t=-2.88） |

| 项 | 值 |
|----|----|
| spread | 0.00405 |
| D1 / D10 | 0.00316 / -0.00089 |

### 判定

- **t=7.46/IR=0.559 全库新纪录**（超 four_dim10 的 7.40/0.555）；
  **近 26 周 t=1.69 全库最强**。
- IC 0.0661（tsc 0.0710 低 7%、four_dim10 0.0721 低 8%）——
  skew 替代 intraday 构成：IC 让位于稳定性。
- 结论：**候选（稳定性全库最强）**——turn/skew/vol/corr 构成
  为稳定性最优集；IC 纪录仍 four_dim10（0.0721）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim_tsv`（初始） | 批次 3 轮 66：F3 四维加法 | 0.0661 | 7.46 | 候选：t/IR 全库新纪录 |

## 6. 风险与备注

- **构成谱系**：IC 最优 four_dim10（0.0721）、稳定性最优 four_dim_tsv
  （0.559）——实盘化按风险偏好选择。
- 基准 [`reversal_20d_four_dim10.md`](reversal_20d_four_dim10.md)（IC 纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
