---
xname: vol_run_energy_cumret
formula: |
  signal = -ts_rank(rl, rl_win) * bell * gain * abs(ts_sum(returns(close), 20))
tags: [mine_b3r23, cross_family, combo_failed, coupled]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 无效（跨家族乘法组合方向冲突）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_cumret 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_cumret`（= `factor/vol_run_energy_cumret.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——跨家族乘法组合不成立 |
| 标签 | mine_b3r23, cross_family, combo_failed, coupled |
| 创建 | 2026-08-18（批次 3 轮次 23，种子 `vol_run_energy_rl120_turn`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量能家族（活跃信号）与价格家族（cumret 反转）正交组合——
"量能分歧 × 价格超调"双确认。

**实现过程**：
1. 首次：`× ts_sum(returns(close), 20)`（带符号）→ IC=-0.038（t=-3.58）
   方向完全反转（subagent 预警的符号冲突证实：跌深股×活跃变正信号，
   与反转方向冲突）。
2. 修正：`× abs(...)`（量能 × |超调幅度|）→ IC=-0.011（t=-1.48）仍负。

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
name: vol_run_energy_cumret
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
  from polars_ta.prefix.wq import ts_rank, ts_delta, ts_count, ts_sum

  def oi_energy(x, n):
      _e = ts_rank(ts_delta(x, 1).abs(), n)
      return sqrt(_e * (1 - _e))

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) == 1, ${rl_win})
  signal = -ts_rank(_rl, ${rl_win}) * _energy * ${gain} * abs(ts_sum(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_cumret/summary.json`（abs 修正版，2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4690 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0111 |
| t 值 | -1.48 |
| IR | -0.114 |
| 近 26 周 mean / t | 0.0024 / 0.14 |

| 项 | 值 |
|----|----|
| spread | 0.00105 |
| D1 / D10 | 0.00266 / 0.00161 |

### 判定

- 带符号版 IC=-0.038（方向反转）；abs 修正版 IC=-0.011（仍负、不显著）。
- 结论：**无效（H2' 否定）**——**量能与价格信号高度耦合**（同属"活跃股"
  维度，信息不独立）；乘法组合破坏各自方向语义（活跃+大跌股被推向做空端）。
  跨家族组合需用正交化手段（如秩差）而非乘法。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_cumret`（初始） | 批次 3 轮 23：H2 跨家族乘法组合 | -0.0111 | -1.48 | 无效：组合方向冲突（两信号耦合） |

## 6. 风险与备注

- **组合方法论**：乘法组合仅适用于**正交信号**；量能与价格同源耦合，
  未来组合需先验证正交性（相关性分析）或使用秩差/去相关。
- 种子 [`vol_run_energy_rl120_turn.md`](vol_run_energy_rl120_turn.md)；
  基准 [`reversal_20d_cumret.md`](reversal_20d_cumret.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
