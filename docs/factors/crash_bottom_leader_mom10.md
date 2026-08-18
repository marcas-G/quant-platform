---
xname: crash_bottom_leader_mom10
formula: |
  signal = (cs_rank(-mom10) + cs_rank(log(circ_mv))) * mask(idx20 < -0.08)
tags: [strategy, crash_bottom, market_timed, refuted]
params: {}
status: 无效（超跌窗口 20→10 证伪：t=1.77 不显著、符号不稳定）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# crash_bottom_leader_mom10 因子档案（10 日超跌窗口）

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `crash_bottom_leader_mom10`（= `factor/crash_bottom_leader_mom10.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效（变异证伪，种子 [`crash_bottom_leader_timed`](crash_bottom_leader_timed.md) 保持最优） |
| 标签 | strategy, crash_bottom, market_timed, refuted |
| 创建 | 2026-08-18（优化轮 2 V3） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**变异点**：超跌窗口 20 → 10 日（时效性边界探索：dd250 证伪证明短窗口胜，
继续向短推进——10 日能否捕捉更"当下"的抛售）。

**变异假设**（证伪）：股灾触发后最近 10 日跌幅比 20 日更能区分当下被抛售的股票。

**保留**：龙头（log circ_mv）、触发层、处理链、方向。

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
  _crash = sign(sign(-0.08 - _mkt20) + 1) / 2
  _mom = ts_mean(close, 10) / ts_delay(close, 10) - 1
  signal = (cs_rank(-_mom) + cs_rank(log(circ_mv))) * _crash
```

## 4. 验证结果

> 数据快照自 `results/crash_bottom_leader_mom10/summary.json`（2026-08-18）。

| 指标 | 本变体 | 种子（对照） |
|------|--------|-------------|
| 有效周 | 106 | 106 |
| RankIC mean | 0.0193 | 0.0321 |
| t 值 | 1.77（不显著） | 2.84 |
| 符号一致性 | **false**（不稳定） | true |
| spread | 0.0046 | 0.0077 |
| LS 年化 / 夏普 | 42.3% / 1.91 | 50.1% / 2.21 |

### 判定

**证伪**：IC 减半、t 不显著、**符号一致性丢失**（近 26 周 t 0.92）。10 日窗口
单周噪声主导。结合 dd250（轮 1）与 mom10（本轮）：**20 日是超跌窗口的
时效性-稳定性平衡点**——250 稀释信息、10 噪声主导。

## 5. 迭代历史

| 日期 | 变体 | 改动 | IC mean | t | 结论 |
|------|------|------|---------|---|------|
| 2026-08-18 | `crash_bottom_leader_mom10` | 超跌窗口 20→10 | 0.0193 | 1.77 | 证伪——10 日噪声主导 |

## 6. 风险与备注

- 与轮 1 dd250 合看：超跌窗口的时效性边界实验闭合（10 噪声 / 20 最优 / 250 稀释）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
