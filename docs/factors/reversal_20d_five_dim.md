---
xname: reversal_20d_five_dim
formula: |
  signal = cs_rank(corr) + cs_rank(intraday) + cs_rank(turn) + cs_rank(vol) + cs_rank(netflow)
tags: [mine_b3r41, reversal, five_dim, saturated]
params: {}
status: 无效（维度饱和——四维是最优点）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_five_dim 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_five_dim`（= `factor/reversal_20d_five_dim.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——维度饱和（四维最优） |
| 标签 | mine_b3r41, reversal, five_dim, saturated |
| 创建 | 2026-08-18（批次 3 轮次 41，种子 `vol_run_energy_rl120_turn`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：四维组合（全库最强）加第五维资金流——netflow 独立（轮 40）但
与 amount/volume 同源可能重叠。

**数学表达**：

```
signal = cs_rank(corr) + cs_rank(intraday) + cs_rank(turn) + cs_rank(ts_rank(vol,20)) + cs_rank(netflow)
```

## 3. 参数与实现

### 处理链

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2023-01-01 ~ 2026-07-31
process: winsorize(quantile=0.99) → standardize()
target: forward_return_5d
adjustment: qfq
```

### 实现（YAML 全文）

```yaml
name: reversal_20d_five_dim
category: custom
direction: -1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2023-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, ts_rank, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 20)) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(turnover) + cs_rank(ts_rank(volume, 20)) + cs_rank(ts_sum(amount * sign(returns(close)), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_five_dim/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4880 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0713 |
| t 值 | 7.11 |
| IR | 0.533 |
| 近 26 周 mean / t | 0.0318 / 1.07 |

| 项 | 值 |
|----|----|
| spread | 0.00520 |
| D1 / D10 | 0.00274 / -0.00246 |

### 判定

- vs 四维（全库最强）：IC 0.0713（0.0719，-1%）、t 7.11（7.35，-3%）、
  IR 0.533（0.551，-3%）——**全面略降**。
- 结论：**无效（维度饱和确认）**——netflow 与 turn/vol 同源（amount 与
  volume/turnover 高度相关），第五维稀释；**四维秩次加法是饱和点**。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_five_dim`（初始） | 批次 3 轮 41：E3 第五维 | 0.0713 | 7.11 | 无效：维度饱和 |

## 6. 风险与备注

- **饱和结论**：秩次加法维度上限 = 4（corr/intraday/turn/vol）；
  后续不做维度扩展，转向核心表达或样本稳健性。
- 基准 [`reversal_20d_corr_intraday_turn_vol.md`](reversal_20d_corr_intraday_turn_vol.md)
  （全库最强：0.072/7.35/0.551）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
