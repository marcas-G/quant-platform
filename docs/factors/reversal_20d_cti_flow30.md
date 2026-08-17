---
xname: reversal_20d_cti_flow30
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(intraday20) + cs_rank(flow30)
tags: [mine_b3r91, reversal, cti_flow30, marginal]
params: {}
status: 无效（flow30 第四维边际）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_cti_flow30 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_cti_flow30`（= `factor/reversal_20d_cti_flow30.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——flow30 第四维边际 |
| 标签 | mine_b3r91, reversal, cti_flow30, marginal |
| 创建 | 2026-08-18（批次 3 轮次 91，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：cti 三维（IC 纪录）+ flow30（谱峰）四维。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(intraday20) + cs_rank(flow30)
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
name: reversal_20d_cti_flow30
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(ts_sum(amount * sign(returns(close)), 30))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_cti_flow30/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0736 |
| t 值 | 6.85 |
| IR | 0.516 |
| 近 26 周 mean / t | 0.0396 / 1.26 |

| 项 | 值 |
|----|----|
| spread | 0.00512 |
| D1 / D10 | 0.00302 / -0.00210 |

### 判定

- vs cti 三维（IC 纪录）：IC 0.0736（0.0744，-1%）、t 6.85（6.99）、
  IR 0.516（0.524）——flow30 第四维略稀释。
- vs four_dim10：IC +2%（flow30 优于 vol 构成）。
- 结论：**无效（边际）**——cti 三维保持 IC 纪录；
  flow30 四维为含 flow 组合最优（0.0736）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_cti_flow30`（初始） | 批次 3 轮 91：F3 四维加法 | 0.0736 | 6.85 | 无效：flow30 边际 |

## 6. 风险与备注

- **组合定稿**：cti 三维（0.0744）IC 纪录；flow30 四维（0.0736）
  为含 flow 最优——维度扩展边际递减。
- 基准 [`reversal_20d_corr_turn_intraday.md`](reversal_20d_corr_turn_intraday.md)
  （全库 IC 纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
