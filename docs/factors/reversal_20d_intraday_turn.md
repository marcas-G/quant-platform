---
xname: reversal_20d_intraday_turn
formula: |
  signal = ts_sum(close/open - 1, 20) * cs_rank(turnover)
tags: [mine_b3r27, reversal, intraday_turn, library_record]
params: {}
status: 候选（全库综合最强：IC 0.0604 纪录）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_intraday_turn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_intraday_turn`（= `factor/reversal_20d_intraday_turn.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（全库综合最强：IC 0.0604、t=5.26、IR 0.394） |
| 标签 | mine_b3r27, reversal, intraday_turn, library_record |
| 创建 | 2026-08-18（批次 3 轮次 27，种子 `momentum_20d_vwap`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：日内成分纪录因子（轮 25，IC 0.0591）× 换手率条件化——条件化在
cumret 上冗余（轮 20），但在更强日内核心上是否仍有增益（档案标注待做项）。

**核心逻辑**：20 日累计日内收益（高开低走超调）× 横截面换手率分位
（投机聚焦——日内超调在投机股更强）。

**数学表达**：

```
signal = Σ(close/open - 1) over 20d × cs_rank(turnover)
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
name: reversal_20d_intraday_turn
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
  from polars_ta.prefix.wq import ts_sum, cs_rank
  signal = ts_sum(close/open - 1, 20) * cs_rank(turnover)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_intraday_turn/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0711 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0604（**全库 IC 纪录**） |
| t 值 | 5.26 |
| IR | 0.394 |
| 近 26 周 mean / t | 0.0001 / 0.00 |
| PearsonIC mean | -0.0377（t=-3.52） |

| 项 | 值 |
|----|----|
| spread | 0.00610（0.61%/周） |
| D1 / D10 | 0.00294 / -0.00315 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- **IC 0.0604 全库纪录**（>0.05 优秀线 +21%）；t=5.26 强显著；IR 0.39 优秀；
  spread 0.61%/周。
- vs intraday（无条件化）：IC +2%、spread +10%——条件化在日内核心上
  **仍有微增益**（与 cumret 冗余不同：日内核心对投机聚焦敏感）。
- 近 26 周 t=0.00（持平——不衰减但也不强）。
- 结论：**候选（全库综合最强）**——日内反转 × 投机聚焦双精确化；
  下一步：量能确认叠加/正交性分析/换样本期复验。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_intraday_turn`（初始） | 批次 3 轮 27：V2 换手率条件化 | 0.0604 | 5.26 | **候选**：IC 0.0604 全库纪录 |

## 6. 风险与备注

- **纪录因子**：当前全库 IC/spread 综合最强——实盘化前需换样本期
  （2019-2021）外样本复验 + 换手率/容量分析。
- **近 26 周持平**（t=0.00）：近期不衰减（优于 20 日反转家族其他成员）。
- 基准 [`reversal_20d_intraday.md`](reversal_20d_intraday.md)（纪录）；
  种子 [`momentum_20d_vwap.md`](momentum_20d_vwap.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
