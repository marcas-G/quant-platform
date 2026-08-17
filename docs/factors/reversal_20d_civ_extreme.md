---
xname: reversal_20d_civ_extreme
formula: |
  signal = cs_rank(corr20) + cs_rank(intraday20) + cs_rank(vol20) + cs_rank(mom20 * mask_turn)
tags: [mine_b4r3, reversal, civ_extreme, redundant_in_combo]
params: {}
status: 无效（组合内冗余）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_civ_extreme 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_civ_extreme`（= `factor/reversal_20d_civ_extreme.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——极端信号在组合内冗余 |
| 标签 | mine_b4r3, reversal, civ_extreme, redundant_in_combo |
| 创建 | 2026-08-18（批次 4 轮次 3，种子 `reversal_20d_corr_intraday_turn_vol`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：轮 1 极端换手信号单独强（t 翻倍）——替换四维组合中 turn 维度。

**数学表达**：

```
signal = cs_rank(corr20) + cs_rank(intraday20) + cs_rank(vol20) + cs_rank(mom20 × mask_turn)
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
name: reversal_20d_civ_extreme
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, ts_rank, ts_mean, ts_delay, cs_rank
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  _w = sign(sign(cs_rank(turnover) - 0.8) + 1) / 2
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 20)) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(ts_rank(volume, 20)) + cs_rank(_mom * _w)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_civ_extreme/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0668 |
| t 值 | 6.66 |
| IR | 0.499 |
| 近 26 周 mean / t | 0.0143 / 0.57 |

| 项 | 值 |
|----|----|
| spread | 0.00628 |
| D1 / D10 | 0.00378 / -0.00250 |

### 判定

- vs 种子（四维）：IC 0.0668（0.0719，-7%）、t 6.66（7.35）、IR 0.499（0.551）、
  spread 0.00628（种子更高档位区分）。
- **组合内冗余确认**：极端信号含反转核心（mom），与 corr/intraday 的反转成分
  重叠；纯换手率维度（cs_rank(turnover)）与反转正交——**正交性价值 > 信息密度**。
- 结论：**无效**——极端换手信号单独强（轮 1）、组合内冗余（本轮）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_civ_extreme`（初始） | 批次 4 轮 3：F3 极端信号替换 turn | 0.0668 | 6.66 | 无效：组合内冗余 |

## 6. 风险与备注

- **组合维度原则**：组合维度需**正交**（纯 turn 与反转正交）；
  含核心的信号（extreme）单独用、不进组合。
- 审核修正：种子 corr 窗口为 20（误记 corr10 已纠正）——归因清晰。
- 种子 [`reversal_20d_corr_intraday_turn_vol.md`](reversal_20d_corr_intraday_turn_vol.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
