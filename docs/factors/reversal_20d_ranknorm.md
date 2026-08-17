---
xname: reversal_20d_ranknorm
formula: |
  signal = ts_mean(close, 20) / ts_delay(close, 20) - 1   # process: [standardize(), csranknorm()]
tags: [mine_b3r21, reversal, ranknorm, equivalent]
params: {}
status: 无效（与 standardize 版逐位等价）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_ranknorm 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_ranknorm`（= `factor/reversal_20d_ranknorm.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——分布形态无关（等价确认） |
| 标签 | mine_b3r21, reversal, ranknorm, equivalent |
| 创建 | 2026-08-18（批次 3 轮次 21，种子 `reversal_20d_nowin`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子假设 (P3) 信号分布形态（standardize 后原始分布 vs 秩次均匀化）
可能影响分层统计。变异：追加 csranknorm()（横截面秩次归一化 → 分层档位等样本）。

**数学表达**：

```
signal = MA(close,20)/close[t-20] - 1 → standardize → csranknorm
```

## 3. 参数与实现

### 处理链

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2023-01-01 ~ 2026-07-31
process: [standardize(), csranknorm()]
target: forward_return_5d
adjustment: qfq
```

### 实现（YAML 全文）

```yaml
name: reversal_20d_ranknorm
category: custom
direction: -1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2023-01-01"
  end: "2026-07-31"
process:
  - standardize()
  - csranknorm()
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_delay
  signal = ts_mean(close, 20) / ts_delay(close, 20) - 1
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_ranknorm/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0409 |
| t 值 | 3.47 |
| IR | 0.260 |
| 近 26 周 mean / t | 0.0018 / 0.05 |

| 项 | 值 |
|----|----|
| spread | 0.00363 |
| D1 / D10 | 0.00267 / -0.00096 |

### 判定

- 与 nowin **逐位一致**（IC 0.0409、t 3.47、IR 0.260、spread 0.00363）——
  csranknorm 为单调变换（不改变秩次），RankIC/分层只依赖秩次 → 完全等价。
- 结论：**无效（等价确认）**——信号分布形态不影响评估；
  与 decile（分档）、nowin（winsorize）同为"幅度/分布变换等价"系列
  （第 3 次确认：只有改变秩次结构的手段才影响评估）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_ranknorm`（初始） | 批次 3 轮 21：P3 csranknorm | 0.0409 | 3.47 | 无效：分布形态无关 |

## 6. 风险与备注

- **系列结论**：decile/nowin/ranknorm 三连确认——评估只对秩次结构敏感；
  处理链（winsorize/standardize/csranknorm/fillna）不再重复探索。
- 种子 [`reversal_20d_nowin.md`](reversal_20d_nowin.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
