---
xname: vol_run_energy_symrun_lin
formula: |
  signal = -ts_rank(rl, rl_win) * e * gain   # e = rank(|d_turn|, win)，无钟形
tags: [mine_b3r5, run_length, oi_energy, bell_required, inverted]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 无效（钟形为语义核心，去钟形信号反转）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_symrun_lin 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun_lin`（= `factor/vol_run_energy_symrun_lin.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——去钟形信号反转（钟形必需） |
| 标签 | mine_b3r5, run_length, oi_energy, bell_required, inverted |
| 创建 | 2026-08-18（批次 3 轮次 5，种子 `vol_run_energy`，base `vol_run_energy_symrun`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：base `vol_run_energy_symrun` 的钟形 `sqrt(e(1-e))` 隐含"中能量区最优"。
检验能量是否单调有效：去钟形 `return _e`。

**数学表达**：

```
signal = -ts_rank(rl, rl_win) × e × gain   （无钟形）
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
name: vol_run_energy_symrun_lin
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
      return _e

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) != 0, ${rl_win})
  signal = -ts_rank(_rl, ${rl_win}) * _energy * ${gain}
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_symrun_lin/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4690 |
| 信号缺失率 | 0.3551 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0441 |
| t 值 | -8.16 |
| IR | -0.631 |
| 近 26 周 mean / t | -0.0338 / -2.53 |
| PearsonIC mean | 0.0157（t=3.23） |

| 项 | 值 |
|----|----|
| spread | -0.00399（负值 = 档位反向） |
| D1 / D10 | -0.00066 / 0.00333 |

### 判定

- vs base symrun：IC **-0.0441（+0.0276，完全反转）**、t=-8.16、IR=-0.63。
- 结论：**无效（钟形为语义核心）**——能量 e 与游程 rl 正相关（放量活跃股
  游程长），去钟形后"高能×高游程"组主导且未来收益为正（延续），信号反号。
  钟形压制高低能两端恰是反转信号的来源；去钟形不只是幅度变换，
  **改变了秩次结构**（修正批次 2 轮 5"幅度函数无信息"的适用范围）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_symrun_lin`（初始） | 批次 3 轮 5：H3 去钟形线性能量 | -0.0441 | -8.16 | 无效：信号反转，钟形必需 |

## 6. 风险与备注

- **重要发现**：钟形调制（中能量区）是能量-游程交互的秩次核心——
  未来迭代可在钟形**形状**上做文章（如 e(1-e) 幂次），但不可去掉。
- 种子 [`vol_run_energy.md`](vol_run_energy.md)；base
  [`vol_run_energy_symrun.md`](vol_run_energy_symrun.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
