---
xname: reversal_20d_four_dim_ctfm
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow20) + cs_rank(max20)
tags: [mine_b4r5, reversal, four_dim_ctfm, ic_record]
params: {}
status: 候选（全库 IC 新纪录：0.0769）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim_ctfm 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim_ctfm`（= `factor/reversal_20d_four_dim_ctfm.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（**全库 IC 新纪录：0.0769**） |
| 标签 | mine_b4r5, reversal, four_dim_ctfm, ic_record |
| 创建 | 2026-08-18（批次 4 轮次 5，种子 `reversal_20d_four_dim_ctfs`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：组合中彩票维度用更强表达——MAX 效应（0.0661/t=5.14）替代 skew（0.0245/t=4.29）。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(flow20) + cs_rank(max20)
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
name: reversal_20d_four_dim_ctfm
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, ts_max, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_sum(amount * sign(returns(close)), 20)) + cs_rank(ts_max(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim_ctfm/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0769（**全库新纪录**） |
| t 值 | 6.36 |
| IR | 0.476 |
| 近 26 周 mean / t | 0.0606 / 1.60 |
| PearsonIC mean | -0.0227（t=-2.14） |

| 项 | 值 |
|----|----|
| spread | 0.00481 |
| D1 / D10 | 0.00273 / -0.00208 |

### 判定

- vs ctfs（skew 版）：**IC +10%**（0.0696→**0.0769，全库新纪录**）、近 26 周
  1.60（强）；t 6.36（6.96）、IR 0.476（0.522）略降——MAX 提升水平、
  skew 稳定性略高。
- 结论：**候选（全库 IC 新纪录）**——彩票维度用 MAX 表达更强；
  skew 版（ctfs）稳定性略优——两版互补。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim_ctfm`（初始） | 批次 4 轮 5：F3 MAX 替代 skew | 0.0769 | 6.36 | **候选**：IC 全库新纪录 |

## 6. 风险与备注

- **彩票维度表达**：MAX（水平）vs skew（稳定性）——组合按目标选择；
  MAX 版为当前 IC 纪录。
- 种子 [`reversal_20d_four_dim_ctfs.md`](reversal_20d_four_dim_ctfs.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
