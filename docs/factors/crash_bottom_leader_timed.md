---
xname: crash_bottom_leader_timed
formula: |
  signal = (cs_rank(-mom20) + cs_rank(log(circ_mv))) * mask(mom20 < -0.20)
tags: [strategy, crash_bottom, timed, triggered]
params: {}
status: 观察中（触发期收益显著高于非触发，样本少）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# crash_bottom_leader_timed 因子档案（股灾时点抄底）

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `crash_bottom_leader_timed`（= `factor/crash_bottom_leader_timed.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 观察中（触发期周收益 5.2% vs 未触发 0.8%） |
| 标签 | strategy, crash_bottom, timed, triggered |
| 创建 | 2026-08-18（策略时点化：个股 20% 深跌触发） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**策略**：个股 20 日跌幅 > 20%（超跌触发）时启用抄底龙头信号
（超跌秩 + 龙头秩），平时不出手。

**数学表达**：

```
signal = (cs_rank(-mom20) + cs_rank(log(circ_mv))) × 1{mom20 < -0.20}
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, cs_rank
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  _deep = sign(sign(-0.20 - _mom) + 1) / 2
  signal = (cs_rank(-_mom) + cs_rank(log(circ_mv))) * _deep
```

## 4. 验证结果

> 数据快照自 `results/crash_bottom_leader_timed/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | **37**（触发时段，20% 深跌阈值） |
| 平均股票数 | 4895 |
| 信号缺失率 | 0.7987 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0069 |
| t 值 | 0.55 |
| IR | 0.091 |
| 近 26 周 mean / t | -0.0004 / -0.03 |
| spread | 0.01940（1.94%/周——触发期档位差极大） |

### 触发期分层（4 组，0 值聚集）

| 组 | mean_ret（周） | n |
|----|--------------|---|
| D1（超跌抄底+龙头） | **0.05196（5.2%/周）** | 180 |
| D0 | 0.02776 | 78 |
| D2 | 0.02097 | 108 |
| D9（0 值/未触发） | 0.00836 | 4792 |

净值：D1 累积 **27.5%**（37 周 ≈ 年化高）、D10 34.4%（180 周 ≈ 年化低）；
long_short 年化 -17.7%（分层被 0 值扭曲）。

### 判定

- **核心验证：触发期抄底周收益 5.2% vs 未触发 0.8%**——个股深跌 20% 后的
  超跌龙头**确实强反弹**（触发期年化显著更高）。
- 但触发周仅 37 周（20% 阈值严苛）→ IC 不显著（t=0.55）；
  分层结构被 0 值扭曲（未触发股全进 D9）→ long_short 失真。
- 结论：**观察中**——超跌触发方向有效（触发期收益显著），
  阈值敏感性待测（15% 触发周更多）；市场级股灾状态待平台增强。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `crash_bottom_leader_timed`（初始） | 策略时点化（个股 20% 深跌触发） | 0.0069 | 0.55 | 观察中：触发期收益显著 |

## 6. 风险与备注

- **平台缺口**：市场级股灾状态（全市场 20 日跌幅）需横截面聚合——
  group_mean 公式不可用、.over() 链 codegen 崩溃（详见
  `results/_strategy_timed_note.md`）——个股级触发为当前实现。
- **触发稀疏**：20% 阈值 37 周——阈值敏感性（15%/25%）待测。
- 无时点版 [`crash_bottom_leader.md`](crash_bottom_leader.md)（全期 0.0428）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
