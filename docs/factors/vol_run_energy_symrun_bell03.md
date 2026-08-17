---
xname: vol_run_energy_symrun_bell03
formula: |
  signal = -ts_rank(rl, rl_win) * (e(1-e))**0.3 * gain
tags: [mine_b3r86, run_length, oi_energy, bell_flat]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 无效（钟形幂次谱 0.3-1.0 完全平坦）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_symrun_bell03 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun_bell03`（= `factor/vol_run_energy_symrun_bell03.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——钟形幂次谱平坦（等价确认） |
| 标签 | mine_b3r86, run_length, oi_energy, bell_flat |
| 创建 | 2026-08-18（批次 3 轮次 86，种子 `momentum_20d_turnrank`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：钟形幂次谱下探——0.3 幂（更宽钟形）。

**数学表达**：

```
signal = -ts_rank(rl, rl_win) × (e(1-e))^0.3 × gain
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
name: vol_run_energy_symrun_bell03
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
      _e = ts_rank(ts_delta(x, 1).abs(), n)
      return (_e * (1 - _e)) ** 0.3

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) != 0, ${rl_win})
  signal = -ts_rank(_rl, ${rl_win}) * _energy * ${gain}
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_symrun_bell03/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4690 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0273 |
| t 值 | 8.40 |
| IR | 0.650 |
| 近 26 周 mean / t | 0.0094 / 1.52 |

| 项 | 值 |
|----|----|
| spread | 0.00350 |
| D1 / D10 | 0.00388 / 0.00039 |

### 判定

- vs symrun（0.5 幂）：IC 0.0273（0.0276）、t 8.40（相同）、IR 0.650（相同）——
  **钟形幂次完全等价**（0.3/0.5/1.0 三档）。
- 结论：**无效（等价确认）**——钟形幂次谱 0.3-1.0 完全平坦；
  钟形的**存在**（轮 5）远重要于**形状**（0.3-1.0 任意）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_symrun_bell03`（初始） | 批次 3 轮 86：B3 钟形 0.3 幂 | 0.0273 | 8.40 | 无效：幂次谱平坦 |

## 6. 风险与备注

- **钟形结论定稿**：幂次 0.3-1.0 平坦——能量交互结构（存在钟形）
  是核心，形状细节无关。
- 基准 [`vol_run_energy_symrun.md`](vol_run_energy_symrun.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
