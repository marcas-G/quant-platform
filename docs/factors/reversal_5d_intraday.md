---
xname: reversal_5d_intraday
formula: |
  signal = ts_sum(close/open - 1, 5)
tags: [mine_b3r48, reversal, intraday5, peak20_confirmed]
params: {}
status: 无效（日内谱峰 20 日确认）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_5d_intraday 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_5d_intraday`（= `factor/reversal_5d_intraday.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——日内谱峰 20 日（5/10/20 谱系确认） |
| 标签 | mine_b3r48, reversal, intraday5, peak20_confirmed |
| 创建 | 2026-08-18（批次 3 轮次 48，种子 `reversal_20d_near5`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：日内谱系下界——5 日（超短窗口）。

**数学表达**：

```
signal = Σ (close/open - 1) over 5d
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
name: reversal_5d_intraday
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
  from polars_ta.prefix.wq import ts_sum
  signal = ts_sum(close/open - 1, 5)
```

## 4. 验证结果

> 数据快照自 `results/reversal_5d_intraday/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 181 |
| 平均股票数 | 4886 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0402 |
| t 值 | 3.62 |
| IR | 0.269 |
| 近 26 周 mean / t | -0.0067 / -0.24 |

| 项 | 值 |
|----|----|
| spread | 0.00375 |
| D1 / D10 | 0.00180 / -0.00194 |

### 判定

- vs intraday20（纪录）：IC 0.0402（0.0591，-32%）、t 3.62（5.22）、
  IR 0.269（0.391）——显著劣化。
- **日内谱系完整**（5/10/20 三点）：

  | 窗口 | IC | t |
  |------|----|----|
  | 5 日 | 0.0402 | 3.62 |
  | 10 日 | 0.0503 | 4.49 |
  | 20 日 | 0.0591 | 5.22 |

- 结论：**无效（谱下界确认）**——日内信号需 20 日累计平滑日间噪声。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_5d_intraday`（初始） | 批次 3 轮 48：I2 5 日日内 | 0.0402 | 3.62 | 无效：谱峰 20 日 |

## 6. 风险与备注

- **谱系完整**：日内/累计/净流入谱峰均 20 日（corr 例外 10 日）——
  窗口维度收束。
- 基准 [`reversal_20d_intraday.md`](reversal_20d_intraday.md)（纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
