---
xname: crash_bottom_leader_timed_m6
formula: |
  signal = (cs_rank(-mom20) + cs_rank(log(circ_mv))) * mask(idx20 < -0.06)
tags: [strategy, crash_bottom, market_timed, refuted]
params: {}
status: 无效（触发阈值 -8% → -6% 证伪：触发周 +44% 但触发期年化减半）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# crash_bottom_leader_timed_m6 因子档案（-6% 触发阈值）

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `crash_bottom_leader_timed_m6`（= `factor/crash_bottom_leader_timed_m6.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效（变异证伪，种子 [`crash_bottom_leader_timed`](crash_bottom_leader_timed.md) 保持最优） |
| 标签 | strategy, crash_bottom, market_timed, refuted |
| 创建 | 2026-08-18（收敛轮：触发频率验证） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**变异点**：触发阈值 -8% → -6%（触发更频繁：平均 2.9 → ~4.2 段/年）。

**变异假设**（证伪）：浅跌段（-6~-8%）也是抄底机会，触发更频繁 → 全期年化提升。

**保留**：超跌（mom20）、龙头（log circ_mv）、段首缓冲、处理链、方向。

## 3. 参数与实现

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2015-01-01 ~ 2026-07-31（分块计算 --chunk-days 500）
process: winsorize(quantile=0.99) → standardize()
```

```yaml
formula: |
  from polars_ta.prefix.wq import ts_sum, ts_mean, ts_delay, cs_rank
  _mkt20 = ts_sum(idx_ret, 20)
  _crash = sign(sign(-0.06 - _mkt20) + 1) / 2
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  signal = (cs_rank(-_mom) + cs_rank(log(circ_mv))) * _crash
```

## 4. 验证结果（策略层，K=30 等权 + 段首缓冲 + 跌停过滤 + 成本）

> 快照自 `tools/strategy_crash_bottom.py`（2026-08-18）。

| 指标 | 本变体（-6%） | 种子（-8%） |
|------|--------------|-------------|
| 触发周 | 157（+44%） | 109 |
| 触发期年化 | 44.7% | 81.9% |
| 全期年化 | 10.2% | 11.5% |
| 夏普 | 1.16 | 1.86 |
| 成本 | 27.8% | 19.0% |

### 判定

**证伪**：触发周 +44% 但触发期年化几乎减半（81.9% → 44.7%）、全期年化反而
微降——**-6~-8% 的浅回调段超跌信号噪声大**，触发变多是"低质量机会"
（与强度分级证伪一致：真正的危机反弹集中在 -8% 以下）。**-8% 是"危机"的
正确阈值**。

## 5. 迭代历史

| 日期 | 变体 | 改动 | 触发期年化 | 夏普 | 结论 |
|------|------|------|-----------|------|------|
| 2026-08-18 | `crash_bottom_leader_timed_m6` | 阈值 -8% → -6% | 44.7% | 1.16 | 证伪——浅触发噪声主导 |

## 6. 风险与备注

- 与强度分级证伪互证：-8% 以下的深度才有"危机反弹"，更浅的触发是噪声。
- 触发频率不是越多越好——质量门槛（-8%）是信号的一部分。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
