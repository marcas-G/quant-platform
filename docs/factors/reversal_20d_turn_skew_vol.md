---
xname: reversal_20d_turn_skew_vol
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(ts_rank(vol,20))
tags: [mine_b3r65, reversal, three_dim_tsv, stability_record]
params: {}
status: 候选（三维 t/IR 新纪录）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_turn_skew_vol 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_turn_skew_vol`（= `factor/reversal_20d_turn_skew_vol.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（三维 t/IR 新纪录：6.94/0.520） |
| 标签 | mine_b3r65, reversal, three_dim_tsv, stability_record |
| 创建 | 2026-08-18（批次 3 轮次 65，种子 `momentum_20d_turnrank_avg20`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：三维构成变体——turn/skew/vol（量能替代 corr）。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(ts_rank(vol, 20))
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
name: reversal_20d_turn_skew_vol
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
  from polars_ta.prefix.wq import ts_skewness, ts_rank, cs_rank
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_rank(volume, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_turn_skew_vol/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0632 |
| t 值 | 6.94（三维新纪录） |
| IR | 0.520（三维新纪录） |
| 近 26 周 mean / t | 0.0479 / 1.67 |
| PearsonIC mean | -0.0211（t=-2.66） |

| 项 | 值 |
|----|----|
| spread | 0.00409 |
| D1 / D10 | 0.00270 / -0.00139 |

### 判定

- vs turn_skew_corr（三维 IC 纪录）：IC 0.0632（0.0656，-4%）、
  **t 6.94（6.75）**、**IR 0.520（0.506）**——量能维度稳定性更强。
- vs turn_skew（二维）：IC 持平、t +21%。
- 结论：**候选**——turn/skew/vol 构成三维稳定性最优；
  corr 构成三维 IC 最优（0.0656）——两构成互补。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_turn_skew_vol`（初始） | 批次 3 轮 65：V3 三维加法 | 0.0632 | 6.94 | 候选：三维 t/IR 新纪录 |

## 6. 风险与备注

- **三维构成对照**：corr 构成（IC 0.0656）vs vol 构成（IR 0.520）——
  结构 vs 量能稳定性偏好。
- 基准 [`reversal_20d_turn_skew_corr.md`](reversal_20d_turn_skew_corr.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
