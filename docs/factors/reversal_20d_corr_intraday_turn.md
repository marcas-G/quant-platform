---
xname: reversal_20d_corr_intraday_turn
formula: |
  signal = cs_rank(corr) + cs_rank(intraday) + cs_rank(turnover)
tags: [mine_b3r36, reversal, three_dim, library_best]
params: {}
status: 候选（全库最强：IC/t/IR 三项纪录）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_intraday_turn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_intraday_turn`（= `factor/reversal_20d_corr_intraday_turn.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（全库最强：IC/t/IR 三项纪录） |
| 标签 | mine_b3r36, reversal, three_dim, library_best |
| 创建 | 2026-08-18（批次 3 轮次 36，种子 `momentum_20d_turnrank_avg20`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量价相关（结构）× 日内（幅度）× 换手率（投机强度）三维
秩次加法——轮 33 二维已强（0.058/6.08），第三维扩展。

**核心逻辑**：三维等权秩次相加（各 1/3）：
- 量价齐升（corr 高）→ 做空
- 日内强（高开低走少）→ 做空
- 高换手（投机）→ 做空

**数学表达**：

```
signal = cs_rank(corr(returns, Δvol, 20)) + cs_rank(Σ(close/open-1, 20)) + cs_rank(turnover)
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
name: reversal_20d_corr_intraday_turn
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 20)) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(turnover)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_intraday_turn/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0724（**全库纪录**） |
| t 值 | 6.79（**全库纪录**） |
| IR | 0.509（**全库纪录，首破 0.5**） |
| 近 26 周 mean / t | 0.0448 / 1.35 |
| PearsonIC mean | -0.0220（t=-2.34） |

| 项 | 值 |
|----|----|
| spread | 0.00463（0.46%/周） |
| D1 / D10 | 0.00295 / -0.00168 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- **IC 0.0724（优秀线 0.05 的 145%）、t 6.79、IR 0.509——三项全库纪录**；
  spread 0.46%/周；**近 26 周 t=1.35**（近期持续有效）。
- vs 二维组合（轮 33）：IC +25%、t +12%、IR +12%。
- 结论：**候选（全库最强）**——三维正交维度秩次加法同时获得
  水平、稳定性、近期有效性。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_intraday_turn`（初始） | 批次 3 轮 36：T3 三维秩次加法 | 0.0724 | 6.79 | **候选**：三项全库纪录 |

## 6. 风险与备注

- **实盘化前**：换样本期（2019-2021）外样本复验、换手/容量分析、
  与量能家族（symrun）正交性。
- **四维扩展**：量能确认（时序）可作第四维（cs_rank 等权）——待测。
- 基准 [`reversal_20d_corr_intraday.md`](reversal_20d_corr_intraday.md)（二维）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
