---
xname: vol_run_energy_symrun_corr
formula: |
  signal = cs_rank(rank(rl)*bell) + cs_rank(corr(returns, d_vol, 20))
tags: [mine_b3r39, cross_family, volume_coupled, combo_failed]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 无效（跨家族组合失败——量维度耦合）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# vol_run_energy_symrun_corr 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun_corr`（= `factor/vol_run_energy_symrun_corr.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——量维度耦合，跨家族组合失败 |
| 标签 | mine_b3r39, cross_family, volume_coupled, combo_failed |
| 创建 | 2026-08-18（批次 3 轮次 39，种子 `vol_run_energy_symrun`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量能家族（活跃度）× 量价相关（结构）秩次加法——跨家族正交测试
（轮 23 乘法失败后改用秩次加法；方向统一：活跃高→做空、corr 高→做空）。

**数学表达**：

```
signal = cs_rank(rank(rl) × bell) + cs_rank(corr(returns, Δvol, 20))
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
name: vol_run_energy_symrun_corr
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
  from polars_ta.prefix.wq import ts_rank, ts_delta, ts_count, ts_corr, cs_rank

  def oi_energy(x, n):
      _e = ts_rank(ts_delta(x, 1).abs(), n)
      return sqrt(_e * (1 - _e))

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) != 0, ${rl_win})
  signal = cs_rank(ts_rank(_rl, ${rl_win}) * _energy) + cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 20))
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_symrun_corr/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4690 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0147 |
| t 值 | 2.79 |
| IR | 0.216 |
| 近 26 周 mean / t | 0.0064 / 0.51 |

| 项 | 值 |
|----|----|
| spread | -0.00041（负值） |
| D1 / D10 | 0.00222 / 0.00263 |

### 判定

- vs symrun（父 1）：IC 0.0147（0.0276，-47%）、t 2.79（8.40）。
- vs corr（父 2）：IC 0.0147（0.0425，-65%）。
- 结论：**无效（S3' 否定）**——量能活跃与量价相关同属"量"维度
  （高度耦合），秩次加法互相稀释；跨家族组合（乘法轮 23/加法本轮）
  **均不成立**——量价反转家族与量能家族不可组合。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `vol_run_energy_symrun_corr`（初始） | 批次 3 轮 39：S3 跨家族秩次加法 | 0.0147 | 2.79 | 无效：量维度耦合 |

## 6. 风险与备注

- **组合方法论最终结论**：正交组合仅适用于**不同信息源**（价格幅度/价格结构/
  投机强度）；量维度内部（量能/量价相关）高度耦合不可组合。
- 种子 [`vol_run_energy_symrun.md`](vol_run_energy_symrun.md)；
  基准 [`reversal_20d_pricevolcorr.md`](reversal_20d_pricevolcorr.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
