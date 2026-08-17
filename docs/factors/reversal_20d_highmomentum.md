---
xname: reversal_20d_highmomentum
formula: |
  signal = close / ts_max(high, 20) - 1   # direction=1（新高端做多）
tags: [mine_b3r56, reversal, high_momentum, falsified]
params: {}
status: 无效（距高点距离双向无全期信息）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_highmomentum 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_highmomentum`（= `factor/reversal_20d_highmomentum.yaml`） |
| 类别 | custom |
| 方向 | `1`（新高端做多） |
| 状态 | 无效——距高点距离双向无全期信息 |
| 标签 | mine_b3r56, reversal, high_momentum, falsified |
| 创建 | 2026-08-18（批次 3 轮次 56，种子 `reversal_20d_near5`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：drawdown（跌深做多）证伪后的反向——新高动量（52 周新高效应方向，
direction=1 做多新高端）。

**数学表达**：

```
signal = close/ts_max(high, 20) - 1   （direction=1：新高端做多）
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
name: reversal_20d_highmomentum
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
  from polars_ta.prefix.wq import ts_max
  signal = close / ts_max(high, 20) - 1
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_highmomentum/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0160 |
| t 值 | 1.20 |
| IR | 0.090 |
| 近 26 周 mean / t | 0.0537 / 1.56 |

| 项 | 值 |
|----|----|
| spread | 0.00217 |
| D1 / D10 | 0.00352 / 0.00135 |

### 判定

- IC 0.0160（t=1.20 全期不显著）；近 26 周 t=1.56（边际）。
- 与 drawdown（-1 方向）同为弱——**距 20 日高点距离双向均无全期信息**
  （新高效应在 20 日尺度不存在）。
- 结论：**无效**——ts_max 距离维度关闭（双向证伪）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_highmomentum`（初始） | 批次 3 轮 56：H2 新高动量 | 0.0160 | 1.20 | 无效：距高点双向无信息 |

## 6. 风险与备注

- **维度关闭**：ts_max 距离维度双向证伪——不再探索新高/回撤结构。
- 基准 [`reversal_20d_drawdown.md`](reversal_20d_drawdown.md)（反向）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
