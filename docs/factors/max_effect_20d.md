---
xname: max_effect_20d
formula: |
  signal = ts_max(returns(close), 20)
tags: [classic_seed, max_effect, lottery, strong]
params: {}
status: 候选（强：IC 0.0661, t=5.14）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# max_effect_20d 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `max_effect_20d`（= `factor/max_effect_20d.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强：IC 0.0661, t=5.14） |
| 标签 | classic_seed, max_effect, lottery, strong |
| 创建 | 2026-08-18（经典因子种子扩充） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

20 日最大日收益（MAX 效应）——彩票类股票（单日暴涨）预期未来收益低。

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
name: max_effect_20d
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
  signal = ts_max(returns(close), 20)
```

## 4. 验证结果

> 数据快照自 `results/max_effect_20d/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0661 |
| t 值 | 5.14 |
| IR | 0.385 |
| 近 26 周 mean / t | 0.0640 / 1.53 |
| PearsonIC mean | -0.0197（t=-1.82） |

| 项 | 值 |
|----|----|
| spread | 0.00251 |
| D1 / D10 | 0.00234 / -0.00017 |

### 判定

**t=5.14 强显著、IR 0.385 优秀、近 26 周 t=1.53**——MAX 效应（彩票偏好）
确认；与 skew 相关但独立更强的彩票维度种子。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`max_effect_5d` | 批次4轮14：窗口 20→5，见 [`max_effect_5d.md`](max_effect_5d.md) | 0.0614 | 6.16 | 观察中：t/IR +20%（时效性） |
| 2026-08-18 | `max_effect_20d`（初始） | 经典种子扩充 | 0.0661 | 5.14 | 候选（强：IC 0.0661, t=5.14） |

## 6. 风险与备注

- **正交种子价值**：与反转家族低相关（预期）——挖因子新种子池成员。
- 缺失率 0.0723。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
