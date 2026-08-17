---
xname: momentum_20d
formula: |
  signal = ts_mean(close, 20) / ts_delay(close, 20) - 1   # direction=1（动量）
tags: [m4b_validation, momentum, baseline_control]
params: {}
status: 已废弃（对照基准）
created_ts: 2026-08-16
updated_ts: 2026-08-17
---

# momentum_20d 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d`（= `factor/momentum_20d.yaml`） |
| 类别 | custom |
| 方向 | `1`（信号高 → 做多，即买入 20 日动量最高者） |
| 状态 | 已废弃——保留作**对照基准**（证伪方向语义），不用于交易 |
| 标签 | m4b_validation, momentum, baseline_control |
| 创建 | 2026-08-16（M4b 平台验证因子） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：与 `reversal_20d` 共用同一公式，仅 direction 相反。它是平台方向
语义正确性的**反向对照**：A 股周频动量预期显著亏损——若平台方向处理正确，
本因子应得到符号相反、幅度相当的负 IC。

**核心逻辑**：过去 20 日涨幅最大的股票未来 5 日收益最低；direction=1 直接
做多该信号（预期亏损，用于验证）。

**数学表达**：

```
signal = MA(close, 20) / close[t-20] - 1    （与 reversal_20d 逐字相同）
r = corr_rank(signal × direction, fwd_ret_5d)
```

**输入数据**：`close`（前复权）。

## 3. 参数与实现

### 参数表

无参数（固定 20 日窗口）。

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
name: momentum_20d
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
  from polars_ta.prefix.wq import ts_mean, ts_delay
  signal = ts_mean(close, 20) / ts_delay(close, 20) - 1
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d/summary.json`（2026-08-17）。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 复权 | qfq |
| 信号缺失率 | 7.23% |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0409 |
| t 值 | -3.47 |
| IR | -0.260 |
| 近 26 周 mean | -0.0018 |
| 近 26 周 t | -0.05 |
| PearsonIC mean（原始信号） | -0.0196（t=-1.87） |

> 语义说明：RankIC 方向调整后为 **-0.0409**（显著为负 = 动量方向显著亏损），
> 与 reversal_20d 的 +0.0409 幅度一致、符号相反——平台方向语义正确；
> Pearson 未乘方向，与 reversal_20d 完全一致（原始信号线性相关）。

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | -0.00369（动量最高档最差） |
| 单调性 | false（D1→D10 大体递增，两端区分明显） |
| D1 mean_ret | -0.00098 |
| D10 mean_ret | 0.00271 |

### 判定

- |t|=3.47 显著，但方向为**负**（按动量方向交易显著亏钱）。
- 结论：**已废弃（对照基准）**——不构成有效因子，但与 reversal_20d 一起
  构成平台方向语义的对称性验证：同公式 ±方向 → ±IC、±D1/D10 镜像。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`reversal_20d_turn_skew` | 批次3轮62：T3 turn×skew，见 [`reversal_20d_turn_skew.md`](reversal_20d_turn_skew.md) | 0.0633 | 5.74 | **强候选**：IC 超两父本 |
| 2026-08-18 | 衍生：`reversal_20d_four_dim_flow` | 批次3轮60：F2 flow 替换 vol，见 [`reversal_20d_four_dim_flow.md`](reversal_20d_four_dim_flow.md) | 0.0717 | 6.77 | **无效**：vol 维度更优 |
| 2026-08-18 | 衍生：`reversal_20d_corr_skew` | 批次3轮52：C3 corr×skew 组合，见 [`reversal_20d_corr_skew.md`](reversal_20d_corr_skew.md) | 0.0425 | 6.45 | **无效**：skew 冗余于 corr |
| 2026-08-18 | 衍生：`reversal_20d_netflow` | 批次3轮40：F2 净流入代理，见 [`reversal_20d_netflow.md`](reversal_20d_netflow.md) | 0.0417 | 5.01 | 候选：资金流维度显著 |
| 2026-08-18 | 衍生：`reversal_20d_closepos` | 批次3轮29：P2 收盘位置，见 [`reversal_20d_closepos.md`](reversal_20d_closepos.md) | 0.0054 | 0.56 | **无效**：位置维度无信息（含一字板 NaN 修复） |
| 2026-08-18 | 衍生：`momentum_20d_m120` | 批次3轮17：120 日动量方向，见 [`momentum_20d_m120.md`](momentum_20d_m120.md) | -0.0154 | -1.25 | **无效**：反转谱衰减到分界（20-60 日最佳） |
| 2026-08-18 | 衍生：`momentum_20d_open` | 批次3轮7：H3 open 口径，见 [`momentum_20d_open.md`](momentum_20d_open.md) | 0.0386 | 3.31 | **无效**：与 close 动量同构 |
| 2026-08-17 | 衍生：`momentum_20d_net60` | 挖因子轮 8：H1 趋势剥离 `_m20-_m60`，见 [`momentum_20d_net60.md`](momentum_20d_net60.md) | -0.0060 | -0.52 | **无效**：反转方向下档位反向，证伪趋势剥离 |
| 2026-08-17 | 衍生：`momentum_20d_decile` | 挖因子轮 5：H6 连续 → 横截面秩次分档，见 [`momentum_20d_decile.md`](momentum_20d_decile.md) | 0.0406 | 3.45 | **无效**：与连续版完全等价（秩次含全部信息） |
| 2026-08-17 | 衍生：`momentum_20d_vwap` | 挖因子轮 2：变异 H3（close→日频 VWAP amount/volume）+ H9（方向→反转），见 [`momentum_20d_vwap.md`](momentum_20d_vwap.md) | 0.0390 | 3.45 | 全期显著；spread +78%；近 26 周衰减 |
| 2026-08-17 | 衍生：`momentum_20d_turnrank` | 挖因子轮 1：变异 H9（方向→反转）+ H5（同质性→换手率条件化 `× cs_rank(turnover)`），见 [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md) | 0.0419 | 3.37 | 全期显著；spread +30%；近 26 周衰减 |
| 2026-08-16 | `momentum_20d`（初始） | M4b 反向对照 | -0.0409 | -3.47 | 方向语义证伪正确，废弃 |

## 6. 风险与备注

- **不是可交易因子**：本档案仅作方向语义对照，交易请用
  [`reversal_20d.md`](reversal_20d.md)（同公式 direction=-1）。
- 全期负显著 + 近 26 周同样衰减（t=-0.05）：近期动量/反转均走弱，
  说明该信号近一年整体信息含量下降，与 reversal 档案的观察一致。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
