---
xname: reversal_20d_corr_turn_flow
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow20)
tags: [mine_b3r79, reversal, corr_turn_flow, strong]
params: {}
status: 候选（IC 0.0703 超 corr_turn）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_turn_flow 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_turn_flow`（= `factor/reversal_20d_corr_turn_flow.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（IC 0.0703 超 corr_turn） |
| 标签 | mine_b3r79, reversal, corr_turn_flow, strong |
| 创建 | 2026-08-18（批次 3 轮次 79，种子 `reversal_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：corr×turn（强互补）加第三维 flow——量维度正交性测试。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow20)
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
name: reversal_20d_corr_turn_flow
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_sum(amount * sign(returns(close)), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_turn_flow/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0703 |
| t 值 | 6.76 |
| IR | 0.507 |
| 近 26 周 mean / t | 0.0455 / 1.49 |
| PearsonIC mean | -0.0227（t=-2.46） |

| 项 | 值 |
|----|----|
| spread | 0.00489 |
| D1 / D10 | 0.00271 / -0.00218 |

### 判定

- vs corr_turn（二维）：IC 0.0703（0.0691，**+1.7%**）、t 6.76（6.33，+7%）、
  IR 0.507（0.472，+7%）、近 26 周 1.49（1.85 略降）——flow 第三维
  **部分正交贡献**（与 vol 的稀释不同——方向加权信息互补）。
- 结论：**候选**——corr/turn/flow 三维为 IC 强组合
  （接近四维 0.0721/五维 0.0712）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_turn_flow`（初始） | 批次 3 轮 79：T3 三维加法 | 0.0703 | 6.76 | 候选：IC 超 corr_turn |

## 6. 风险与备注

- **三维谱更新**：corr/turn/flow（0.0703）> corr/turn/skew（0.0656）>
  corr/turn/vol（0.0625）——flow 是 corr×turn 的最佳第三维。
- 基准 [`reversal_20d_corr_turn.md`](reversal_20d_corr_turn.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
