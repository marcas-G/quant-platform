---
xname: vol_run_energy_rl120_turn_up
formula: |
  signal = -ts_rank(rl, rl_win) * sqrt(e(1-e)) * gain   # e = rank(max(d_turn,0), win)
tags: [mine_b3r3, run_length, oi_energy, up_only, no_gain]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 无效（相对种子劣化）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_rl120_turn_up 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_rl120_turn_up`（= `factor/vol_run_energy_rl120_turn_up.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——只算放量能量劣于对称能量 |
| 标签 | mine_b3r3, run_length, oi_energy, up_only, no_gain |
| 创建 | 2026-08-18（批次 3 轮次 3，种子 `vol_run_energy_rl120_turn`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子隐含假设 (H4) 能量 \|Δ\| 对称（放缩量信息等价）。检验"缩量无能量
信息"：能量只算放量 `max(Δ, 0)`（缩量日能量=0）。

**数学表达**：

```
e = ts_rank(max(Δturnover, 0), win)   # max(d,0) = (d+|d|)/2
signal = -ts_rank(rl, rl_win) × sqrt(e(1-e)) × gain
```

## 3. 参数与实现

### 处理链

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2022-01-01 ~ 2026-07-31
process: winsorize(quantile=0.99) → standardize()
target: forward_return_5d
adjustment: qfq
```

### 实现（YAML 全文）

```yaml
name: vol_run_energy_rl120_turn_up
category: custom
direction: -1
params: {win: 200, gain: 2.0, rl_win: 120}
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2022-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_rank, ts_delta, ts_count

  def oi_energy(x, n):
      _d = ts_delta(x, 1)
      _e = ts_rank((_d + abs(_d)) / 2, n)  # max(d,0)：只算放量能量
      return sqrt(_e * (1 - _e))

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) == 1, ${rl_win})
  signal = -ts_rank(_rl, ${rl_win}) * _energy * ${gain}
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_rl120_turn_up/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4690 |
| 信号缺失率 | 0.3551 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0139 |
| t 值 | 4.49 |
| IR | 0.347 |
| 近 26 周 mean / t | 0.0176 / 3.17 |
| PearsonIC mean | -0.0077（t=-3.04） |

| 项 | 值 |
|----|----|
| spread | 0.00208 |
| D1 / D10 | 0.00386 / 0.00178 |

### 判定

- vs 种子（对称能量）：IC 0.0139（0.0152，-9%）、t 4.49（5.26）、IR 0.347（0.407）、
  spread 0.00208（0.00252，-17%）。近 26 周持平（t 3.17 vs 3.24）。
- 结论：**无效**——缩量信息有少量价值；\|Δ\| 对称能量保持。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_rl120_turn_up`（初始） | 批次 3 轮 3：H4 能量只算放量 | 0.0139 | 4.49 | 无效：对称能量更优 |

## 6. 风险与备注

- **证伪价值**：能量对称性方向排除（放缩量均含信息）；与批次 2 轮 7
  （游程对称化有效）形成对照：游程需对称、能量保持对称已是局部最优。
- 平台缺口记录：白名单无 if_else、`.abs()` 方法链基表达式不可为裸 Name——
  本轮踩到并修订 interface.md。
- 种子 [`vol_run_energy_rl120_turn.md`](vol_run_energy_rl120_turn.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
