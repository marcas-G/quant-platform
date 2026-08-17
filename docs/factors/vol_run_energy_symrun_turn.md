---
xname: vol_run_energy_symrun_turn
formula: |
  signal = cs_rank(rank(rl)*bell) + cs_rank(turnover)
tags: [mine_b3r87, run_length, symrun_turn, mixed]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 观察中（IC 升、t 大降、近 26 周强）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_symrun_turn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun_turn`（= `factor/vol_run_energy_symrun_turn.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（IC 升、t 大降、近 26 周强） |
| 标签 | mine_b3r87, run_length, symrun_turn, mixed |
| 创建 | 2026-08-18（批次 3 轮次 87，种子 `vol_run_energy_symrun`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量能活跃 × 换手率秩次加法——同源（turnover）耦合测试。

**数学表达**：

```
signal = cs_rank(rank(rl) × bell) + cs_rank(turnover)
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
name: vol_run_energy_symrun_turn
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
  signal = cs_rank(ts_rank(_rl, ${rl_win}) * _energy) + cs_rank(turnover)
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_symrun_turn/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4690 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0368 |
| t 值 | 2.94 |
| IR | 0.228 |
| 近 26 周 mean / t | 0.0591 / 1.67（**近期强**） |

| 项 | 值 |
|----|----|
| spread | 0.00003（塌缩） |
| D1 / D10 | 0.00260 / 0.00257 |

### 判定

- vs symrun（父 1）：IC +33%（0.0276→0.0368）但 **t 8.40→2.94 大降**、
  IR 0.650→0.228——组合噪声大（同源 turn 与活跃度部分重叠）。
- **近 26 周 t=1.67（强）**——近期组合有效。
- 结论：**观察中（边际）**——symrun×turn 组合 IC/近期优、稳定性差；
  symrun 单独（t=8.40）仍是量能家族首选。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_symrun_turn`（初始） | 批次 3 轮 87：S3 秩次加法 | 0.0368 | 2.94 | 观察中：IC 升、t 降 |

## 6. 风险与备注

- **同源组合**：turnover 系信号（活跃度/turn）组合噪声大——
  量能家族保持单一表达（symrun 最优）。
- 基准 [`vol_run_energy_symrun.md`](vol_run_energy_symrun.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
