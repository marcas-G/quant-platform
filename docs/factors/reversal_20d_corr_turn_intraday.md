---
xname: reversal_20d_corr_turn_intraday
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(intraday20)
tags: [mine_b3r83, reversal, three_dim_cti, ic_record]
params: {}
status: 候选（全库 IC 新纪录：0.0744）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_turn_intraday 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_turn_intraday`（= `factor/reversal_20d_corr_turn_intraday.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（**全库 IC 新纪录：0.0744**） |
| 标签 | mine_b3r83, reversal, three_dim_cti, ic_record |
| 创建 | 2026-08-18（批次 3 轮次 83，种子 `momentum_20d_turnrank_avg20`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：corr×turn（强互补）加第三维 intraday——三维谱补全。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(intraday20)
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
name: reversal_20d_corr_turn_intraday
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_turn_intraday/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0744（**全库新纪录**） |
| t 值 | 6.99 |
| IR | 0.524 |
| 近 26 周 mean / t | 0.0450 / 1.44 |
| PearsonIC mean | -0.0236（t=-2.51） |

| 项 | 值 |
|----|----|
| spread | 0.00525（0.53%/周） |
| D1 / D10 | 0.00308 / -0.00217 |

### 判定

- **IC 0.0744 全库新纪录**（超 four_dim10 的 0.0721 +3%、超三维前纪录
  corr_turn_flow 0.0703 +6%）。
- **三维 > 四/五维**：intraday 与 corr/turn 正交性最强（幅度维度独立）；
  四维加量维度（vol/flow/skew）反而稀释。
- 结论：**候选（全库 IC 纪录）**——corr/turn/intraday 是
  IC 最优三维集；稳定性纪录仍 wcorr_tsv10（0.574）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_turn_intraday`（初始） | 批次 3 轮 83：T3 三维加法 | 0.0744 | 6.99 | **候选**：全库 IC 新纪录 |

## 6. 风险与备注

- **IC 最优集**：corr/turn/intraday（0.0744）——后续四维扩展应选
  正交维度（flow 已验证 +6%，可作第四维候补）。
- 基准 [`reversal_20d_corr_turn.md`](reversal_20d_corr_turn.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
