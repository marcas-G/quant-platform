---
xname: reversal_20d_corr_turn_vol
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(vol10)
tags: [mine_b3r78, reversal, corr_turn_vol, marginal]
params: {}
status: 观察中（IC 降、t/IR 升）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_turn_vol 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_turn_vol`（= `factor/reversal_20d_corr_turn_vol.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（IC 0.0625 降、t/IR 升） |
| 标签 | mine_b3r78, reversal, corr_turn_vol, marginal |
| 创建 | 2026-08-18（批次 3 轮次 78，种子 `reversal_20d_nowin`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：corr×turn（强互补）加第三维 vol——量维度重叠测试。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(ts_rank(vol,10))
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
name: reversal_20d_corr_turn_vol
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_rank, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_rank(volume, 10))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_turn_vol/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 180 |
| 平均股票数 | 4884 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0625 |
| t 值 | 7.00 |
| IR | 0.522 |
| 近 26 周 mean / t | 0.0477 / 1.83 |

| 项 | 值 |
|----|----|
| spread | 0.00384 |
| D1 / D10 | 0.00320 / -0.00065 |

### 判定

- vs corr_turn（二维）：IC 0.0625（0.0691，**-10%**）、**t 7.00（6.33，+11%）**、
  IR 0.522（0.472，+11%）、近 26 周 1.83（1.85 持平）——vol 增稳定性
  但稀释 IC（corr 与 vol 同属量维度部分重叠）。
- 结论：**观察中（边际）**——量维度重叠的稳定性-水平 trade-off；
  二维 corr_turn（IC 更优）与三维（稳定性更优）各有所长。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_turn_vol`（初始） | 批次 3 轮 78：T3 三维加法 | 0.0625 | 7.00 | 观察中：IC 降、t/IR 升 |

## 6. 风险与备注

- **三维构成谱**：corr/turn/skew（0.0656）、corr/turn/vol（0.0625）、
  turn/skew/vol（0.0632）——二维 corr_turn（0.0691）仍是 IC 最优组合之一。
- 基准 [`reversal_20d_corr_turn.md`](reversal_20d_corr_turn.md)（强候选）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
