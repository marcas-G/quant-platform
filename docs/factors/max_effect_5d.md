---
xname: max_effect_5d
formula: |
  signal = ts_max(returns(close), 5)
tags: [mine_b4r14, max_effect, recent, timeliness]
params: {}
status: 观察中（t/IR 升、IC 略降——暴涨有时效性）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# max_effect_5d 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `max_effect_5d`（= `factor/max_effect_5d.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（近期 MAX 稳定性更强） |
| 标签 | mine_b4r14, max_effect, recent, timeliness |
| 创建 | 2026-08-18（批次 4 轮次 14，种子 `max_effect_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**隐含假设深挖**：20 日窗口隐含"暴涨无时效性"；彩票冲击的可得性
（记忆鲜活度）随天数衰减——近期 5 日 MAX 更鲜活。

**数学表达**：

```
signal = max(returns, 5d)
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
name: max_effect_5d
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
  from polars_ta.prefix.wq import ts_max
  signal = ts_max(returns(close), 5)
```

## 4. 验证结果

> 数据快照自 `results/max_effect_5d/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 181 |
| 平均股票数 | 4886 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0614 |
| t 值 | 6.16 |
| IR | 0.458 |
| 近 26 周 mean / t | 0.0359 / 1.20 |

| 项 | 值 |
|----|----|
| spread | 0.00211 |
| D1 / D10 | 0.00168 / -0.00044 |

### 判定

- vs max_20d：IC -7%（0.0661→0.0614）、**t +20%（5.14→6.16）**、
  **IR +19%（0.385→0.458）**——**暴涨冲击部分有时效性**
  （近期 MAX 稳定性更强、彩票属性更鲜活）。
- 结论：**观察中（边际）**——5 日与 20 日互补（近期稳定性/全窗水平）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `max_effect_5d`（初始） | 批次 4 轮 14：窗口 20→5（时效性） | 0.0614 | 6.16 | 观察中：t/IR 升 |

## 6. 风险与备注

- **暴涨时效性**：彩票冲击的可得性衰减——近期 MAX 更稳定；
  与 20 日版互补（近/全窗）。
- 种子 [`max_effect_20d.md`](max_effect_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
