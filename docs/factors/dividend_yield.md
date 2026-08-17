---
xname: dividend_yield
formula: |
  signal = dv_ratio
tags: [classic_seed, value, dividend]
params: {}
status: 观察中（t=2.31 显著、spread 负）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# dividend_yield 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `dividend_yield`（= `factor/dividend_yield.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 观察中（t=2.31 显著、spread 负） |
| 标签 | classic_seed, value, dividend |
| 创建 | 2026-08-18（经典因子种子扩充） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

股息率（dv_ratio）——高股息股票预期收益更高。

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
name: dividend_yield
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
  signal = dv_ratio
```

## 4. 验证结果

> 数据快照自 `results/dividend_yield/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 4421 |
| 信号缺失率 | 0.1414 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0260 |
| t 值 | 2.31 |
| IR | 0.171 |
| 近 26 周 mean / t | 0.0521 / 1.20 |
| PearsonIC mean | 0.0022（t=0.25） |

| 项 | 值 |
|----|----|
| spread | -0.00042 |
| D1 / D10 | 0.00309 / 0.00351 |

### 判定

t=2.31 显著但 spread 为负（档位反向：高股息档收益低——A 股高股息多为防御性
大票，短期收益弱）；缺失率 14%。
结论：**观察中**——股息维度有秩次信息但方向与经典预期相反（或受样本期风格影响）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `dividend_yield`（初始） | 经典种子扩充（价值维度） | 0.0260 | 2.31 | 观察中（t=2.31 显著、spread 负） |

## 6. 风险与备注

- **正交种子价值**：价值维度与反转家族低相关（预期）——挖因子新种子池成员；
  表现差也可（多样性优先）。
- 缺失率 0.1414（daily_basic 早期覆盖）——评估已按实际行。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
