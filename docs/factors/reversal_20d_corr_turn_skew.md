---
xname: reversal_20d_corr_turn_skew
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(skew20)
tags: [mine_b3r77, reversal, duplicate_commute, diluted]
params: {}
status: 无效（与 turn_skew_corr 数学等价——重复；skew 稀释 corr_turn）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_turn_skew 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_turn_skew`（= `factor/reversal_20d_corr_turn_skew.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——与轮 63 数学等价（重复）；skew 稀释 |
| 标签 | mine_b3r77, reversal, duplicate_commute, diluted |
| 创建 | 2026-08-18（批次 3 轮次 77，种子 `reversal_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：corr×turn（强互补）加第三维 skew。

**发现**：加法交换律下 corr+turn+skew 与轮 63 的 turn+skew+corr **数学等价**
（逐位相同：IC 0.0656/t 6.75/IR 0.506）——重复因子。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(skew20)
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
name: reversal_20d_corr_turn_skew
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_skewness, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_turn_skew/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0656 |
| t 值 | 6.75 |
| IR | 0.506 |
| 近 26 周 mean / t | 0.0499 / 1.72 |

| 项 | 值 |
|----|----|
| spread | 0.00335 |
| D1 / D10 | 0.00304 / -0.00030 |

### 判定

- 与 [`reversal_20d_turn_skew_corr.md`](reversal_20d_turn_skew_corr.md)（轮 63）
  **逐位等价**（加法交换律）——重复因子。
- vs corr_turn（二维）：IC 0.0656（0.0691，-5%）——skew 第三维稀释
  （skew 与 corr 部分重叠，轮 52 冗余确认）。
- 结论：**无效（重复+稀释）**——权威记录在轮 63 档案；
  二维 corr_turn（0.0691）优于三维。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_turn_skew`（初始） | 批次 3 轮 77：T3 三维加法 | 0.0656 | 6.75 | 无效：重复+稀释 |

## 6. 风险与备注

- **流程教训**：加法组合存在交换对称（轮 11 教训重申）——
  组合轮次前先查已有组合；corr/turn/skew 三维已在轮 63 入库。
- 基准 [`reversal_20d_corr_turn.md`](reversal_20d_corr_turn.md)（强候选 0.0691）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
