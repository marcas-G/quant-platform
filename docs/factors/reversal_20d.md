---
xname: reversal_20d
formula: |
  signal = ts_mean(close, 20) / ts_delay(close, 20) - 1   # direction=-1（反转）
tags: [m4b_validation, short_term_reversal, baseline]
params: {}
status: 观察中
created_ts: 2026-08-16
updated_ts: 2026-08-17
---

# reversal_20d 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d`（= `factor/reversal_20d.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空；等价于买入 20 日动量最低者） |
| 状态 | 观察中（全期显著，近 26 周衰减） |
| 标签 | m4b_validation, short_term_reversal, baseline |
| 创建 | 2026-08-16（M4b 平台验证因子） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：A 股周频/月频动量呈显著负向（短期反转异象），是验证平台全链路
（universe → 数据 → 计算 → 评估）的正确性基准因子——统计上应显著，且
`momentum_20d` 是同公式的对照方向（预期显著亏损，证伪方向语义正确）。

**核心逻辑**：过去 20 日涨幅越大的股票，未来 5 日收益越低；direction=-1
把该负相关翻转成做多信号。

**数学表达**：

```
signal = MA(close, 20) / close[t-20] - 1    （20 日动量）
r = corr_rank(signal × direction, fwd_ret_5d)   （方向调整后的 RankIC）
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
name: reversal_20d
category: custom
direction: -1
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

> 数据快照自 `results/reversal_20d/summary.json`（2026-08-17）。
> 重跑 `factorlab run factor/reversal_20d.yaml` 后按新 summary 更新本表。

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
| RankIC mean（方向调整后） | 0.0409 |
| t 值 | 3.47 |
| IR | 0.260 |
| 近 26 周 mean | 0.0018 |
| 近 26 周 t | 0.05 |
| PearsonIC mean（原始信号） | -0.0196（t=-1.87） |

> 语义说明：RankIC 为**方向调整后**（正 = 按 direction=-1 交易有效）；Pearson 为
> 原始信号线性相关（未乘方向，与 momentum_20d 完全一致），负值 = 动量高者未来
> 收益低，与反转异象一致。符号差异来自方向语义，非矛盾。

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00362（0.36%/周） |
| 单调性 | false（D1→D10 大体递减，两端区分明显） |
| D1 mean_ret | 0.00265 |
| D10 mean_ret | -0.00097 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- |t|=3.47 > 2 显著；IR 0.26 处于 0.1-0.3 可研究区间；spread 0.36%/周 > 0.2% 关注线；
  **全期有效 → 候选水平**。
- **但近 26 周 t=0.05、mean≈0.002**：2026 年以来反转明显衰减（大盘环境变化/风格切换）。
- 结论：**观察中**——全期统计成立、近期失效；作为平台验证基准继续保留，
  不做进一步实盘化。下一步可选：换近 26 周窗口复验、与换手率交互分析。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-17 | 衍生：`reversal_20d_volconf` | 挖因子轮 9：H4 量能确认 `× ts_rank(volume,20)`，见 [`reversal_20d_volconf.md`](reversal_20d_volconf.md) | 0.0350 | 3.28 | 边际：spread +19%、IC -14% |
| 2026-08-17 | 衍生：`reversal_20d_nowin` | 挖因子轮 6：H8 移除 winsorize（极值保留），见 [`reversal_20d_nowin.md`](reversal_20d_nowin.md) | 0.0409 | 3.47 | **无效**：与 winsorize 版完全等价 |
| 2026-08-17 | 衍生：`reversal_20d_near5` | 挖因子轮 3：H2 锚结构 → 近端 5 日单点反转，见 [`reversal_20d_near5.md`](reversal_20d_near5.md) | 0.0290 | 2.44 | **无效**：全面劣于 20 日版，证伪"反转近端驱动" |
| 2026-08-16 | `reversal_20d`（初始） | M4b 全链路验证基准 | 0.0409 | 3.47 | 全期显著；近 26 周衰减 |

## 6. 风险与备注

- **近期失效**：近 26 周 t≈0，2026 年反转异象衰减明显；全期显著性主要由 2023-2025 贡献。
- **容量**：短期反转依赖高换手，拥挤时容量差（实盘需换手控制）。
- **相关性**：与 `momentum_20d`（同公式 direction=1，见
  [`momentum_20d.md`](momentum_20d.md)）互为对照——动量方向显著亏损
  （IC=-0.0409, t=-3.47），反证反转方向语义正确。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
