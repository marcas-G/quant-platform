---
xname: crash_bottom_leader_timed
formula: |
  signal = (cs_rank(-mom20) + cs_rank(log(circ_mv))) * mask(idx20 < -0.08)
tags: [strategy, crash_bottom, market_timed, strong_triggered]
params: {}
status: 观察中（触发期极强：long_short 年化 96%/夏普 2.42；样本 14 周小）
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
| 状态 | 观察中（触发期极强、样本小） |
| 标签 | strategy, crash_bottom, market_timed, strong_triggered |
| 创建 | 2026-08-18（策略时点化：中证1000 市场股灾触发） |
| 最近更新 | 2026-08-18 |

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
date: 2023-01-01 ~ 2026-07-31
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
  start: "2023-01-01"
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

> 数据快照自 `results/crash_bottom_leader_timed/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | **14**（中证1000 20 日跌 >8% 触发时段） |
| 平均股票数 | 4910 |
| 信号缺失率 | 0.9205（92% 时间非触发） |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0856 |
| t 值 | 1.41（边际——14 周样本） |
| IR | 0.378 |
| 近 26 周 mean / t | 0.0856 / 1.41 |
| spread | 0.01810（1.81%/周） |

### 触发期分层（**D0→D9 完美单调**）

| 组 | mean_ret（周） |
|----|--------------|
| D0 | 0.01380 |
| D5 | 0.00935 |
| D9 | -0.00431 |

净值（触发期）：D1 +13.6%、D10 -15.0%；
**long_short 年化 0.955939、夏普 2.421502**。

### 判定

- **触发期极强**：档位完美单调（D0→D9 递减）、做多 D1/做空 D10 年化 96%
  夏普 2.42——**市场股灾时抄底超跌龙头的策略方向强验证**。
- **样本限制**：仅 14 个触发周（中证1000 20 日跌 >8% 在 2023-2026 的时段）——
  IC t=1.41 边际；IR 0.378 + 单调性 + 夏普支持方向。
- 结论：**观察中（触发期强、样本待扩）**——扩展样本期
  （数据自 2000：2015 股灾/2016 熔断/2018 熊市有更多触发周）为下一步。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `crash_bottom_leader_timed`（初始） | 市场级触发（idx_ret 数据层支持） | 0.0856 | 1.41 | 触发期极强、样本小 |

## 6. 风险与备注

- **样本小**：14 周——必须扩样本期复验（2015/2018/2024 多轮股灾）。
- **触发稀疏**：92% 时间空仓——策略本质（只在股灾出手）。
- **数据层新增**：`idx_ret`（中证1000 日收益按需 join，`_MARKET_INDEX` 可换）。
- 无时点版 [`crash_bottom_leader.md`](crash_bottom_leader.md)（全期 0.0428）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
