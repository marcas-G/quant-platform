---
xname: reversal_20d_five_dim_ctfi
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow20) + cs_rank(intraday20) + cs_rank(skew20)
tags: [mine_b3r82, reversal, five_dim_ctfi, skew_flat]
params: {}
status: 无效（skew 第五维持平）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_five_dim_ctfi 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_five_dim_ctfi`（= `factor/reversal_20d_five_dim_ctfi.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——skew 第五维持平 |
| 标签 | mine_b3r82, reversal, five_dim_ctfi, skew_flat |
| 创建 | 2026-08-18（批次 3 轮次 82，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：ctfi 四维加第五维 skew——冗余性构成差异测试。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow20) + cs_rank(intraday20) + cs_rank(skew20)
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
name: reversal_20d_five_dim_ctfi
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_sum(amount * sign(returns(close)), 20)) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(ts_skewness(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_five_dim_ctfi/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0713 |
| t 值 | 6.91 |
| IR | 0.518 |
| 近 26 周 mean / t | 0.0353 / 1.18 |

| 项 | 值 |
|----|----|
| spread | 0.00490 |
| D1 / D10 | 0.00321 / -0.00170 |

### 判定

- vs four_dim_ctfi：IC 0.0713（0.0717，-0.6% 持平）、t 6.91（6.77，+2%）、
  IR 0.518（0.508，+2%）——**skew 第五维基本持平**。
- 结论：**无效（持平）**——skew 冗余于 corr 不随构成改变；
  四维 ctfi（0.0717）为含 corr 构成最优。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_five_dim_ctfi`（初始） | 批次 3 轮 82：F3 五维加法 | 0.0713 | 6.91 | 无效：skew 持平 |

## 6. 风险与备注

- **skew 结论定稿**：skew 与 corr 冗余（多构成确认）——含 corr 组合
  不再加 skew；skew 仅用于不含 corr 的组合（turn_skew 家族）。
- 基准 [`reversal_20d_four_dim_ctfi.md`](reversal_20d_four_dim_ctfi.md)（候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
