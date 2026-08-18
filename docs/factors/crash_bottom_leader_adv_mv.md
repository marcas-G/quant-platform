---
xname: crash_bottom_leader_adv_mv
formula: |
  signal = (cs_rank(-mom20) + cs_rank(log(circ_mv)) + cs_rank(log(adv20(volume)))) * mask(idx20 < -0.08)
tags: [strategy, crash_bottom, market_timed, refuted]
params: {}
status: 无效（市值+成交额叠加证伪：t=0.68，维度冗余）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# crash_bottom_leader_adv_mv 因子档案（市值+成交额双龙头）

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `crash_bottom_leader_adv_mv`（= `factor/crash_bottom_leader_adv_mv.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效（变异证伪，种子 [`crash_bottom_leader_timed`](crash_bottom_leader_timed.md) 保持最优） |
| 标签 | strategy, crash_bottom, market_timed, refuted |
| 创建 | 2026-08-18（优化轮 2 V5） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**变异点**：把轮 2 V4 的成交额龙头**叠加**到种子的市值龙头（三层：
超跌 + 市值 + 成交额）。

**变异假设**（证伪）：市值与成交额提供互补信息（V4 的夏普提升来源可叠加）。

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
  signal = (cs_rank(-_mom) + cs_rank(log(circ_mv)) + cs_rank(log(adv20(volume)))) * _crash
```

## 4. 验证结果

> 数据快照自 `results/crash_bottom_leader_adv_mv/summary.json`（2026-08-18）。

| 指标 | 本变体 | 种子（对照） |
|------|--------|-------------|
| RankIC mean | 0.0081 | 0.0321 |
| t 值 | 0.68（完全不显著） | 2.84 |
| 符号一致性 | false | true |
| spread | 0.0065 | 0.0077 |
| LS 年化 / 夏普 | 37.3% / 1.78 | 50.1% / 2.21 |

### 判定

**证伪**：IC 暴跌至 0.008（t=0.68）、符号不一致。**市值与成交额在触发期高度
相关**（恐慌放量期大票放量）——叠加 = 重复计数同一维度，与轮 1 V2（稳健）
同构。**正交性规则第二次验证**：触发期新成分必须与现有成分正交，相关性高的
维度只能替换不能叠加。

## 5. 迭代历史

| 日期 | 变体 | 改动 | IC mean | t | 结论 |
|------|------|------|---------|---|------|
| 2026-08-18 | `crash_bottom_leader_adv_mv` | 市值+成交额叠加 | 0.0081 | 0.68 | 证伪——维度冗余 |

## 6. 风险与备注

- 正交性规则（两次验证）：触发期成分须与超跌正交（stable 证伪）、
  相似维度只能替换不能叠加（adv_mv 证伪）。
- 与 [`crash_bottom_leader_adv20`](crash_bottom_leader_adv20.md) 对照：替换成立、
  叠加证伪——市值/成交额二选一。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
