---
xname: reversal_20d_near5
formula: |
  signal = close / ts_delay(close, 5) - 1
tags: [mine_r3, reversal, near_end, falsified]
params: {}
status: 无效（证伪 H2'）
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# reversal_20d_near5 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_near5`（= `factor/reversal_20d_near5.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 无效——证伪"反转近端驱动"假设；保留作对照 |
| 标签 | mine_r3, reversal, near_end, falsified |
| 创建 | 2026-08-17（挖因子批次 2 轮次 3，种子 `reversal_20d`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `reversal_20d` 的隐含假设 (H2) MA(close,20)/close[t-20] 把近端与
远端收益等权混合。检验"反转由**近端超调**驱动"（Lo-MacKinlay 分解文献方向）：
改为 `close/close[t-5]` 近端 5 日单点反转。

**核心逻辑**：近 5 日单点收益反转（纯近端，无 MA 平滑）。

**数学表达**：

```
signal = close / close[t-5] - 1
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
name: reversal_20d_near5
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
  from polars_ta.prefix.wq import ts_delay
  signal = close / ts_delay(close, 5) - 1
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_near5/summary.json`（2026-08-17）。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 181 |
| 平均股票数 | 4881 |
| 复权 | qfq |
| 信号缺失率 | 5.50% |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0290 |
| t 值 | 2.44 |
| IR | 0.181 |
| 近 26 周 mean | -0.0133 |
| 近 26 周 t | -0.47 |
| PearsonIC mean（原始信号） | -0.0134（t=-1.36） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00152 |
| 单调性 | false |
| D1 mean_ret | 0.00102 |
| D10 mean_ret | -0.00051 |

### 判定

- **全面劣于种子**：IC 0.029（种子 0.041）、t 2.44（3.47）、spread 0.15%/周（0.36%/周）、
  近 26 周 t=-0.47（种子 0.05）。
- 结论：**无效（H2' 证伪）**——A 股 20 日反转不是近端驱动；
  20 日 MA 平均成本锚显著优于近端 5 日单点（MA 平滑了日间噪声，
  且反转信号在 ~20 日尺度更完整）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`reversal_5d_corr` | 批次3轮38：N2 秩次加法，见 [`reversal_5d_corr.md`](reversal_5d_corr.md) | 0.0450 | 4.65 | 观察中：IC 超两父本、稳定性降 |
| 2026-08-18 | 衍生：`reversal_5d_turn` | 批次3轮24：N2 换手率条件化，见 [`reversal_5d_turn.md`](reversal_5d_turn.md) | 0.0283 | 2.32 | 观察中：spread+92%、IC 持平 |
| 2026-08-18 | 衍生：`reversal_5d_volconf` | 批次3轮10：N2 量能确认，见 [`reversal_5d_volconf.md`](reversal_5d_volconf.md) | 0.0304 | 2.84 | 观察中：spread+42%，未超 20 日家族 |
| 2026-08-17 | `reversal_20d_near5`（初始） | 挖因子轮 3：H2 锚结构 → 近端 5 日单点 | 0.0290 | 2.44 | 无效：全面劣于 20 日版 |

## 6. 风险与备注

- **证伪价值**：近端驱动假设被数据否定——未来迭代不要在"缩短反转尺度"方向
  重复探索；有效方向是口径精确化（VWAP/换手率条件化，见
  [`momentum_20d_vwap.md`](momentum_20d_vwap.md) 与
  [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md)）。
- 种子 [`reversal_20d.md`](reversal_20d.md) 仍为 20 日反转家族基准。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
