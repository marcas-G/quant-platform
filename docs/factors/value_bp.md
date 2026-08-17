---
xname: value_bp
formula: |
  signal = 1 / pb
tags: [classic_seed, value, bp, strong]
params: {}
status: 候选（强：IC 0.0514, t=4.12）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# value_bp 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `value_bp`（= `factor/value_bp.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 候选（强：IC 0.0514, t=4.12） |
| 标签 | classic_seed, value, bp, strong |
| 创建 | 2026-08-18（经典因子种子扩充） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

账面市值比倒数（1/PB）——经典价值因子：低 PB 股票预期收益更高。

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
name: value_bp
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
  signal = 1 / pb
```

## 4. 验证结果

> 数据快照自 `results/value_bp/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 4863 |
| 信号缺失率 | 0.054 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0514 |
| t 值 | 4.12 |
| IR | 0.305 |
| 近 26 周 mean / t | 0.0493 / 1.16 |
| PearsonIC mean | 0.0099（t=1.02） |

| 项 | 值 |
|----|----|
| spread | 0.00243 |
| D1 / D10 | 0.00298 / 0.00054 |

### 判定

**t=4.12 强显著、IR 0.305 优秀、缺失率仅 5.4%**——库内首个非反转家族强因子
（IC 0.0514 接近优秀线 0.05）。
结论：**候选（强）**——价值维度（BP）为高质量新种子。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `value_bp`（初始） | 经典种子扩充（价值维度） | 0.0514 | 4.12 | 候选（强：IC 0.0514, t=4.12） |

## 6. 风险与备注

- **正交种子价值**：价值维度与反转家族低相关（预期）——挖因子新种子池成员；
  表现差也可（多样性优先）。
- 缺失率 0.054（daily_basic 早期覆盖）——评估已按实际行。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
