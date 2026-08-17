---
xname: momentum_20d_m120
formula: |
  signal = ts_mean(close, 120) / ts_delay(close, 120) - 1   # direction=1（动量方向对照）
tags: [mine_b3r17, momentum_120d, reversal_spectrum, boundary]
params: {}
status: 无效（120 日动量边际负——反转谱衰减到分界）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_m120 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_m120`（= `factor/momentum_20d_m120.yaml`） |
| 类别 | custom |
| 方向 | `1`（120 日动量方向对照） |
| 状态 | 无效——反转谱衰减到边际（尺度分界 ~120 日） |
| 标签 | mine_b3r17, momentum_120d, reversal_spectrum, boundary |
| 创建 | 2026-08-18（批次 3 轮次 17，种子 `momentum_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：尺度谱延伸——20/60 日均证伪动量方向（反转谱），120 日（半年）
是否进入动量区？尺度分界定位。

**数学表达**：

```
signal = MA(close, 120) / close[t-120] - 1
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
name: momentum_20d_m120
category: custom
direction: 1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2023-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_delay
  signal = ts_mean(close, 120) / ts_delay(close, 120) - 1
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_m120/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 157（120 日冷启动） |
| 平均股票数 | 4852 |
| 信号缺失率 | 0.1869 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0154 |
| t 值 | -1.25 |
| IR | -0.100 |
| 近 26 周 mean / t | -0.0297 / -0.86 |
| PearsonIC mean | -0.0092（t=-0.90） |

| 项 | 值 |
|----|----|
| spread | -0.00074 |
| D1 / D10 | 0.00188 / 0.00262 |

### 判定

- **反转尺度谱完整图景**（direction=1 动量方向 IC）：

  | 窗口 | IC | t |
  |------|----|----|
  | 20 日 | -0.0409 | -3.47 |
  | 60 日 | -0.0377 | -3.14 |
  | 120 日 | -0.0154 | -1.25（边际） |

- 反转强度随窗口**单调衰减**，120 日进入边际区（不显著）——A 股反转谱
  分界在 ~60-120 日之间；半年尺度动量仍未转正。
- 结论：**无效（尺度谱确认）**——动量方向 120 日边际负；
  反转主要信息在 20-60 日窗口（最佳区间）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `momentum_20d_m120`（初始） | 批次 3 轮 17：120 日动量方向 | -0.0154 | -1.25 | 无效：反转谱衰减到分界 |

## 6. 风险与备注

- **尺度谱结论**：反转信息集中在 20-60 日（t>3），120 日衰减到边际；
  未来窗口类变异限定在 20-60 区间，更长窗口无信息。
- 种子 [`momentum_20d.md`](momentum_20d.md)；60 日对照
  [`momentum_20d_m60.md`](momentum_20d_m60.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
