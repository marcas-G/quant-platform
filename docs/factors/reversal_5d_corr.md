---
xname: reversal_5d_corr
formula: |
  signal = cs_rank(close/close[t-5]-1) + cs_rank(corr(returns, d_vol, 20))
tags: [mine_b3r38, reversal, near5_corr, marginal]
params: {}
status: 观察中（IC 超两父本、稳定性被稀释）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_5d_corr 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_5d_corr`（= `factor/reversal_5d_corr.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（组合 IC 超两父本、稳定性降） |
| 标签 | mine_b3r38, reversal, near5_corr, marginal |
| 创建 | 2026-08-18（批次 3 轮次 38，种子 `reversal_20d_near5`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：近端超调（幅度，弱）与量价相关（结构，强）秩次加法——
近端信息补偿 corr 的幅度维度。

**数学表达**：

```
signal = cs_rank(close/close[t-5] - 1) + cs_rank(corr(returns, Δvol, 20))
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
name: reversal_5d_corr
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_delay, cs_rank
  signal = cs_rank(close / ts_delay(close, 5) - 1) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_5d_corr/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0450 |
| t 值 | 4.65 |
| IR | 0.349 |
| 近 26 周 mean / t | 0.0022 / 0.09 |

| 项 | 值 |
|----|----|
| spread | 0.00228 |
| D1 / D10 | 0.00188 / -0.00040 |

### 判定

- vs near5（父 1）：IC +55%（0.0290→0.0450）、t 2.44→4.65——大幅改善。
- vs corr（父 2）：IC +6%（0.0425→0.0450）但 t 6.36→4.65、IR 0.477→0.349——
  **近端维度增水平、稀释稳定性**。
- 结论：**观察中（边际）**——近端与 corr 部分正交（IC 增益），
  但近端噪声稀释 corr 的稳定性；全库最强仍是四维组合（0.072/7.35）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_5d_corr`（初始） | 批次 3 轮 38：N2 秩次加法 | 0.0450 | 4.65 | 观察中：IC 超两父本、稳定性降 |

## 6. 风险与备注

- **维度权衡**：近端维度增水平舍稳定性——组合设计需平衡；
  四维组合（含 corr+intraday+turn+vol）仍是综合最优。
- 父本 [`reversal_20d_near5.md`](reversal_20d_near5.md)、
  [`reversal_20d_pricevolcorr.md`](reversal_20d_pricevolcorr.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
