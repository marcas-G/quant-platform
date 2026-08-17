---
xname: reversal_20d_four_dim_tsv10
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(vol10) + cs_rank(corr10)
tags: [mine_b3r71, reversal, four_dim_tsv10, intraday_contrib]
params: {}
status: 无效（intraday 贡献确认：五维更优）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim_tsv10 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim_tsv10`（= `factor/reversal_20d_four_dim_tsv10.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——intraday 维度贡献确认（五维更优） |
| 标签 | mine_b3r71, reversal, four_dim_tsv10, intraday_contrib |
| 创建 | 2026-08-18（批次 3 轮次 71，种子 `reversal_20d_nowin`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：五维（tsv10）去 intraday——维度贡献灵敏度测试。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(ts_rank(vol,10)) + cs_rank(corr10)
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
name: reversal_20d_four_dim_tsv10
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
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_rank(volume, 10)) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim_tsv10/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0645 |
| t 值 | 7.44 |
| IR | 0.557 |
| 近 26 周 mean / t | 0.0442 / 1.71 |

| 项 | 值 |
|----|----|
| spread | 0.00415 |
| D1 / D10 | 0.00313 / -0.00101 |

### 判定

- vs five_dim_tsv10：IC 0.0645（0.0707，**-9%**）、t 7.44（7.58）、
  IR 0.557（0.568）——**intraday 第五维贡献确认（IC +9%）**。
- 结论：**无效（维度贡献确认）**——五维保持；
  近 26 周 t=1.71 仍强（构成内维度均近期有效）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim_tsv10`（初始） | 批次 3 轮 71：D2 去 intraday | 0.0645 | 7.44 | 无效：intraday 贡献确认 |

## 6. 风险与备注

- **维度贡献**：intraday 在 tsv 构成中贡献 IC +9%——五维构成每维
  均有实质贡献（六维才饱和）。
- 基准 [`reversal_20d_five_dim_tsv10.md`](reversal_20d_five_dim_tsv10.md)
  （稳定性纪录 7.58/0.568）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
