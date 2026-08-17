---
xname: reversal_20d_wskew_tsv10
formula: |
  signal = cs_rank(turn) + 2*cs_rank(skew20) + cs_rank(vol10) + cs_rank(corr10) + cs_rank(intraday20)
tags: [mine_b3r72, reversal, wskew, equal_better]
params: {}
status: 无效（等权更优）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_wskew_tsv10 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_wskew_tsv10`（= `factor/reversal_20d_wskew_tsv10.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——skew 加权稀释 |
| 标签 | mine_b3r72, reversal, wskew, equal_better |
| 创建 | 2026-08-18（批次 3 轮次 72，种子 `momentum_20d_decile`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：skew（近期强）双倍权重——近期表现加权测试。

**数学表达**：

```
signal = cs_rank(turn) + 2×cs_rank(skew20) + cs_rank(vol10) + cs_rank(corr10) + cs_rank(intraday20)
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
name: reversal_20d_wskew_tsv10
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
  signal = cs_rank(turnover) + 2 * cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_rank(volume, 10)) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_wskew_tsv10/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0657 |
| t 值 | 7.55 |
| IR | 0.566 |
| 近 26 周 mean / t | 0.0343 / 1.35 |

| 项 | 值 |
|----|----|
| spread | 0.00436 |
| D1 / D10 | 0.00319 / -0.00117 |

### 判定

- vs tsv10（等权）：IC 0.0657（0.0707，-7%）、t/IR 持平、近 26 周略降——
  **skew 双倍全面略降**（skew 的 IC 低于其他维度，加权稀释整体）。
- 结论：**无效**——等权保持；skew 不宜加权（其贡献在组合互补
  而非单独放大）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_wskew_tsv10`（初始） | 批次 3 轮 72：W2 skew 双倍 | 0.0657 | 7.55 | 无效：等权更优 |

## 6. 风险与备注

- **加权结论**：组合等权已近最优（skew/corr 加权均证伪）——
  权重优化方向关闭。
- 基准 [`reversal_20d_five_dim_tsv10.md`](reversal_20d_five_dim_tsv10.md)
  （稳定性纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
