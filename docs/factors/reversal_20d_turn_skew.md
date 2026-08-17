---
xname: reversal_20d_turn_skew
formula: |
  signal = cs_rank(turnover) + cs_rank(skew20)
tags: [mine_b3r62, reversal, turn_skew, strong, recent_alive]
params: {}
status: 候选（强候选：IC 0.0633 超两父本）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_turn_skew 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_turn_skew`（= `factor/reversal_20d_turn_skew.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强候选：IC 0.0633、近 26 周 t=1.58） |
| 标签 | mine_b3r62, reversal, turn_skew, strong, recent_alive |
| 创建 | 2026-08-18（批次 3 轮次 62，种子 `momentum_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：投机（换手率）× 彩票（偏度）秩次加法——相关但独立显著的维度。

**数学表达**：

```
signal = cs_rank(turnover) + cs_rank(skewness(returns, 20))
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
name: reversal_20d_turn_skew
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
  from polars_ta.prefix.wq import ts_skewness, cs_rank
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_turn_skew/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0633 |
| t 值 | 5.74 |
| IR | 0.430 |
| 近 26 周 mean / t | 0.0575 / 1.58（**近期强**） |
| PearsonIC mean | -0.0171（t=-1.84） |

| 项 | 值 |
|----|----|
| spread | 0.00294 |
| D1 / D10 | 0.00246 / -0.00048 |

### 判定

- vs turnrank（父 1）：IC **+51%**（0.0419→0.0633）、t +70%。
- vs skew（父 2）：IC **+158%**。
- **近 26 周 t=1.58**（近期仍强——投机+彩票信号 2026 年未衰减）。
- 结论：**候选（强候选）**——投机×彩票高度互补；
  可作为四维组合的候选替换维度。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_turn_skew`（初始） | 批次 3 轮 62：T3 turn×skew | 0.0633 | 5.74 | **强候选**：IC 超两父本 |

## 6. 风险与备注

- **维度互补图景**：投机（turn）× 彩票（skew）互补性强——
  投机维度组合优于价格维度组合（轮 52/54 对照）。
- 基准 [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md)、
  [`reversal_20d_skew.md`](reversal_20d_skew.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
