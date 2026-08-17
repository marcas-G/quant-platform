---
xname: reversal_20d_volconf
formula: |
  signal = (MA(close,20)/close[t-20]-1) * ts_rank(volume, 20)
tags: [mine_r9, reversal, volume_confirm, marginal]
params: {}
status: 观察中（边际：IC 略降、spread +19%）
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# reversal_20d_volconf 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_volconf`（= `factor/reversal_20d_volconf.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 观察中（边际：IC -14%、spread +19%） |
| 标签 | mine_r9, reversal, volume_confirm, marginal |
| 创建 | 2026-08-17（挖因子批次 2 轮次 9，种子 `reversal_20d`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `reversal_20d` 的隐含假设 (H4) 价格信号自足（缩量阴跌与放量
超调等权）。检验"放量超调反转更强（量价配合）"：加时序量能确认
`× ts_rank(volume, 20)`（0-1 量能分位）——与 turnrank 的横截面换手率正交
（本变异是时序事件维度）。

**核心逻辑**：20 日反转 × 近 20 日量能分位（放量超调权重高）。

**数学表达**：

```
signal = (MA(close,20)/close[t-20] - 1) × ts_rank(volume, 20)
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
name: reversal_20d_volconf
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, ts_rank
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * ts_rank(volume, 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_volconf/summary.json`（2026-08-17）。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 174 |
| 平均股票数 | 4881 |
| 复权 | qfq |
| 信号缺失率 | 7.23% |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0350 |
| t 值 | 3.28 |
| IR | 0.249 |
| 近 26 周 mean | 0.0043 |
| 近 26 周 t | 0.14 |
| PearsonIC mean（原始信号） | -0.0229（t=-2.36） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00430（0.43%/周） |
| 单调性 | false |
| D1 mean_ret | 0.00274 |
| D10 mean_ret | -0.00156 |

### 判定

- 与种子对比：IC 0.0350（0.0409，-14%）、t 3.28（3.47）、IR 0.249（0.260）、
  **spread 0.00430（0.00362，+19%**，D10 更负 -0.00156 vs -0.00097）。
- 近 26 周 t=0.14（种子 0.05）微好。
- 结论：**观察中（边际）**——量能确认增强档位区分（H4' 部分支持），
  但整体秩次预测力略降；与轮 2/轮 1 的口径-条件化变异规律一致：
  分位条件化普遍增强两端区分、对整体 IC 中性偏负。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`reversal_20d_four_dim_tsv` | 批次3轮66：F3 四维加法，见 [`reversal_20d_four_dim_tsv.md`](reversal_20d_four_dim_tsv.md) | 0.0661 | 7.46 | 候选：t/IR 全库新纪录 |
| 2026-08-18 | 衍生：`reversal_20d_intraday_flow` | 批次3轮57：N3 intraday×flow，见 [`reversal_20d_intraday_flow.md`](reversal_20d_intraday_flow.md) | 0.0559 | 5.29 | 观察中：IR 超两父本 |
| 2026-08-18 | 衍生：`reversal_20d_four_dim10` | 批次3轮45：D2 corr10 四维，见 [`reversal_20d_four_dim10.md`](reversal_20d_four_dim10.md) | 0.0721 | 7.40 | **候选**：新全库最强 |
| 2026-08-18 | 衍生：`reversal_20d_pricevolcorr` | 批次3轮32：C2 量价相关，见 [`reversal_20d_pricevolcorr.md`](reversal_20d_pricevolcorr.md) | 0.0425 | 6.36 | **强候选**：IR/t 全库纪录、近 26 周仍有效 |
| 2026-08-18 | 衍生：`reversal_20d_volconf_fwd` | 批次3轮16：V3 前向填充，见 [`reversal_20d_volconf_fwd.md`](reversal_20d_volconf_fwd.md) | 0.0350 | 3.28 | **无效**：fillna 对 NaN 无效果 |
| 2026-08-18 | 衍生：`reversal_20d_volturn` | 批次3轮2：V3 换手率条件化叠加，见 [`reversal_20d_volturn.md`](reversal_20d_volturn.md) | 0.0366 | 3.25 | 观察中：spread 超两父本 |
| 2026-08-17 | `reversal_20d_volconf`（初始） | 挖因子轮 9：H4 量能确认 `× ts_rank(volume,20)` | 0.0350 | 3.28 | 边际：spread +19%、IC -14% |

## 6. 风险与备注

- **与 turnrank 正交性**：横截面换手率（投机强度）与时序量能（放量事件）
  两个维度已分别测试——turnrank 全期略优（IC 0.0419）；二者组合
  （`× cs_rank(turnover) × ts_rank(volume,20)`）待迭代。
- 近 26 周与种子同为衰减区间。
- 种子 [`reversal_20d.md`](reversal_20d.md) 为反转基准。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
