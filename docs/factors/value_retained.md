---
xname: value_retained
formula: |
  signal = 1/pe_ttm - dv_ratio
tags: [mine_b4r15, value, retained, dividend_preference, inverted]
params: {}
status: 无效（方向反转——A 股分红是正信号）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# value_retained 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `value_retained`（= `factor/value_retained.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效——留存盈利方向反转（A 股分红偏好） |
| 标签 | mine_b4r15, value, retained, dividend_preference, inverted |
| 创建 | 2026-08-18（批次 4 轮次 15，种子 `value_ep`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**隐含假设深挖**：EP 隐含"盈利用途（分红 vs 留存）无关"——留存盈利
（E-D）/P = 增长潜力代理。

**数学表达**：

```
signal = 1/pe_ttm - dv_ratio   （留存盈利收益率）
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
name: value_retained
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
  signal = 1 / pe_ttm - dv_ratio
```

## 4. 验证结果

> 数据快照自 `results/value_retained/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 3488 |
| 信号缺失率 | 0.322 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0270 |
| t 值 | -2.34 |
| IR | -0.174 |
| 近 26 周 mean / t | -0.0505 / -1.12 |

| 项 | 值 |
|----|----|
| spread | 0.00019 |

### 判定

- **方向反转且显著负**（IC -0.0270, t=-2.34）：留存盈利高（少分红多留存）
  → 未来收益**低**——与增长潜力假设相反。
- **方向性发现**：A 股分红倾向是正信号（dividend_yield 正 IC 2.31 + 本因子
  负 IC）——不分红（高留存）= 盈利质量差/铁公鸡；分红 = 质量信号。
- 结论：**无效（方向反转）**——留存假设反了；
  "分红是质量信号"为有价值的方向性结论。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `value_retained`（初始） | 批次 4 轮 15：EP→留存盈利 | -0.0270 | -2.34 | 无效：方向反转（分红偏好） |

## 6. 风险与备注

- **分红质量信号**：dividend_yield（正）与 value_retained（负）互证——
  A 股分红倾向是质量/治理信号。
- 种子 [`value_ep.md`](value_ep.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
