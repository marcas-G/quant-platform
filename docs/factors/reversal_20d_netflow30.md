---
xname: reversal_20d_netflow30
formula: |
  signal = ts_sum(amount * sign(returns(close)), 30)
tags: [mine_b3r89, reversal, netflow30, peak_30]
params: {}
status: 候选（netflow 谱峰修正为 30 日）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_netflow30 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_netflow30`（= `factor/reversal_20d_netflow30.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（netflow 谱峰 30 日） |
| 标签 | mine_b3r89, reversal, netflow30, peak_30 |
| 创建 | 2026-08-18（批次 3 轮次 89，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：资金流窗口谱上探——30 日（更长平滑）。

**数学表达**：

```
signal = Σ (amount × sign(returns)) over 30d
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
name: reversal_20d_netflow30
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
  from polars_ta.prefix.wq import ts_sum
  signal = ts_sum(amount * sign(returns(close)), 30)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_netflow30/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0447 |
| t 值 | 5.32 |
| IR | 0.401 |
| 近 26 周 mean / t | 0.0092 / 0.38 |

| 项 | 值 |
|----|----|
| spread | 0.00287 |
| D1 / D10 | 0.00182 / -0.00105 |

### 判定

- vs netflow20：IC 0.0447（0.0417，**+7%**）、t 5.32（5.01）、
  IR 0.401（0.375）——**30 日全面更优**。
- **谱峰修正**：netflow 谱 10（0.0403）/20（0.0417）/30（0.0447）——
  峰在 30 日（资金流信号需更长累计平滑）。
- 结论：**候选**——netflow30 为资金流最优表达；
  组合中 flow 维度应换 30 日（待测）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_netflow30`（初始） | 批次 3 轮 89：F2 netflow30 | 0.0447 | 5.32 | 候选：谱峰 30 日 |

## 6. 风险与备注

- **谱峰修正**：资金流谱峰 30 日（原 20 日结论修正）——
  组合中 flow 维度换 30 日窗口可再测。
- 基准 [`reversal_20d_netflow.md`](reversal_20d_netflow.md)（20 日版）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
