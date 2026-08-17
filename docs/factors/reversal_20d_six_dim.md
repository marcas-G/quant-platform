---
xname: reversal_20d_six_dim
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(vol20) + cs_rank(corr10) + cs_rank(intraday20) + cs_rank(flow20)
tags: [mine_b3r68, reversal, six_dim, saturated]
params: {}
status: 无效（六维饱和——五维 tsv 综合最优）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_six_dim 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_six_dim`（= `factor/reversal_20d_six_dim.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——六维饱和 |
| 标签 | mine_b3r68, reversal, six_dim, saturated |
| 创建 | 2026-08-18（批次 3 轮次 68，种子 `reversal_20d_nowin`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：tsv 五维（综合最优）六维扩展——flow 是否独立贡献。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(vol20) + cs_rank(corr10) + cs_rank(intraday20) + cs_rank(flow20)
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
name: reversal_20d_six_dim
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
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_rank(volume, 20)) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(ts_sum(amount * sign(returns(close)), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_six_dim/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0719 |
| t 值 | 7.24 |
| IR | 0.543 |
| 近 26 周 mean / t | 0.0315 / 1.13 |

| 项 | 值 |
|----|----|
| spread | 0.00547 |
| D1 / D10 | 0.00326 / -0.00220 |

### 判定

- vs five_dim_tsv：IC 0.0719（0.0712，+1%）但 **t 7.24（7.51，-4%）**、
  **IR 0.543（0.563，-4%）**——flow 与 vol 重叠稀释稳定性。
- 结论：**无效（饱和确认）**——tsv 五维是综合最优；
  六维 IC 微升不抵稳定性损失。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_six_dim`（初始） | 批次 3 轮 68：S3 六维加法 | 0.0719 | 7.24 | 无效：六维饱和 |

## 6. 风险与备注

- **维度上限**：tsv 五维为综合最优饱和点——后续不做维度扩展；
  转向核心表达或样本稳健性。
- 基准 [`reversal_20d_five_dim_tsv.md`](reversal_20d_five_dim_tsv.md)
  （综合最优：0.0712/7.51/0.563）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
