---
xname: vol_run_energy_rl120_turn
formula: |
  signal = -ts_rank(run_freq(turnover, rl_win), rl_win) * oi_energy(turnover, win) * gain
tags: [mine_r1, run_length, oi_energy, turnover, coverage_fix]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 候选
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# vol_run_energy_rl120_turn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_rl120_turn`（= `factor/vol_run_energy_rl120_turn.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 候选（t=5.26, IR=0.41, 近 26 周仍显著） |
| 标签 | mine_r1, run_length, oi_energy, turnover, coverage_fix |
| 创建 | 2026-08-17（挖因子批次 2 轮次 1，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `vol_run_energy` 的两个隐含假设——(H2) 游程频率需 500 日样本
（代价：缺失率 68%、次新股被系统性排除）；(H8) volume 绝对变化无股本结构污染
（送转/增发让 volume 跳变产生假放量）。本因子变异 H2（游程窗口参数化 rl_win=120）
与 H8（volume→turnover），实现"更详细准确的因子表达"（结构不变，口径与尺度精确化）。

**核心逻辑**：换手率口径的放量上涨频率（120 日）× 量能钟形调制——同上
[`vol_run_energy.md`](vol_run_energy.md) 的游程×能量结构，但覆盖大幅扩大。

**数学表达**：

```
e     = ts_rank(|ts_delta(turnover, 1)|, win)
bell  = sqrt(e * (1 - e))
rl    = ts_count(sign(ts_delta(turnover, 1)) == 1, rl_win)
signal = -ts_rank(rl, rl_win) * bell * gain
```

**输入数据**：`turnover`（daily_basic.turnover_rate 映射，公式引用自动加载）。

## 3. 参数与实现

### 参数表

| 参数 | 默认值 | 含义 | 有效范围 |
|------|--------|------|----------|
| `win` | 200 | 量能窗口 | 正整数 >1 |
| `gain` | 2.0 | 信号振幅 | >0 |
| `rl_win` | 120 | 游程频率窗口（变异 H2） | 正整数 >1 |

### 处理链

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2022-01-01 ~ 2026-07-31
process: winsorize(quantile=0.99) → standardize()
target: forward_return_5d
adjustment: qfq
```

### 实现（YAML 全文）

```yaml
name: vol_run_energy_rl120_turn
category: custom
direction: -1
params: {win: 200, gain: 2.0, rl_win: 120}
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2022-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_rank, ts_delta, ts_count

  def oi_energy(x, n):
      _e = ts_rank(ts_delta(x, 1).abs(), n)
      return sqrt(_e * (1 - _e))

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) == 1, ${rl_win})
  signal = -ts_rank(_rl, ${rl_win}) * _energy * ${gain}
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_rl120_turn/summary.json`（2026-08-17）。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4566 |
| 复权 | qfq |
| 信号缺失率 | 35.51%（种子 67.99%） |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0152 |
| t 值 | 5.26 |
| IR | 0.407 |
| 近 26 周 mean | 0.0156 |
| 近 26 周 t | 3.24 |
| PearsonIC mean（原始信号） | -0.0097（t=-4.15） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00252（0.25%/周） |
| 单调性 | false |
| D1 mean_ret | 0.00425 |
| D10 mean_ret | 0.00173 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- t=5.26 强显著；IR 0.41 > 0.3 优秀；近 26 周 t=3.24 **不衰减**（种子 t=1.39）。
- 覆盖翻倍（有效周 86→167、缺失率 68%→36%）：H2 变异消除游程冷启动；
  spread 0.25%/周 > 0.2% 关注线（种子 0.15%）。
- 结论：**候选**——两变异点（rl_win=120 + turnover 口径）全部验证有效，
  全面优于种子；下一步可做 rl_win 更细扫描与 win 联合调优。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`reversal_20d_kurt` | 批次3轮51：K2 收益峰度，见 [`reversal_20d_kurt.md`](reversal_20d_kurt.md) | 0.0065 | 1.53 | **无效**：全期弱、近 26 周显著 |
| 2026-08-18 | 衍生：`reversal_20d_five_dim` | 批次3轮41：E3 第五维，见 [`reversal_20d_five_dim.md`](reversal_20d_five_dim.md) | 0.0713 | 7.11 | **无效**：维度饱和（四维最优） |
| 2026-08-18 | 衍生：`reversal_20d_pricevolcorr60` | 批次3轮34：W2 corr 60 日，见 [`reversal_20d_pricevolcorr60.md`](reversal_20d_pricevolcorr60.md) | 0.0382 | 5.34 | **无效**：20 日是峰；近 26 周 t=1.81 亮点 |
| 2026-08-18 | 衍生：`vol_run_energy_cumret` | 批次3轮23：H2 跨家族乘法组合，见 [`vol_run_energy_cumret.md`](vol_run_energy_cumret.md) | -0.0111 | -1.48 | **无效**：量能-价格耦合，乘法组合方向冲突 |
| 2026-08-18 | 衍生：`vol_run_energy_rl120_turn_up` | 批次3轮3：H4 能量只算放量，见 [`vol_run_energy_rl120_turn_up.md`](vol_run_energy_rl120_turn_up.md) | 0.0139 | 4.49 | **无效**：对称能量更优 |
| 2026-08-17 | `vol_run_energy_rl120_turn`（初始） | 挖因子轮 1：H2 游程窗口参数化 120 + H8 turnover 口径 | 0.0152 | 5.26 | **候选**：覆盖翻倍、近 26 周不衰减 |

## 6. 风险与备注

- **换手率口径依赖**：turnover 来自 daily_basic，2010s 早期覆盖可能不足
  （本样本 2022 起无影响）；历史回测到更早需核对。
- **rl_win=120 单点测试**：仅验证了一个尺度；120 vs 250 的稳定性曲线未扫。
- **相关性**：与 [`vol_run_energy.md`](vol_run_energy.md) 同源（游程×能量结构），
  组合冗余；种子档案已记录本迭代。变异记录 `results/_mine_round_1.md`。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
