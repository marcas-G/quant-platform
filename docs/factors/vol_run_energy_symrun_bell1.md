---
xname: vol_run_energy_symrun_bell1
formula: |
  signal = -ts_rank(rl, rl_win) * e(1-e) * gain   # 钟形指数 1.0
tags: [mine_b3r13, run_length, oi_energy, bell_sharpness, equivalent]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 无效（与 sqrt 钟形等价）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_symrun_bell1 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun_bell1`（= `factor/vol_run_energy_symrun_bell1.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——钟形锐度与 sqrt 等价 |
| 标签 | mine_b3r13, run_length, oi_energy, bell_sharpness, equivalent |
| 创建 | 2026-08-18（批次 3 轮次 13，种子 `vol_run_energy_symrun`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `vol_run_energy_symrun` 的假设 (S3) sqrt 钟形（指数 0.5）是
最优锐度。检验更尖钟形（指数 1.0：中能区收窄、压制更强）。

**数学表达**：

```
signal = -ts_rank(rl, rl_win) × e(1-e) × gain   （钟形指数 0.5 → 1.0）
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
name: vol_run_energy_symrun_bell1
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
      return _e * (1 - _e)

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) != 0, ${rl_win})
  signal = -ts_rank(_rl, ${rl_win}) * _energy * ${gain}
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_symrun_bell1/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4690 |
| 信号缺失率 | 0.3551 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0278 |
| t 值 | 8.37 |
| IR | 0.648 |
| 近 26 周 mean / t | 0.0090 / 1.45 |
| PearsonIC mean | -0.0171（t=-5.32） |

| 项 | 值 |
|----|----|
| spread | 0.00363 |
| D1 / D10 | 0.00395 / 0.00031 |

### 判定

- vs symrun（sqrt 钟形）：IC 0.0278（0.0276）、t 8.37（8.40）、IR 0.648（0.650）、
  spread 0.00363（0.00348，+4.3% 噪声级）、近 26 周持平。
- 结论：**无效（等价确认）**——钟形锐度对秩次影响微小，sqrt 已是平衡点；
  钟形的**存在**（轮 5）远比**形状**重要。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_symrun_bell1`（初始） | 批次 3 轮 13：S3 钟形锐度 | 0.0278 | 8.37 | 无效：与 sqrt 等价 |

## 6. 风险与备注

- **结论**：钟形形状（0.5 vs 1.0 指数）不敏感——能量交互的结构重要性
  高于参数细节；未来不在此方向重复。
- 种子 [`vol_run_energy_symrun.md`](vol_run_energy_symrun.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
