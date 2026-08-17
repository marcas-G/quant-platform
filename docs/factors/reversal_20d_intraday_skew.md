---
xname: reversal_20d_intraday_skew
formula: |
  signal = cs_rank(intraday20) + cs_rank(skew20)
tags: [mine_b3r54, reversal, intraday_skew, marginal]
params: {}
status: 观察中（IR 超两父本、IC 略降）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_intraday_skew 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_intraday_skew`（= `factor/reversal_20d_intraday_skew.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（IR 0.426 超两父本、IC 略降） |
| 标签 | mine_b3r54, reversal, intraday_skew, marginal |
| 创建 | 2026-08-18（批次 3 轮次 54，种子 `reversal_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：日内幅度 × 彩票偏好（矩）秩次加法——不同信息源组合。

**数学表达**：

```
signal = cs_rank(Σ(close/open-1, 20)) + cs_rank(skewness(returns, 20))
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
name: reversal_20d_intraday_skew
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
  from polars_ta.prefix.wq import ts_sum, ts_skewness, cs_rank
  signal = cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(ts_skewness(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_intraday_skew/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0517 |
| t 值 | 5.68 |
| IR | 0.426 |
| 近 26 周 mean / t | 0.0097 / 0.44 |

| 项 | 值 |
|----|----|
| spread | 0.00362 |
| D1 / D10 | 0.00325 / -0.00036 |

### 判定

- vs intraday（父 1）：IC 0.0517（0.0591，-13%）、**t 5.68（5.22）**、
  **IR 0.426（0.391）**——偏度增稳定性。
- vs skew（父 2）：IC +111%、t +32%。
- 结论：**观察中（边际）**——幅度×矩组合 IR 超两父本
  （偏度贡献稳定性），IC 略降于 intraday。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_intraday_skew`（初始） | 批次 3 轮 54：I3 秩次加法 | 0.0517 | 5.68 | 观察中：IR 超两父本 |

## 6. 风险与备注

- **组合结论**：intraday×skew 部分正交（IR 增益）但 IC 稀释——
  与 corr×skew（冗余）不同：幅度-矩组合比结构-矩组合更正交。
- 基准 [`reversal_20d_intraday.md`](reversal_20d_intraday.md)（纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
