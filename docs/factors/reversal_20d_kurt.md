---
xname: reversal_20d_kurt
formula: |
  signal = ts_kurtosis(returns(close), 20)
tags: [mine_b3r51, reversal, kurtosis, recent_strong]
params: {}
status: 无效（全期弱；近 26 周显著）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_kurt 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_kurt`（= `factor/reversal_20d_kurt.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——全期弱；近 26 周显著 |
| 标签 | mine_b3r51, reversal, kurtosis, recent_strong |
| 创建 | 2026-08-18（批次 3 轮次 51，种子 `vol_run_energy_rl120_turn`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：峰度（尾部厚度）维度——极端波动频率与未来收益。

**数学表达**：

```
signal = kurtosis(returns(close), 20d)
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
name: reversal_20d_kurt
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
  from polars_ta.prefix.wq import ts_kurtosis
  signal = ts_kurtosis(returns(close), 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_kurt/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0065 |
| t 值 | 1.53 |
| IR | 0.115 |
| 近 26 周 mean / t | 0.0273 / 2.51（**近期显著**） |

| 项 | 值 |
|----|----|
| spread | 0.00085 |
| D1 / D10 | 0.00282 / 0.00196 |

### 判定

- 全期 IC 0.0065（t=1.53 不显著）；**近 26 周 t=2.51 显著**
  （2026 年极端波动股做空有效——环境变化或近期市场风格）。
- 结论：**无效（全期弱）**——峰度信息弱于偏度（t=4.29）；
  近 26 周亮点记录（作为近期观察项）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_kurt`（初始） | 批次 3 轮 51：K2 收益峰度 | 0.0065 | 1.53 | 无效：全期弱、近 26 周显著 |

## 6. 风险与备注

- **矩维度结论**：偏度（t=4.29）优于峰度（t=1.53）——彩票偏好（偏度）
  是有效矩维度，峰度边际。
- 种子 [`vol_run_energy_rl120_turn.md`](vol_run_energy_rl120_turn.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
