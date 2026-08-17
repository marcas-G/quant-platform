---
xname: reversal_20d_skew10
formula: |
  signal = ts_skewness(returns(close), 10)
tags: [mine_b3r53, reversal, skew10, peak20]
params: {}
status: 无效（偏度谱峰 20 日）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_skew10 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_skew10`（= `factor/reversal_20d_skew10.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——偏度谱峰 20 日 |
| 标签 | mine_b3r53, reversal, skew10, peak20 |
| 创建 | 2026-08-18（批次 3 轮次 53，种子 `reversal_20d_nowin`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：偏度窗口谱——10 日（矩结构短窗灵敏性）。

**数学表达**：

```
signal = skewness(returns(close), 10d)
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
name: reversal_20d_skew10
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
  from polars_ta.prefix.wq import ts_skewness
  signal = ts_skewness(returns(close), 10)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_skew10/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 180 |
| 平均股票数 | 4884 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0122 |
| t 值 | 2.10 |
| IR | 0.156 |
| 近 26 周 mean / t | 0.0079 / 0.47 |

| 项 | 值 |
|----|----|
| spread | -0.00094 |
| D1 / D10 | 0.00178 / 0.00272 |

### 判定

- vs skew20：IC 0.0122（0.0245，-50%）、t 2.10（4.29）——大幅劣化。
- 结论：**无效（谱峰确认）**——**偏度谱峰 20 日**（矩估计需足够样本，
  10 日噪声大）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_skew10`（初始） | 批次 3 轮 53：K2 skew10 | 0.0122 | 2.10 | 无效：谱峰 20 日 |

## 6. 风险与备注

- **矩谱结论**：偏度/峰度谱峰 20 日（矩估计样本需求）；
  corr（非矩）谱峰 10 日例外。
- 基准 [`reversal_20d_skew.md`](reversal_20d_skew.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
