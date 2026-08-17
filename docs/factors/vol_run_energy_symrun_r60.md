---
xname: vol_run_energy_symrun_r60
formula: |
  signal = -ts_rank(rl, rl_win) * bell * gain   # rl_win=60
tags: [mine_b3r85, run_length, oi_energy, rl60, family_t_record]
params: {win: 200, gain: 2.0, rl_win: 60}
status: 观察中（t 新纪录、IC 略降）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_symrun_r60 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun_r60`（= `factor/vol_run_energy_symrun_r60.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（t=8.57 量能家族新纪录、IC 略降） |
| 标签 | mine_b3r85, run_length, oi_energy, rl60, family_t_record |
| 创建 | 2026-08-18（批次 3 轮次 85，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：游程窗口谱——rl_win=60（120 默认的季度尺度对照）。

**数学表达**：

```
signal = -ts_rank(rl, rl_win) × bell × gain   （rl_win=60）
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
name: vol_run_energy_symrun_r60
category: custom
direction: -1
params: {win: 200, gain: 2.0, rl_win: 60}
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

> 数据快照自 `results/vol_run_energy_symrun_r60/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 179 |
| 平均股票数 | 4717 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0267 |
| t 值 | 8.57（量能家族新纪录） |
| IR | 0.641 |
| 近 26 周 mean / t | 0.0086 / 1.37 |

| 项 | 值 |
|----|----|
| spread | 0.00341 |
| D1 / D10 | 0.00356 / 0.00016 |

### 判定

- vs symrun（r120）：IC 0.0267（0.0276，-3%）、**t 8.57（8.40）**、
  IR 0.641（0.650）——r60 微升 t、略降 IC。
- 结论：**观察中（边际）**——游程窗口谱基本平坦（60-120 相当）；
  r120 保持（IC 略优）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`vol_run_energy_symrun_r30` | 批次4轮9：R2 rl_win=30，见 [`vol_run_energy_symrun_r30.md`](vol_run_energy_symrun_r30.md) | 0.0259 | 8.51 | 观察中：谱平坦 |
| 2026-08-18 | `vol_run_energy_symrun_r60`（初始） | 批次 3 轮 85：R2 rl_win=60 | 0.0267 | 8.57 | 观察中：t 新纪录 |

## 6. 风险与备注

- **游程窗口谱**：60-120 平坦（游程频率结构稳健）——
  参数不敏感方向关闭。
- 基准 [`vol_run_energy_symrun.md`](vol_run_energy_symrun.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
