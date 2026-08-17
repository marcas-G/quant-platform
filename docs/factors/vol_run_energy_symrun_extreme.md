---
xname: vol_run_energy_symrun_extreme
formula: |
  signal = -ts_rank(rl, rl_win) * bell * gain * mask(cs_rank(turnover) > 0.8)
tags: [mine_b4r7, run_length, symrun, extreme_incompatible, inverted]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 无效（方向反转——量能活跃与换手极端不兼容）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_symrun_extreme 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun_extreme`（= `factor/vol_run_energy_symrun_extreme.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——方向反转（极端掩码与量能活跃不兼容） |
| 标签 | mine_b4r7, run_length, symrun, extreme_incompatible, inverted |
| 创建 | 2026-08-18（批次 4 轮次 7，种子 `vol_run_energy_symrun_turn`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：极端换手聚焦（跨维度增强器）应用到量能家族（turnover 系）。

**数学表达**：

```
signal = -ts_rank(rl, rl_win) × bell × gain × 1{cs_rank(turnover) > 0.8}
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
name: vol_run_energy_symrun_extreme
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
  from polars_ta.prefix.wq import ts_rank, ts_delta, ts_count, cs_rank

  def oi_energy(x, n):
      _e = ts_rank(ts_delta(x, 1).abs(), n)
      return sqrt(_e * (1 - _e))

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) != 0, ${rl_win})
  _w = sign(sign(cs_rank(turnover) - 0.8) + 1) / 2
  signal = -ts_rank(_rl, ${rl_win}) * _energy * ${gain} * _w
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_symrun_extreme/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4690 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0685 |
| t 值 | -7.13 |
| IR | -0.552 |
| 近 26 周 mean / t | -0.0540 / -1.76 |

| 项 | 值 |
|----|----|
| spread | -0.00185（负值） |

### 判定

- vs symrun（种子）：**IC 0.0276 → -0.0685 完全反转**（t=-7.13）。
- 机制：symrun 活跃度基于 turnover——与换手率同源耦合；极端换手掩码
  只保留 top 20% 换手股后，量能活跃语义被换手水平主导、方向反转。
- 结论：**无效（方向反转）**——极端掩码适用于与换手**正交**的信号
  （反转/日内/彩票），不适用于同源（turnover 系）信号。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_symrun_extreme`（初始） | 批次 4 轮 7：S2 极端换手聚焦 | -0.0685 | -7.13 | 无效：方向反转 |

## 6. 风险与备注

- **极端聚焦适用边界**：正交信号（价格/日内/彩票）适用、同源信号
  （turnover 系）不适用——掩码增强器的适用范围清晰化。
- 种子 [`vol_run_energy_symrun_turn.md`](vol_run_energy_symrun_turn.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
