---
xname: value_ep
formula: |
  signal = 1 / pe_ttm
tags: [classic_seed, value, ep]
params: {}
status: 候选（t=2.31 显著）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# value_ep 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `value_ep`（= `factor/value_ep.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 候选（t=2.31 显著） |
| 标签 | classic_seed, value, ep |
| 创建 | 2026-08-18（经典因子种子扩充） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

盈利收益率（1/PE_TTM）——经典价值因子：低估值股票预期收益更高。

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
name: value_ep
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
  signal = 1 / pe_ttm
```

## 4. 验证结果

> 数据快照自 `results/value_ep/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 3730 |
| 信号缺失率 | 0.2745 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0312 |
| t 值 | 2.31 |
| IR | 0.171 |
| 近 26 周 mean / t | 0.0562 / 1.40 |
| PearsonIC mean | 0.0026（t=0.24） |

| 项 | 值 |
|----|----|
| spread | 0.00085 |
| D1 / D10 | 0.00269 / 0.00184 |

### 判定

t=2.31 显著；IR 0.171；spread 0.085%/周；缺失率 27%（pe_ttm 早期覆盖不足）。
结论：**候选**——价值维度独立显著（与反转家族低相关，正交种子价值确认）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`value_retained` | 批次4轮15：EP→留存盈利，见 [`value_retained.md`](value_retained.md) | -0.0270 | -2.34 | **无效**：方向反转（A 股分红是质量信号） |
| 2026-08-18 | `value_ep`（初始） | 经典种子扩充（价值维度） | 0.0312 | 2.31 | 候选（t=2.31 显著） |

## 6. 风险与备注

- **正交种子价值**：价值维度与反转家族低相关（预期）——挖因子新种子池成员；
  表现差也可（多样性优先）。
- 缺失率 0.2745（daily_basic 早期覆盖）——评估已按实际行。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
