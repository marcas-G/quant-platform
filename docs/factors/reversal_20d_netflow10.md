---
xname: reversal_20d_netflow10
formula: |
  signal = ts_sum(amount * sign(returns(close)), 10)
tags: [mine_b3r47, reversal, netflow10, peak20]
params: {}
status: 无效（netflow 谱峰 20 日）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_netflow10 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_netflow10`（= `factor/reversal_20d_netflow10.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——netflow 谱峰 20 日 |
| 标签 | mine_b3r47, reversal, netflow10, peak20 |
| 创建 | 2026-08-18（批次 3 轮次 47，种子 `momentum_20d_turnrank_avg20`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：资金流窗口谱——10 日（结构信号短窗假设的谱系补全）。

**数学表达**：

```
signal = Σ (amount × sign(returns)) over 10d
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
name: reversal_20d_netflow10
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
  signal = ts_sum(amount * sign(returns(close)), 10)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_netflow10/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 180 |
| 平均股票数 | 4884 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0403 |
| t 值 | 4.86 |
| IR | 0.362 |
| 近 26 周 mean / t | -0.0199 / -0.91 |

| 项 | 值 |
|----|----|
| spread | 0.00265 |
| D1 / D10 | 0.00124 / -0.00141 |

### 判定

- vs netflow20：IC 0.0403（0.0417，-3%）、t 4.86（5.01）、IR 0.362（0.375）——
  全面略降。
- 结论：**无效（谱峰确认）**——**netflow 谱峰 20 日**（与 corr 的 10 日峰
  不同：方向加权累计需 20 日平滑，短窗噪声大）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_netflow10`（初始） | 批次 3 轮 47：N2 netflow10 | 0.0403 | 4.86 | 无效：谱峰 20 日 |

## 6. 风险与备注

- **窗口谱分类**：corr（结构相关）谱峰 10 日、netflow（方向累计）谱峰
  20 日、intraday（价格幅度）谱峰 20 日——各维度谱峰已定位。
- 基准 [`reversal_20d_netflow.md`](reversal_20d_netflow.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
