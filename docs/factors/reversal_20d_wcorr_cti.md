---
xname: reversal_20d_wcorr_cti
formula: |
  signal = 2*cs_rank(corr10) + cs_rank(turn) + cs_rank(intraday20)
tags: [mine_b3r100, reversal, wcorr_cti, marginal_final]
params: {}
status: 观察中（t/IR 升、IC 降——收官轮）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_wcorr_cti 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_wcorr_cti`（= `factor/reversal_20d_wcorr_cti.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（t/IR 升、IC 降——批次 3 收官轮） |
| 标签 | mine_b3r100, reversal, wcorr_cti, marginal_final |
| 创建 | 2026-08-18（批次 3 轮次 100，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：cti 三维（全库 IC 纪录）的 corr 双倍加权——批次收官稳定性测试。

**数学表达**：

```
signal = 2×cs_rank(corr10) + cs_rank(turn) + cs_rank(intraday20)
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
name: reversal_20d_wcorr_cti
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
  signal = 2 * cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_wcorr_cti/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0689 |
| t 值 | 7.22 |
| IR | 0.541 |
| 近 26 周 mean / t | 0.0367 / 1.43 |

| 项 | 值 |
|----|----|
| spread | 0.00452 |
| D1 / D10 | 0.00317 / -0.00135 |

### 判定

- vs cti（等权纪录）：IC 0.0689（0.0744，-7%）、**t 7.22（6.99，+3%）**、
  IR 0.541（0.524，+3%）——corr 加权延续模式（稳定性-水平权衡）。
- 结论：**观察中（边际）**——批次收官确认：**等权 cti 三维
  （0.0744/6.99/0.524）为全库综合最优平衡**。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_wcorr_cti`（初始） | 批次 3 轮 100：W3 corr 双倍 | 0.0689 | 7.22 | 观察中：收官确认等权最优 |

## 6. 风险与备注

- **批次 3 收官**：100 轮完成——最优集定稿：
  IC 纪录 cti 三维（0.0744）、稳定性纪录 wcorr_tsv10（7.65/0.574）、
  近期最强 corr_turn（近 26 周 t=1.85）。
- 基准 [`reversal_20d_corr_turn_intraday.md`](reversal_20d_corr_turn_intraday.md)
  （全库 IC 纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
