---
xname: reversal_20d_five_dim_tsvf
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(vol10) + cs_rank(corr10) + cs_rank(flow30)
tags: [mine_b3r99, reversal, five_dim_tsvf, intraday_better]
params: {}
status: 无效（intraday 维度更优）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_five_dim_tsvf 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_five_dim_tsvf`（= `factor/reversal_20d_five_dim_tsvf.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——intraday 维度更优 |
| 标签 | mine_b3r99, reversal, five_dim_tsvf, intraday_better |
| 创建 | 2026-08-18（批次 3 轮次 99，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：tsv10 五维的 intraday → flow30 替换（构成变体）。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(vol10) + cs_rank(corr10) + cs_rank(flow30)
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
name: reversal_20d_five_dim_tsvf
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
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_rank(volume, 10)) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(amount * sign(returns(close)), 30))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_five_dim_tsvf/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0700 |
| t 值 | 7.48 |
| IR | 0.564 |
| 近 26 周 mean / t | 0.0423 / 1.45 |

| 项 | 值 |
|----|----|
| spread | 0.00456 |
| D1 / D10 | 0.00312 / -0.00144 |

### 判定

- vs tsv10（intraday 版）：IC 0.0700（0.0707，-1%）、t 7.48（7.58）、
  IR 0.564（0.568）——**flow30 替换全面略降**。
- 结论：**无效**——intraday 维度贡献优于 flow（轮 71 确认 +9% 延续）；
  tsv10 五维保持（稳定性纪录）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_five_dim_tsvf`（初始） | 批次 3 轮 99：F3 flow30 替换 | 0.0700 | 7.48 | 无效：intraday 更优 |

## 6. 风险与备注

- **构成定稿**：tsv10（含 intraday）五维为稳定性纪录——
  flow 替换方向关闭。
- 基准 [`reversal_20d_five_dim_tsv10.md`](reversal_20d_five_dim_tsv10.md)
  （稳定性纪录 7.58/0.568）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
