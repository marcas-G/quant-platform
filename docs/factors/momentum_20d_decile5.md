---
xname: momentum_20d_decile5
formula: |
  signal = floor(cs_rank(MA(close,20)/close[t-20]-1) * 5) / 5
tags: [mine_b3r8, reversal, decile5, granularity, no_gain]
params: {}
status: 无效（5 档劣化，10 档有边际信息）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_decile5 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_decile5`（= `factor/momentum_20d_decile5.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——10 档有边际信息 |
| 标签 | mine_b3r8, reversal, decile5, granularity, no_gain |
| 创建 | 2026-08-18（批次 3 轮次 8，种子 `momentum_20d_decile`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `momentum_20d_decile`（10 档分档，与连续等价）的假设 (D3)
秩次信息需 10 档表达。检验粒度边界：5 档是否已饱和。

**数学表达**：

```
signal = floor(cs_rank(MA(close,20)/close[t-20]-1) × 5) / 5
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
name: momentum_20d_decile5
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, cs_rank
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  signal = floor(cs_rank(_mom) * 5) / 5
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_decile5/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0397 |
| t 值 | 3.41 |
| IR | 0.256 |
| 近 26 周 mean / t | 0.0022 / 0.07 |
| PearsonIC mean | -0.0154（t=-1.55） |

| 项 | 值 |
|----|----|
| spread | 0.00299 |
| 分层组数 | 5（信号 6 档取值 → 分层按取值分组） |
| 组均值 | G0=0.0031, G1=0.0035, G2=0.0031, G3=0.0023, G4=0.0001 |

### 判定

- vs decile（10 档）：IC 0.0397（0.0406，-2%）、t 3.41、IR 0.256、
  **spread 0.00299（0.00361，-17%）**——档数收窄直接压缩档位间距。
- 结论：**无效**——10 档有边际信息（至少档位区分层面）；
  秩次信息粒度边界 ≥10 档。与 decile 等价性结论（连续 vs 分档）互补：
  连续信息冗余，但 10 档粒度有值。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `momentum_20d_decile5`（初始） | 批次 3 轮 8：D3 5 档粒度 | 0.0397 | 3.41 | 无效：10 档有边际信息 |

## 6. 风险与备注

- **粒度结论**：分档粒度下限 ~10 档（分层 spread 对档数敏感）；
  上限方向（20 档）预计趋近连续版（等价）。
- 种子 [`momentum_20d_decile.md`](momentum_20d_decile.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
