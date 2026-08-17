---
xname: reversal_20d_pricevolcorr10
formula: |
  signal = ts_corr(returns(close), ts_delta(volume, 1), 10)
tags: [mine_b3r44, reversal, price_vol_corr10, peak_shift]
params: {}
status: 候选（corr 谱峰 10 日——全指标微升）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_pricevolcorr10 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_pricevolcorr10`（= `factor/reversal_20d_pricevolcorr10.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（corr 谱峰 10 日） |
| 标签 | mine_b3r44, reversal, price_vol_corr10, peak_shift |
| 创建 | 2026-08-18（批次 3 轮次 44，种子 `momentum_20d_decile`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量价相关窗口谱下界——10 日（结构信号短窗灵敏度）。

**数学表达**：

```
signal = corr(returns(close), Δvolume, 10d)
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
name: reversal_20d_pricevolcorr10
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
  from polars_ta.prefix.wq import ts_corr, ts_delta
  signal = ts_corr(returns(close), ts_delta(volume, 1), 10)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_pricevolcorr10/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 180 |
| 平均股票数 | 4884 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0439 |
| t 值 | 6.46 |
| IR | 0.481 |
| 近 26 周 mean / t | 0.0161 / 1.04 |
| PearsonIC mean | -0.0136（t=-2.52） |

| 项 | 值 |
|----|----|
| spread | 0.00289 |
| D1 / D10 | 0.00318 / 0.00029 |

### 判定

- vs corr20（原纪录）：IC 0.0439（0.0425，+3%）、t 6.46（6.36）、
  IR 0.481（0.477）——**全指标微升**。
- **谱峰结论**：量价结构信号谱峰在 **10 日**（10 > 20 > 60 单调递减——
  与价格反转的 20 日峰不同：结构信号更短、放量事件短窗更灵敏）。
- 结论：**候选**——corr10 为量价相关更优窗口。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_pricevolcorr10`（初始） | 批次 3 轮 44：C2 corr 10 日 | 0.0439 | 6.46 | 候选：谱峰 10 日 |

## 6. 风险与备注

- **窗口结论**：corr 谱峰 10 日（结构信号短窗）；
  四维组合中的 corr 维度可换 corr10（待测）。
- 基准 [`reversal_20d_pricevolcorr.md`](reversal_20d_pricevolcorr.md)（20 日版）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
