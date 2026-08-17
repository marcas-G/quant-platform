---
xname: reversal_20d_five_dim_all
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(skew20) + cs_rank(flow30) + cs_rank(intraday20)
tags: [mine_b3r98, reversal, five_dim_all, saturated]
params: {}
status: 无效（五维饱和）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_five_dim_all 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_five_dim_all`（= `factor/reversal_20d_five_dim_all.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——五维饱和 |
| 标签 | mine_b3r98, reversal, five_dim_all, saturated |
| 创建 | 2026-08-18（批次 3 轮次 98，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：tsfi 四维加第五维 corr——全维度组合饱和点。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(skew20) + cs_rank(flow30) + cs_rank(intraday20)
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
name: reversal_20d_five_dim_all
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, ts_skewness, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_sum(amount * sign(returns(close)), 30)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_five_dim_all/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0728 |
| t 值 | 6.95 |
| IR | 0.524 |
| 近 26 周 mean / t | 0.0389 / 1.26 |

| 项 | 值 |
|----|----|
| spread | 0.00468 |
| D1 / D10 | 0.00326 / -0.00143 |

### 判定

- vs tsfi 四维：IC 0.0728（0.0727 持平）、t 6.95（6.73，+3%）、
  IR 0.524（0.507，+3%）——corr 第五维持平（skew 冗余抵消）。
- vs cti 纪录（0.0744）：差 2.2%。
- 结论：**无效（饱和确认）**——全维度五维组合持平；
  cti 三维（0.0744）保持全库 IC 纪录。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_five_dim_all`（初始） | 批次 3 轮 98：F3 五维加法 | 0.0728 | 6.95 | 无效：五维饱和 |

## 6. 风险与备注

- **维度上限定稿**：五维全维度持平——组合维度扩展终止；
  最优集：cti 三维（IC 0.0744）/tsv 五维（IR 0.574）。
- 基准 [`reversal_20d_corr_turn_intraday.md`](reversal_20d_corr_turn_intraday.md)
  （全库 IC 纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
