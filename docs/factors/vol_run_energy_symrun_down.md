---
xname: vol_run_energy_symrun_down
formula: |
  signal = -ts_rank(rl_down, rl_win) * bell * gain   # rl_down: sign(d_turn)==-1
tags: [mine_b3r19, run_length, oi_energy, down_only, up_driven]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 无效（上涨活跃是游程主源）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_symrun_down 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun_down`（= `factor/vol_run_energy_symrun_down.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——只算下跌活跃大幅劣化 |
| 标签 | mine_b3r19, run_length, oi_energy, down_only, up_driven |
| 创建 | 2026-08-18（批次 3 轮次 19，种子 `vol_run_energy_symrun`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `vol_run_energy_symrun` 的假设 (S3) 对称游程内恐慌（下跌活跃）
与追涨（上涨活跃）等权。检验子方向：只算下跌活跃（恐慌分歧驱动反转）。

**数学表达**：

```
signal = -ts_rank(ts_count(sign(Δturnover)==-1, rl_win), rl_win) × bell × gain
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
name: vol_run_energy_symrun_down
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
      return sqrt(_e * (1 - _e))

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) == -1, ${rl_win})
  signal = -ts_rank(_rl, ${rl_win}) * _energy * ${gain}
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_symrun_down/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4690 |
| 信号缺失率 | 0.3551 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0126 |
| t 值 | 3.95 |
| IR | 0.306 |
| 近 26 周 mean / t | -0.0061 / -0.83 |
| PearsonIC mean | -0.0058（t=-2.06） |

| 项 | 值 |
|----|----|
| spread | 0.00126 |
| D1 / D10 | 0.00323 / 0.00197 |

### 判定

- vs symrun（对称）：IC 0.0126（0.0276，**-54%**）、t 3.95（8.40）、
  IR 0.306（0.650）、spread 0.00126（0.00348，**-64%**）。
- 结论：**无效（S3' 否定）**——**上涨活跃（追涨分歧）是游程信号主源**；
  删除上涨部分丢失大部分信息，恐慌（下跌活跃）非反转驱动主源。
  对称游程 = 以上涨为主、下跌补充的联合信号。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_symrun_down`（初始） | 批次 3 轮 19：S3 只算下跌活跃 | 0.0126 | 3.95 | 无效：上涨活跃是主源 |

## 6. 风险与备注

- **方向性结论**：游程信号不对称——上涨活跃权重 > 下跌活跃；
  对称（!=0）是最优折中。未来不做游程方向性删减。
- 种子 [`vol_run_energy_symrun.md`](vol_run_energy_symrun.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
