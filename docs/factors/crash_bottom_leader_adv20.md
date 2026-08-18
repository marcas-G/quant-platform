---
xname: crash_bottom_leader_adv20
formula: |
  signal = (cs_rank(-mom20) + cs_rank(log(adv20(volume)))) * mask(idx20 < -0.08)
tags: [strategy, crash_bottom, market_timed, liquidity_leader]
params: {}
status: 观察中（可交易性龙头：IC 略低但 LS 夏普 2.45 最高；与种子等价替代）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# crash_bottom_leader_adv20 因子档案（成交额龙头）

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `crash_bottom_leader_adv20`（= `factor/crash_bottom_leader_adv20.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 观察中（等价替代——夏普维度更优，IC 维度略低） |
| 标签 | strategy, crash_bottom, market_timed, liquidity_leader |
| 创建 | 2026-08-18（优化轮 2 V4） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**变异点**：龙头从市值 `log(circ_mv)` → 成交额 `log(adv20(volume))`。

**变异假设**（部分成立）：股灾抄底的"龙头"实质是**能买进的**——市值大但
流动性枯竭的股票（连续跌停/一字板）信号再强也无法成交；20 日均量是可交易性
直接代理。

**保留**：超跌（mom20）、触发层、处理链、方向。

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
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  signal = (cs_rank(-_mom) + cs_rank(log(adv20(volume)))) * _crash
```

## 4. 验证结果

> 数据快照自 `results/crash_bottom_leader_adv20/summary.json`（2026-08-18）。

| 指标 | 本变体 | 种子（对照） |
|------|--------|-------------|
| 有效周 | 106 | 106 |
| RankIC mean | 0.0284 | 0.0321 |
| t 值 | 2.77（显著） | 2.84 |
| 符号一致性 | true | true |
| spread | **0.0085** | 0.0077 |
| LS 年化 | 50.4% | 50.1% |
| **LS 夏普** | **2.45** | 2.21 |
| LS 最大回撤 | -31.4% | -27.9% |

### 判定

**观察中（等价替代）**：t=2.77 仍显著，spread/夏普维度优于种子（+10%/+11%），
但 IC 维度略低（0.028 vs 0.032）、回撤略差（-31% vs -28%）。市值与成交额
触发期高相关 → 两变体近乎同信息的不同加权；**成交额龙头在组合维度（夏普）
更优，市值龙头在 IC 维度更纯**。不替换种子，并存观察。

## 5. 迭代历史

| 日期 | 变体 | 改动 | IC mean | t | 结论 |
|------|------|------|---------|---|------|
| 2026-08-18 | `crash_bottom_leader_adv20` | 龙头 市值→成交额 | 0.0284 | 2.77 | 观察中——夏普更优、IC 略低 |

## 6. 风险与备注

- 注意：`adv20` 是平台薄封装（展开为 `ts_mean(volume, 20)`），warmup 自动提取覆盖。
- 组合变体 [`crash_bottom_leader_adv_mv`](crash_bottom_leader_adv_mv.md)（市值+成交额
  叠加）证伪——两维度冗余，不可叠加。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
