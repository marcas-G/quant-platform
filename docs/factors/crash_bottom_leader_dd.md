---
xname: crash_bottom_leader_dd
formula: |
  signal = (cs_rank(-dd250) + cs_rank(log(circ_mv))) * mask(idx20 < -0.08)
tags: [strategy, crash_bottom, market_timed, refuted]
params: {}
status: 无效（回撤深度超跌证伪：IC t=1.56 不显著、LS 夏普 1.09 < 种子 2.21）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# crash_bottom_leader_dd 因子档案（回撤深度超跌）

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `crash_bottom_leader_dd`（= `factor/crash_bottom_leader_dd.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效（变异证伪，种子 [`crash_bottom_leader_timed`](crash_bottom_leader_timed.md) 保持最优） |
| 标签 | strategy, crash_bottom, market_timed, refuted |
| 创建 | 2026-08-18（优化轮 1 V1） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**变异点**：种子用 `mom20`（20 日动量）度量"超跌"，本变体替换为**距 52 周高点回撤
深度**：`_dd = close / ts_max(ts_delay(close, 1), 250) - 1`。

**变异假设**（证伪）：股灾抄底语义下"跌得深"= 距高点的回撤深度（空间维度）；
mom20 混入短期动量噪声（急跌后的小反弹会让动量回正，但距高点仍深）。

**保留**：触发层（中证1000 20日 <-8%）、龙头成分（log circ_mv）、处理链、方向。

## 3. 参数与实现

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2015-01-01 ~ 2026-07-31（分块计算 --chunk-days 500）
process: winsorize(quantile=0.99) → standardize()
```

```yaml
formula: |
  from polars_ta.prefix.wq import ts_sum, ts_max, ts_delay, cs_rank
  _mkt20 = ts_sum(idx_ret, 20)
  _crash = sign(sign(-0.08 - _mkt20) + 1) / 2
  _dd = close / ts_max(ts_delay(close, 1), 250) - 1
  signal = (cs_rank(-_dd) + cs_rank(log(circ_mv))) * _crash
```

## 4. 验证结果

> 数据快照自 `results/crash_bottom_leader_dd/summary.json`（2026-08-18）。

| 指标 | 本变体 | 种子（对照） |
|------|--------|-------------|
| 有效周 | 71（250 日窗口吞掉 2015 早期） | 106 |
| RankIC mean | 0.0207 | 0.0321 |
| t 值 | 1.56（不显著） | 2.84 |
| IR | 0.185 | 0.276 |
| spread | 0.0049 | 0.0077 |
| LS 年化 / 夏普 | 22.8% / 1.09 | 50.1% / 2.21 |

### 判定

**证伪**：250 日回撤深度全面劣于 20 日动量——IC/t/分层/LS 全维度倒退，且
回撤窗口还丢失样本早期触发周。**股灾抄底的"超跌"是时效性急跌（当下错杀），
不是长期回撤**；20 日动量窗口虽含噪声，但捕捉"当下"的信息价值更高
（时效性维度：短窗口 > 长窗口）。

## 5. 迭代历史

| 日期 | 变体 | 改动 | IC mean | t | 结论 |
|------|------|------|---------|---|------|
| 2026-08-18 | `crash_bottom_leader_dd` | 超跌度量 mom20 → dd250 | 0.0207 | 1.56 | 证伪——时效性优先 |

## 6. 风险与备注

- 变异过程同时暴露并修复了分块计算两个内存缺陷（全列面板累积 OOM、
  评估重复对齐 segfault），见分块计算 spec 迭代记录。
- 回撤类因子（dd250）在非时点场景可能仍有用（如全期反转），本次仅证伪
  "股灾触发期"场景。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
