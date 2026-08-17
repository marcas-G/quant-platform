---
xname: reversal_20d_intraday
formula: |
  signal = ts_sum(close/open - 1, 20)   # 20 日累计日内收益（纯日内成分）
tags: [mine_b3r25, reversal, intraday, overnight_noise, library_best]
params: {}
status: 候选（最强候选：IC 0.0591 全库纪录）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_intraday 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_intraday`（= `factor/reversal_20d_intraday.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（最强候选：IC 0.0591、t=5.22、IR 0.39——全库纪录） |
| 标签 | mine_b3r25, reversal, intraday, overnight_noise, library_best |
| 创建 | 2026-08-18（批次 3 轮次 25，种子 `momentum_20d_decile`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：日收益 = 隔夜（open/close[t-1]）+ 日内（close/open）。累计收益
（cumret）混合两者；拆出**纯日内成分**（A 股日内反转文献：高开低走、
日内超调回摆）——隔夜跳空（消息/情绪）可能是噪声或反向。

**核心逻辑**：20 日累计日内收益（close/open - 1 求和）× 反转方向——
**日内超调回摆是反转的主驱动**。

**数学表达**：

```
signal = Σ (close/open - 1) over 20d
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
name: reversal_20d_intraday
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
  signal = ts_sum(close/open - 1, 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_intraday/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0711 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0591（**全库纪录**） |
| t 值 | 5.22 |
| IR | 0.391 |
| 近 26 周 mean / t | 0.0069 / 0.24 |
| PearsonIC mean | -0.0299（t=-2.82） |

| 项 | 值 |
|----|----|
| spread | 0.00556（0.56%/周） |
| D1 / D10 | 0.00299 / -0.00257 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- **IC 0.0591 > 0.05 优秀线（全库纪录，超 cumret 0.0503 +18%）**；
  t=5.22 强显著；IR 0.39 优秀；spread 0.56%/周。
- **D2' 强验证**：日内成分是反转主驱动；隔夜跳空（open/close[t-1]）为噪声
  或反向成分——混合累计收益被隔夜稀释。
- 近 26 周 t=0.24（边际，优于 cumret 的 -0.18）。
- 结论：**候选（最强候选）——反转家族新纪录**；
  下一步：日内 × 条件化/口径组合、隔夜成分反向测试。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_intraday`（初始） | 批次 3 轮 25：D2 日内成分 | 0.0591 | 5.22 | **最强候选**：IC 0.0591 全库纪录 |

## 6. 风险与备注

- **日内-隔夜拆分**：反转信息集中在日内成分——后续可测隔夜成分反向
  （预期 IC 负或零）、日内×条件化叠加。
- **数据口径**：close/open 为日频收盘/开盘价；日内收益对数据质量敏感
  （复权：qfq 视图下 open/close 同步复权，比值不受影响 ✓）。
- 基准 [`reversal_20d_cumret.md`](reversal_20d_cumret.md)（强候选）；
  种子 [`momentum_20d_decile.md`](momentum_20d_decile.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
