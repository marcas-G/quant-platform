---
xname: reversal_20d_corr_flow_intraday
formula: |
  signal = cs_rank(corr10) + cs_rank(flow20) + cs_rank(intraday20)
tags: [mine_b3r59, reversal, three_dim_cfi, record]
params: {}
status: 候选（三维 IC 纪录：0.0607）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_flow_intraday 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_flow_intraday`（= `factor/reversal_20d_corr_flow_intraday.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（三维 IC 纪录：0.0607） |
| 标签 | mine_b3r59, reversal, three_dim_cfi, record |
| 创建 | 2026-08-18（批次 3 轮次 59，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：corr×flow 二维有效（轮 58）加第三维日内幅度。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(flow20) + cs_rank(intraday20)
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
name: reversal_20d_corr_flow_intraday
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(amount * sign(returns(close)), 20)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_flow_intraday/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0607（三维纪录） |
| t 值 | 5.96 |
| IR | 0.447 |
| 近 26 周 mean / t | 0.0118 / 0.45 |

| 项 | 值 |
|----|----|
| spread | 0.00442 |
| D1 / D10 | 0.00309 / -0.00133 |

### 判定

- vs corr_flow（父 1）：IC +14%（0.0531→0.0607）。
- vs intraday（父 2）：IC +3%。
- vs corr_intraday（原三维纪录）：IC +4%。
- **三维 IC 新纪录（0.0607）**——corr/flow/intraday 三维互补；
  与四维（0.0721）仍有差距（turn/vol 维度贡献）。
- 结论：**候选**——三维组合（量结构+资金+幅度）有效。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_flow_intraday`（初始） | 批次 3 轮 59：T3 三维加法 | 0.0607 | 5.96 | 候选：三维 IC 纪录 |

## 6. 风险与备注

- **组合矩阵**：corr/flow/intraday 三维互补（量结构+资金+幅度）；
  四维（+turn/vol）仍是全库最强（0.0721/7.40/0.555）。
- 基准 [`reversal_20d_corr_flow.md`](reversal_20d_corr_flow.md)、
  [`reversal_20d_corr_intraday.md`](reversal_20d_corr_intraday.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
