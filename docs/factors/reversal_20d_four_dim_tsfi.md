---
xname: reversal_20d_four_dim_tsfi
formula: |
  signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(flow30) + cs_rank(intraday20)
tags: [mine_b3r97, reversal, four_dim_tsfi, near_record]
params: {}
status: 候选（IC 0.0727 接近全库最强）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_four_dim_tsfi 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_four_dim_tsfi`（= `factor/reversal_20d_four_dim_tsfi.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（IC 0.0727 接近全库最强 0.0744） |
| 标签 | mine_b3r97, reversal, four_dim_tsfi, near_record |
| 创建 | 2026-08-18（批次 3 轮次 97，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：投机系三维加第四维 intraday——tsfi 构成。

**数学表达**：

```
signal = cs_rank(turn) + cs_rank(skew20) + cs_rank(flow30) + cs_rank(intraday20)
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
name: reversal_20d_four_dim_tsfi
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
  from polars_ta.prefix.wq import ts_skewness, ts_sum, cs_rank
  signal = cs_rank(turnover) + cs_rank(ts_skewness(returns(close), 20)) + cs_rank(ts_sum(amount * sign(returns(close)), 30)) + cs_rank(ts_sum(close/open - 1, 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_four_dim_tsfi/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0727 |
| t 值 | 6.73 |
| IR | 0.507 |
| 近 26 周 mean / t | 0.0428 / 1.24 |

| 项 | 值 |
|----|----|
| spread | 0.00475 |
| D1 / D10 | 0.00305 / -0.00170 |

### 判定

- vs turn_skew_flow30（三维）：IC +4.3%（0.0697→0.0727）——intraday 有效。
- vs cti 纪录（0.0744）：差 2.3%——投机系四维接近全库最强。
- 结论：**候选**——tsfi 四维为投机系最优构成。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_four_dim_tsfi`（初始） | 批次 3 轮 97：F3 四维加法 | 0.0727 | 6.73 | 候选：接近纪录 |

## 6. 风险与备注

- **构成谱**：cti（corr 系 0.0744）vs tsfi（投机系 0.0727）——
  两构成接近；IC 纪录保持 cti。
- 基准 [`reversal_20d_corr_turn_intraday.md`](reversal_20d_corr_turn_intraday.md)
  （全库 IC 纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
