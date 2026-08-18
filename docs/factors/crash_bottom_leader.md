---
xname: crash_bottom_leader
formula: |
  signal = cs_rank(-mom20) + cs_rank(log(circ_mv)) + cs_rank(-ts_std_dev(returns,20))
tags: [strategy, crash_bottom, leader, multi_component]
params: {}
status: 候选（策略因子：超跌×龙头×稳健）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# crash_bottom_leader 因子档案（股灾抄底龙头策略）

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `crash_bottom_leader`（= `factor/crash_bottom_leader.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 候选（策略因子：IC 0.0428/t 2.95） |
| 标签 | strategy, crash_bottom, leader, multi_component |
| 创建 | 2026-08-18（策略组合：现有因子成分） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**策略假设**：股灾抄底龙头——极端下跌时，跌幅深的大盘低波动股（超跌龙头，
优质资产错杀）反弹最强。

**三个成分**（均来自因子库已验证维度）：

| 成分 | 表达 | 来源 |
|------|------|------|
| 超跌 | `-mom20` | reversal 家族 |
| 龙头 | `log(circ_mv)` | small_cap 反向 |
| 稳健 | `-ts_std_dev(returns,20)` | low_vol_20d |

**数学表达**：

```
signal = cs_rank(-mom20) + cs_rank(log(circ_mv)) + cs_rank(-vol20)
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
name: crash_bottom_leader
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, ts_std_dev, cs_rank
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  signal = cs_rank(-_mom) + cs_rank(log(circ_mv)) + cs_rank(-ts_std_dev(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/crash_bottom_leader/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0428 |
| t 值 | 2.95 |
| IR | 0.221 |
| 近 26 周 mean / t | 0.0511 / 1.24 |
| PearsonIC mean | 0.0065（t=0.55） |

| 项 | 值 |
|----|----|
| spread | 0.00217 |
| D1 / D10 | 0.00203 / -0.00014 |

### 判定

- IC 0.0428（t=2.95 显著、IR 0.221）、spread 0.22%/周、近 26 周 t=1.24（仍有效）。
- **独立性**：与 reversal_20d 相关 **-0.34**（做多超跌端——方向独立）；
  与 low_vol_20d 相关 **0.76**（龙头/稳健成分主导）。
- 结论：**候选（策略因子）**——"超跌×龙头×稳健"组合成立；
  有效但弱于 low_vol 单因子（0.0696）——稳健成分主导，
  超跌贡献方向独立性。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `crash_bottom_leader`（初始） | 策略组合（三层秩次加法） | 0.0428 | 2.95 | 候选：有效独立方向 |

## 6. 风险与备注

- **成分主导**：low_vol 贡献最大（相关 0.76）——"稳健"是策略核心，
  "超跌"提供与反转家族的独立方向（-0.34）。
- **股灾识别缺失**：策略未做市场级股灾状态判定（index_daily 不可跨表引用）——
  样本期内是"持续抄底"而非"仅股灾时抄底"。
- **拆层可做**：超跌×龙头（去稳健）/超跌×稳健（去龙头）可定位成分贡献。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
