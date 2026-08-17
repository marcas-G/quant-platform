---
xname: vol_run_energy_symrun_r30
formula: |
  signal = -ts_rank(rl, rl_win) * bell * gain   # rl_win=30
tags: [mine_b4r9, run_length, oi_energy, rl30, spectrum_flat]
params: {win: 200, gain: 2.0, rl_win: 30}
status: 观察中（游程窗口谱平坦确认）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_symrun_r30 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun_r30`（= `factor/vol_run_energy_symrun_r30.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（游程窗口谱 30-120 平坦） |
| 标签 | mine_b4r9, run_length, oi_energy, rl30, spectrum_flat |
| 创建 | 2026-08-18（批次 4 轮次 9，种子 `vol_run_energy_symrun_r60`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：游程窗口谱下探——30 日（月频）边界。

**数学表达**：

```
signal = -ts_rank(rl, rl_win) × bell × gain   （rl_win=30）
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
name: vol_run_energy_symrun_r30
category: custom
direction: -1
params: {win: 200, gain: 2.0, rl_win: 30}
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
      _e = ts_rank(ts_delta(x, 1).abs(), n)
      return sqrt(_e * (1 - _e))

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) != 0, ${rl_win})
  signal = -ts_rank(_rl, ${rl_win}) * _energy * ${gain}
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_symrun_r30/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 185（覆盖随窗口缩短递增） |
| 平均股票数 | 4730 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0259 |
| t 值 | 8.51 |
| IR | 0.625 |
| 近 26 周 mean / t | 0.0084 / 1.33 |

| 项 | 值 |
|----|----|
| spread | 0.00341 |

### 判定

- 游程窗口谱（rl30/60/120）：IC 0.0259/0.0267/0.0276（单调微降）、
  t 8.51/8.57/8.40（持平）、覆盖 185/179/167（单调增）——**谱平坦**，
  覆盖-质量权衡（短窗覆盖大、长窗 IC 微优）。
- 结论：**观察中（边际）**——谱下探确认平坦；r120 保持 IC 最优。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_symrun_r30`（初始） | 批次 4 轮 9：R2 rl_win=30 | 0.0259 | 8.51 | 观察中：谱平坦 |

## 6. 风险与备注

- **窗口谱定稿**：游程窗口 30-120 平坦——量能家族窗口参数不敏感。
- 种子 [`vol_run_energy_symrun_r60.md`](vol_run_energy_symrun_r60.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
