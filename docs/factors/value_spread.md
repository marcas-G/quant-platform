---
xname: value_spread
formula: |
  signal = pb / pe_ttm
tags: [mine_b4r12, value, pb_pe_spread, falsified]
params: {}
status: 无效（全期不显著；近 26 周亮点）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# value_spread 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `value_spread`（= `factor/value_spread.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效——估值价差全期无预测力 |
| 标签 | mine_b4r12, value, pb_pe_spread, falsified |
| 创建 | 2026-08-18（批次 4 轮次 12，种子 `value_bp`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**隐含假设深挖**：BP/EP 都是价值表达，PB/PE 比揭示盈利-资产相对定价——
"深度价值（资产与盈利双便宜）应有溢价"。

**数学表达**：

```
signal = pb / pe_ttm
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
name: value_spread
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
  signal = pb / pe_ttm
```

## 4. 验证结果

> 数据快照自 `results/value_spread/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 3729 |
| 信号缺失率 | 0.2746 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0062 |
| t 值 | -0.71 |
| IR | -0.052 |
| 近 26 周 mean / t | 0.0246 / 1.67 |

| 项 | 值 |
|----|----|
| spread | -0.00194 |

### 判定

- vs value_bp/EP：IC -0.0062（t=-0.71 不显著）——**估值价差不携带
  独立信息**（价值信号在 BP/EP 各自水平）。
- **近 26 周 t=1.67（亮点）**——近期盈利-资产定价差异有效。
- 结论：**无效（全期证伪）**——PB/PE 相对定价非全期价值维度；
  近 26 周作为观察项。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `value_spread`（初始） | 批次 4 轮 12：估值价差 | -0.0062 | -0.71 | 无效：价差无独立信息 |

## 6. 风险与备注

- **价值维度结构**：BP/EP 水平有效、二者比值无效——价值信息在绝对水平。
- 种子 [`value_bp.md`](value_bp.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
