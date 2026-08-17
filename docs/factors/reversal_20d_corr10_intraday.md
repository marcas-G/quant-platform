---
xname: reversal_20d_corr10_intraday
formula: |
  signal = cs_rank(corr10) + cs_rank(intraday20)
tags: [mine_b3r92, reversal, corr10_intraday, peak_applied]
params: {}
status: 候选（corr10 谱峰应用）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr10_intraday 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr10_intraday`（= `factor/reversal_20d_corr10_intraday.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（corr10 谱峰应用微升） |
| 标签 | mine_b3r92, reversal, corr10_intraday, peak_applied |
| 创建 | 2026-08-18（批次 3 轮次 92，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：corr×intraday 二维的 corr 窗口换谱峰（10 日）。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(intraday20)
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
name: reversal_20d_corr10_intraday
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
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr10_intraday/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0607 |
| t 值 | 6.16 |
| IR | 0.461 |
| 近 26 周 mean / t | 0.0132 / 0.57 |

| 项 | 值 |
|----|----|
| spread | 0.00436 |
| D1 / D10 | 0.00314 / -0.00122 |

### 判定

- vs corr_intraday（corr20）：IC +4.5%（0.0581→0.0607）、t 6.16（6.08）、
  IR 0.461（0.456）——corr10 谱峰传导有效。
- 结论：**候选**——corr10×intraday 为二维组合更优版；
  cti 三维（0.0744）仍是全库 IC 纪录。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr10_intraday`（初始） | 批次 3 轮 92：C3 corr10 | 0.0607 | 6.16 | 候选：谱峰应用 |

## 6. 风险与备注

- **谱峰应用系列**：corr10/flow30 谱峰窗口在组合中传导有效——
  组合维度窗口统一取谱峰。
- 基准 [`reversal_20d_corr_intraday.md`](reversal_20d_corr_intraday.md)（corr20 版）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
