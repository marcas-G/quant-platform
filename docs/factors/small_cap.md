---
xname: small_cap
formula: |
  signal = -log(circ_mv)
tags: [classic_seed, size, small_cap]
params: {}
status: 无效（t=1.53 不显著）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# small_cap 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `small_cap`（= `factor/small_cap.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效（t=1.53 不显著） |
| 标签 | classic_seed, size, small_cap |
| 创建 | 2026-08-18（经典因子种子扩充） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

市值对数取负（小市值溢价）——小盘股预期收益更高。

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
name: small_cap
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
  signal = -log(circ_mv)
```

## 4. 验证结果

> 数据快照自 `results/small_cap/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 4887 |
| 信号缺失率 | 0.0492 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0219 |
| t 值 | 1.53 |
| IR | 0.113 |
| 近 26 周 mean / t | -0.0151 / -0.52 |
| PearsonIC mean | 0.0151（t=1.37） |

| 项 | 值 |
|----|----|
| spread | 0.00215 |
| D1 / D10 | 0.00411 / 0.00196 |

### 判定

t=1.53 不显著、近 26 周 t=-0.52（近期小盘弱）——A 股 2023-2026 小市值
溢价不明显（风格切换）。
结论：**无效（保留作种子）**——规模维度当前无溢价，正交种子价值保留。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `small_cap`（初始） | 经典种子扩充 | 0.0219 | 1.53 | 无效（t=1.53 不显著） |

## 6. 风险与备注

- **正交种子价值**：与反转家族低相关（预期）——挖因子新种子池成员。
- 缺失率 0.0492。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
