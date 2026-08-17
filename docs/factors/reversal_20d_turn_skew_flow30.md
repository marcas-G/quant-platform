---
xname: reversal_20d_turn_skew_flow30
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(flow30)
tags: [mine_b3r95, reversal, turn_skew_flow30, strong]
params: {}
status: 候选（IC 0.0697 超 turn_skew）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_turn_skew_flow30 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_turn_skew_flow30`（= `factor/reversal_20d_turn_skew_flow30.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（IC 0.0697 超 turn_skew +10%） |
| 标签 | mine_b3r95, reversal, turn_skew_flow30, strong |
| 创建 | 2026-08-18（批次 3 轮次 95，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：turn×skew（强互补）加第三维 flow30——投机+彩票+资金流。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(flow30)
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
name: reversal_20d_turn_skew_flow30
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
  from polars_ta.prefix.wq import ts_skewness, ts_sum, cs_rank
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_sum(amount * sign(returns(close)), 30))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_turn_skew_flow30/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0697 |
| t 值 | 6.31 |
| IR | 0.475 |
| 近 26 周 mean / t | 0.0530 / 1.39 |
| PearsonIC mean | -0.0209（t=-2.12） |

| 项 | 值 |
|----|----|
| spread | 0.00376 |
| D1 / D10 | 0.00262 / -0.00114 |

### 判定

- vs turn_skew（二维）：IC **+10%**（0.0633→0.0697）、t 6.31（5.74）、
  IR 0.475（0.430）——flow30 第三维强贡献。
- vs flow_skew：IC +50%。
- 近 26 周 t=1.39（近期强）。
- 结论：**候选**——投机/彩票/资金流三维高度互补
  （IC 接近 cti 纪录 0.0744）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_turn_skew_flow30`（初始） | 批次 3 轮 95：T3 三维加法 | 0.0697 | 6.31 | 候选：IC 超 turn_skew |

## 6. 风险与备注

- **三维谱更新**：turn/skew/flow30（0.0697）为投机系最强三维
  （无 corr 构成——skew 与 corr 冗余限制）。
- 基准 [`reversal_20d_turn_skew.md`](reversal_20d_turn_skew.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
