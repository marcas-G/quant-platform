---
xname: crash_bottom_leader_timed_stable
formula: |
  signal = (cs_rank(-mom20) + cs_rank(log(circ_mv)) + cs_rank(-vol20)) * mask(idx20 < -0.08)
tags: [strategy, crash_bottom, market_timed, refuted]
params: {}
status: 无效（触发期加回稳健成分证伪：IC 减半 t=1.20，冗余/方向冲突）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# crash_bottom_leader_timed_stable 因子档案（触发期稳健成分）

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `crash_bottom_leader_timed_stable`（= `factor/crash_bottom_leader_timed_stable.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效（变异证伪，种子 [`crash_bottom_leader_timed`](crash_bottom_leader_timed.md) 保持最优） |
| 标签 | strategy, crash_bottom, market_timed, refuted |
| 创建 | 2026-08-18（优化轮 1 V2） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**变异点**：原版三层 [`crash_bottom_leader`](crash_bottom_leader.md)（超跌+龙头+稳健）
时点化时丢弃了"稳健"成分；本变体把它加回时点版：
`+ cs_rank(-ts_std_dev(returns(close), 20))`。

**变异假设**（证伪）：股灾抄底的对象是"优质资产被错杀"——低波动是优质代理，
高波动股是博反弹投机标的（不该抄）。

**保留**：超跌/龙头表达（mom20/log circ_mv）、触发层、处理链、方向。

## 3. 参数与实现

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2015-01-01 ~ 2026-07-31（分块计算 --chunk-days 500）
process: winsorize(quantile=0.99) → standardize()
```

```yaml
formula: |
  from polars_ta.prefix.wq import ts_sum, ts_mean, ts_delay, ts_std_dev, cs_rank
  _mkt20 = ts_sum(idx_ret, 20)
  _crash = sign(sign(-0.08 - _mkt20) + 1) / 2
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  signal = (cs_rank(-_mom) + cs_rank(log(circ_mv)) + cs_rank(-ts_std_dev(returns(close), 20))) * _crash
```

## 4. 验证结果

> 数据快照自 `results/crash_bottom_leader_timed_stable/summary.json`（2026-08-18）。

| 指标 | 本变体 | 种子（对照） |
|------|--------|-------------|
| 有效周 | 106（同种子） | 106 |
| RankIC mean | 0.0178 | 0.0321 |
| t 值 | 1.20（不显著） | 2.84 |
| IR | 0.117 | 0.276 |
| spread | 0.0049 | 0.0077 |
| LS 年化 / 夏普 | 33.9% / 1.26 | 50.1% / 2.21 |

### 判定

**证伪**：IC 减半、t 从 2.84 跌到 1.20（不显著）、LS 夏普 1.26 < 2.21。
触发期内"稳健"成分与"超跌"**冗余/方向冲突**——跌得深的大票本身就是低波动
错杀标的（超跌与低波动同源），第三层重复计数同一维度稀释权重；"低波动溢价"
假设只在非触发期成立（原版三层全期有效的来源）。**时点版两层恰好是原版
三层的精确化**——触发掩码已隐式完成质量过滤。

## 5. 迭代历史

| 日期 | 变体 | 改动 | IC mean | t | 结论 |
|------|------|------|---------|---|------|
| 2026-08-18 | `crash_bottom_leader_timed_stable` | 加回稳健成分（三层） | 0.0178 | 1.20 | 证伪——冗余稀释 |

## 6. 风险与备注

- 反向启示：原版三层在全期有效 ≠ 成分在触发期有效——时点掩码改变成分的
  边际贡献（状态依赖）。
- 平台改进：`returns()` 薄封装在触发掩码公式内可用（无需 import，与原版一致）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
