---
xname: vol_run_energy_symrun_w100
formula: |
  signal = -ts_rank(rl, rl_win) * bell * gain   # win=100
tags: [mine_b3r69, run_length, oi_energy, win100, coverage_gain]
params: {win: 100, gain: 2.0, rl_win: 120}
status: 无效（IC 降；覆盖扩大）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_symrun_w100 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun_w100`（= `factor/vol_run_energy_symrun_w100.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——turnover 口径 win200 最优 |
| 标签 | mine_b3r69, run_length, oi_energy, win100, coverage_gain |
| 创建 | 2026-08-18（批次 3 轮次 69，种子 `vol_run_energy_rl120_turn`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：turnover 口径能量窗口谱——win=100（volume 口径变体更优的对照）。

**数学表达**：

```
signal = -ts_rank(rl, rl_win) × bell × gain   （win=100）
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
name: vol_run_energy_symrun_w100
category: custom
direction: -1
params: {win: 100, gain: 2.0, rl_win: 120}
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

> 数据快照自 `results/vol_run_energy_symrun_w100/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 187（+13% vs symrun） |
| 平均股票数 | 4734 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0217 |
| t 值 | 7.49 |
| IR | 0.548 |
| 近 26 周 mean / t | 0.0088 / 1.26 |

| 项 | 值 |
|----|----|
| spread | 0.00264 |
| D1 / D10 | 0.00298 / 0.00034 |

### 判定

- vs symrun（w200）：IC 0.0217（0.0276，-21%）、t 7.49（8.40）、
  IR 0.548（0.650）——全面略降；**有效周 187（166，+13% 覆盖扩大）**。
- 结论：**无效**——turnover 口径 win200 最优（与 volume 口径 win100
  方向相反：口径决定窗口谱）；覆盖-质量权衡偏向质量。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_symrun_w100`（初始） | 批次 3 轮 69：W2 win100 | 0.0217 | 7.49 | 无效：w200 最优 |

## 6. 风险与备注

- **窗口谱结论**：能量窗口谱依赖口径（volume→100、turnover→200）；
  量能家族保持 win200/turnover 最优设置。
- 基准 [`vol_run_energy_symrun.md`](vol_run_energy_symrun.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
