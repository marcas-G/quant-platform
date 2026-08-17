---
xname: reversal_20d_intraday_flow30
formula: |
  signal = cs_rank(intraday20) + cs_rank(flow30)
tags: [mine_b3r94, reversal, intraday_flow30, peak_applied]
params: {}
status: 候选（flow30 谱峰应用）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_intraday_flow30 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_intraday_flow30`（= `factor/reversal_20d_intraday_flow30.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（flow30 谱峰应用） |
| 标签 | mine_b3r94, reversal, intraday_flow30, peak_applied |
| 创建 | 2026-08-18（批次 3 轮次 94，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：intraday×flow 二维的 flow 窗口换谱峰（30 日）。

**数学表达**：

```
signal = cs_rank(intraday20) + cs_rank(flow30)
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
name: reversal_20d_intraday_flow30
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
  from polars_ta.prefix.wq import ts_sum, cs_rank
  signal = cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(ts_sum(amount * sign(returns(close)), 30))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_intraday_flow30/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0589 |
| t 值 | 5.50 |
| IR | 0.415 |
| 近 26 周 mean / t | 0.0107 / 0.38 |

| 项 | 值 |
|----|----|
| spread | 0.00447 |
| D1 / D10 | 0.00268 / -0.00179 |

### 判定

- vs intraday_flow（flow20）：IC +5.4%（0.0559→0.0589）、t 5.50（5.29）、
  IR 0.415（0.397）——flow30 传导有效。
- 结论：**候选**——flow30 谱峰在 intraday 组合中同样增益。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_intraday_flow30`（初始） | 批次 3 轮 94：F3 flow30 | 0.0589 | 5.50 | 候选：谱峰应用 |

## 6. 风险与备注

- **谱峰应用系列定稿**：flow30 在 corr/turn/intraday 组合中传导均 +5%——
  组合维度统一取谱峰（corr10/flow30/intraday20）。
- 基准 [`reversal_20d_intraday_flow.md`](reversal_20d_intraday_flow.md)（flow20 版）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
