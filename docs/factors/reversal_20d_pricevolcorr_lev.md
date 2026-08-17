---
xname: reversal_20d_pricevolcorr_lev
formula: |
  signal = ts_corr(returns(close), volume, 20)
tags: [mine_b3r43, reversal, price_vol_corr, level_weaker]
params: {}
status: 无效（Δ量版更优）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_pricevolcorr_lev 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_pricevolcorr_lev`（= `factor/reversal_20d_pricevolcorr_lev.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——量水平相关弱于 Δ量 |
| 标签 | mine_b3r43, reversal, price_vol_corr, level_weaker |
| 创建 | 2026-08-18（批次 3 轮次 43，种子 `reversal_20d_nowin`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量价相关的第二输入对照——Δ量（事件）vs 量水平（活跃度）。

**数学表达**：

```
signal = corr(returns(close), volume, 20d)
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
name: reversal_20d_pricevolcorr_lev
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
  from polars_ta.prefix.wq import ts_corr
  signal = ts_corr(returns(close), volume, 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_pricevolcorr_lev/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0267 |
| t 值 | 4.04 |
| IR | 0.303 |
| 近 26 周 mean / t | 0.0011 / 0.08 |

| 项 | 值 |
|----|----|
| spread | 0.00050 |
| D1 / D10 | 0.00277 / 0.00227 |

### 判定

- vs corr（Δ量版，IR 纪录）：IC 0.0267（0.0425，-37%）、t 4.04（6.36）、
  IR 0.303（0.477）——**量水平相关全面弱于 Δ量版**。
- 结论：**无效（L2' 否定）**——**Δ量（放量事件）是量价相关的正确输入**；
  量水平（活跃度）受股本/趋势影响，相关结构噪声大。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_pricevolcorr_lev`（初始） | 批次 3 轮 43：L2 量水平 | 0.0267 | 4.04 | 无效：Δ量版更优 |

## 6. 风险与备注

- **输入结论**：量价相关保持 Δ量输入（放量事件结构）；
  量水平方向不再重复。
- 基准 [`reversal_20d_pricevolcorr.md`](reversal_20d_pricevolcorr.md)（IR 纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
