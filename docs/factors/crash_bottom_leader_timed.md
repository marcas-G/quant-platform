---
xname: crash_bottom_leader_timed
formula: |
  signal = (cs_rank(-mom20) + cs_rank(log(circ_mv))) * mask(idx20 < -0.08)
tags: [strategy, crash_bottom, market_timed, strong_triggered]
params: {}
status: 候选（11.5 年 106 触发周：IC t=2.84 显著、档位单调、long_short 夏普 2.21）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# crash_bottom_leader_timed 因子档案（市场级股灾抄底）

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `crash_bottom_leader_timed`（= `factor/crash_bottom_leader_timed.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 候选（扩样复验通过：106 触发周统计显著） |
| 标签 | strategy, crash_bottom, market_timed, strong_triggered |
| 创建 | 2026-08-18（策略时点化：中证1000 市场股灾触发） |
| 最近更新 | 2026-08-18（分块计算扩样 2015-2026） |

## 2. 逻辑

**策略**：**市场级股灾触发**——中证1000 指数 20 日累计跌幅 > 8% 时（股灾状态），
启用"超跌龙头"抄底信号（超跌秩 + 龙头秩），平时不出手。

**市场状态**：`idx_ret`（中证1000 日收益，数据层按需 join）→ `ts_sum(idx_ret, 20)`
= 市场 20 日累计 → `<-8%` 触发掩码。

**数学表达**：

```
signal = (cs_rank(-mom20) + cs_rank(log(circ_mv))) × 1{Σ idx_ret(20d) < -8%}
```

## 3. 参数与实现

### 处理链

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2015-01-01 ~ 2026-07-31（分块计算 --chunk-days 500）
process: winsorize(quantile=0.99) → standardize()
target: forward_return_5d
adjustment: qfq
```

### 实现（YAML 全文）

```yaml
name: crash_bottom_leader_timed
category: custom
direction: 1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2015-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_sum, ts_mean, ts_delay, cs_rank
  _mkt20 = ts_sum(idx_ret, 20)
  _crash = sign(sign(-0.08 - _mkt20) + 1) / 2
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  signal = (cs_rank(-_mom) + cs_rank(log(circ_mv))) * _crash
```

## 4. 验证结果

> 数据快照自 `results/crash_bottom_leader_timed/summary.json`（2026-08-18，分块计算）。

| 项 | 值 |
|----|----|
| 区间 | 2015-01-05 ~ 2026-07-31（11.5 年，1168 万行面板） |
| 周数（有效） | **106**（中证1000 20 日跌 >8% 触发时段：2015 股灾/2016 熔断/2018 熊市/2024 微盘/2025 关税等） |
| 信号缺失率 | 0.8627（86% 时间非触发，空仓） |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0321 |
| t 值 | **2.84（统计显著）** |
| IR | 0.276 |
| 近 26 周 mean / t | 0.0700 / 2.06 |
| 符号一致性 | true |
| spread | 0.00774（0.77%/周） |

### 触发期分层（D0→D9 单调）

| 组 | 年化收益 | 夏普 | 最大回撤 |
|----|---------|------|---------|
| D1 | +47.5% | 1.04 | -35.3% |
| D5 | +37.4% | 0.78 | -42.1% |
| D9 | +19.0% | 0.39 | -37.3% |
| D10 | **-2.6%** | -0.05 | -42.0% |

**long_short 年化 50.1%、夏普 2.21、最大回撤 -27.9%、胜率 62.3%**。

### 判定

- **扩样复验通过**：14 → 106 触发周（覆盖 11.5 年全部股灾时段），IC t 从 1.41
  （边际）→ **2.84（显著）**，符号一致性 true，档位仍单调（D1 +47.5% → D10 -2.6%）。
- 14 周样本的年化 96%/夏普 2.42 是**小样本侥幸**——扩样回归到年化 50%/夏普 2.21，
  仍是极强的市场级时点策略。
- 结论：**候选**——市场股灾时抄底超跌龙头策略方向强验证。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `crash_bottom_leader_timed`（初始） | 市场级触发（idx_ret 数据层支持），2023-2026 样本 | 0.0856 | 1.41 | 触发期极强、样本小 |
| 2026-08-18 | 分块计算扩样 | `--chunk-days 500` 扩到 2015-2026（平台内存优化落地） | 0.0321 | **2.84** | 统计显著，升候选 |
| 2026-08-18 | [`crash_bottom_leader_dd`](crash_bottom_leader_dd.md) | 超跌度量 mom20 → dd250 | 0.0207 | 1.56 | 证伪——超跌是时效性急跌非长期回撤 |
| 2026-08-18 | [`crash_bottom_leader_timed_stable`](crash_bottom_leader_timed_stable.md) | 加回稳健成分（三层） | 0.0178 | 1.20 | 证伪——触发期稳健与超跌冗余稀释 |

## 6. 风险与备注

- **触发稀疏**：86% 时间空仓——策略本质（只在股灾出手），适合作为市场状态
  开关而非全期因子。
- **触发周集中**：106 周分布在少数几段（2015-2016、2018、2024-2026），
  周间相关性高，IR 解读需注意聚类效应。
- **平台能力**：样本扩展依赖分块计算（`--chunk-days 500`，见
  `docs/interface.md` §分块计算）——16GB 内存护栏下 2015+ 全市场才可跑。
- **数据层新增**：`idx_ret`（中证1000 日收益按需 join，`_MARKET_INDEX` 可换）。
- 无时点版 [`crash_bottom_leader.md`](crash_bottom_leader.md)（全期 0.0428）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
