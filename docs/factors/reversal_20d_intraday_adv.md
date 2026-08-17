---
xname: reversal_20d_intraday_adv
formula: |
  signal = ts_sum(close/open - 1, 20) * cs_rank(adv20(volume))
tags: [mine_b3r88, reversal, intraday_adv, vol_equivalent]
params: {}
status: 无效（adv20 与量能确认条件化等价）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_intraday_adv 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_intraday_adv`（= `factor/reversal_20d_intraday_adv.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——adv20 与量能确认等价（薄封装覆盖完成） |
| 标签 | mine_b3r88, reversal, intraday_adv, vol_equivalent |
| 创建 | 2026-08-18（批次 3 轮次 88，种子 `vol_run_energy_rl120_turn`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：adv20（20 日均量水平）条件化——薄封装最后覆盖。

**数学表达**：

```
signal = Σ(close/open - 1, 20) × cs_rank(adv20(volume))
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
name: reversal_20d_intraday_adv
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
  from polars_ta.prefix.wq import ts_sum, cs_rank
  signal = ts_sum(close/open - 1, 20) * cs_rank(adv20(volume))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_intraday_adv/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0547 |
| t 值 | 5.33 |
| IR | 0.400 |
| 近 26 周 mean / t | 0.0091 / 0.35 |

| 项 | 值 |
|----|----|
| spread | 0.00453 |
| D1 / D10 | 0.00230 / -0.00223 |

### 判定

- vs intraday_vol：IC 0.0547（相同）、t 5.33（相同）、IR 0.400（0.399）——
  **adv20 与量能确认条件化几乎等价**（20 日均量水平与量能分位高度相关）。
- vs intraday（无条件化）：IC -7%（条件化稀释）。
- 结论：**无效（等价确认）**——量条件化口径（水平/事件）等价；
  **平台薄封装全部覆盖完成**（returns/vwap/adv20/group_rank/group_mean）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_intraday_adv`（初始） | 批次 3 轮 88：A2 adv20 条件化 | 0.0547 | 5.33 | 无效：与量能确认等价 |

## 6. 风险与备注

- **薄封装覆盖完成**：returns/vwap/adv20/group_rank/group_mean 全部测试过。
- 基准 [`reversal_20d_intraday_vol.md`](reversal_20d_intraday_vol.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
