---
xname: reversal_20d_corr_flow30
formula: |
  signal = cs_rank(corr10) + cs_rank(flow30)
tags: [mine_b3r93, reversal, corr_flow30, dual_peak]
params: {}
status: 候选（双谱峰二维）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_flow30 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_flow30`（= `factor/reversal_20d_corr_flow30.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（双谱峰二维：corr10/flow30） |
| 标签 | mine_b3r93, reversal, corr_flow30, dual_peak |
| 创建 | 2026-08-18（批次 3 轮次 93，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：corr×flow 二维的 flow 窗口换谱峰（30 日）。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(flow30)
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
name: reversal_20d_corr_flow30
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(amount * sign(returns(close)), 30))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_flow30/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0559 |
| t 值 | 6.55 |
| IR | 0.493 |
| 近 26 周 mean / t | 0.0155 / 0.73 |

| 项 | 值 |
|----|----|
| spread | 0.00354 |
| D1 / D10 | 0.00289 / -0.00066 |

### 判定

- vs corr_flow（flow20）：IC +5.3%（0.0531→0.0559）、t 6.55（6.25）、
  IR 0.493（0.469）——flow30 谱峰传导有效。
- 结论：**候选**——corr10/flow30 双谱峰二维为 corr×flow 最优版。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_flow30`（初始） | 批次 3 轮 93：F3 flow30 | 0.0559 | 6.55 | 候选：双谱峰 |

## 6. 风险与备注

- **谱峰应用系列完成**：corr10/flow30 在二维/三维组合中传导均有效。
- 基准 [`reversal_20d_corr_flow.md`](reversal_20d_corr_flow.md)（flow20 版）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
