---
xname: reversal_20d_vol_flow
formula: |
  signal = cs_rank(ts_rank(vol,10)) + cs_rank(flow20)
tags: [mine_b3r74, reversal, vol_flow, complementary]
params: {}
status: 候选（IC 超 netflow 父本）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_vol_flow 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_vol_flow`（= `factor/reversal_20d_vol_flow.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（IC 0.0461 超 netflow、IR 0.466） |
| 标签 | mine_b3r74, reversal, vol_flow, complementary |
| 创建 | 2026-08-18（批次 3 轮次 74，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量能确认（事件）× 资金流（方向加权）秩次加法——量维度组合。

**数学表达**：

```
signal = cs_rank(ts_rank(volume, 10)) + cs_rank(Σ(amount×sign(returns), 20))
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
name: reversal_20d_vol_flow
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
  from polars_ta.prefix.wq import ts_rank, ts_sum, cs_rank
  signal = cs_rank(ts_rank(volume, 10)) + cs_rank(ts_sum(amount * sign(returns(close)), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_vol_flow/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0461 |
| t 值 | 6.22 |
| IR | 0.466 |
| 近 26 周 mean / t | 0.0067 / 0.31 |

| 项 | 值 |
|----|----|
| spread | 0.00348 |
| D1 / D10 | 0.00199 / -0.00149 |

### 判定

- vs netflow（父）：IC +11%（0.0417→0.0461）、t 6.22（5.01，+24%）、
  IR 0.466（0.375）——量能事件与资金流互补。
- 结论：**候选**——vol×flow 组合有效。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_vol_flow`（初始） | 批次 3 轮 74：V3 vol×flow | 0.0461 | 6.22 | 候选：IC 超 netflow |

## 6. 风险与备注

- **量维度组合**：vol×flow 互补（事件 vs 方向）——与 corr×flow（轮 58）
  同为有效量维度组合；量维度间组合可行性取决于结构差异。
- 基准 [`reversal_20d_netflow.md`](reversal_20d_netflow.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
