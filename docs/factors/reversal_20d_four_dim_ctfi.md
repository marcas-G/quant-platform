---
xname: reversal_20d_four_dim_ctfi
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow20) + cs_rank(intraday20)
tags: [mine_b3r81, reversal, four_dim_ctfi, near_record]
params: {}
status: 候选（IC 0.0717 接近全库最强）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim_ctfi 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim_ctfi`（= `factor/reversal_20d_four_dim_ctfi.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（IC 0.0717 接近全库最强 0.0721） |
| 标签 | mine_b3r81, reversal, four_dim_ctfi, near_record |
| 创建 | 2026-08-18（批次 3 轮次 81，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：corr/turn/flow 三维（0.0703）加第四维 intraday——flow 替代 vol
的四维构成（four_dim10 变体）。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow20) + cs_rank(intraday20)
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
name: reversal_20d_four_dim_ctfi
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_sum(amount * sign(returns(close)), 20)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim_ctfi/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0717 |
| t 值 | 6.77 |
| IR | 0.508 |
| 近 26 周 mean / t | 0.0356 / 1.17 |

| 项 | 值 |
|----|----|
| spread | 0.00519 |
| D1 / D10 | 0.00285 / -0.00233 |

### 判定

- vs corr_turn_flow（三维）：IC +2%（0.0703→0.0717）。
- vs four_dim10（IC 纪录）：IC 0.0717（0.0721，**-0.6%**）——**接近全库最强**。
- 结论：**候选**——corr/turn/flow/intraday 构成（flow 替代 vol）
  几乎追平 IC 纪录；t/IR 略低（vol 构成稳定性更强）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim_ctfi`（初始） | 批次 3 轮 81：F3 四维加法 | 0.0717 | 6.77 | 候选：接近全库最强 |

## 6. 风险与备注

- **构成对照**：flow 构成（IC 0.0717）vs vol 构成（0.0721）——
  IC 接近、vol 稳定性更强；两构成均为实盘化候选。
- 基准 [`reversal_20d_four_dim10.md`](reversal_20d_four_dim10.md)（IC 纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
