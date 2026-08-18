---
xname: amihud_illiq_turn_20d
formula: |
  signal = ts_mean(abs(returns)/(turnover+1e-6), 20)
tags: [mine_b4r16, amihud, turnover, size_info, falsified]
params: {}
status: 无效（amount 口径更优；近 26 周亮点）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# amihud_illiq_turn_20d 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `amihud_illiq_turn_20d`（= `factor/amihud_illiq_turn_20d.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效——amount 口径更优 |
| 标签 | mine_b4r16, amihud, turnover, size_info, falsified |
| 创建 | 2026-08-18（批次 4 轮次 16，种子 `amihud_illiq_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**隐含假设深挖**：分母为什么是成交额（绝对量）——流动性本质是相对可交易
股本（换手率口径）。

**数学表达**：

```
signal = MA(|r| / turnover, 20)
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
name: amihud_illiq_turn_20d
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
  from polars_ta.prefix.wq import ts_mean
  signal = ts_mean(abs(returns(close)) / (turnover + 1e-6), 20)
```

## 4. 验证结果

> 数据快照自 `results/amihud_illiq_turn_20d/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0276 |
| t 值 | 2.50 |
| IR | 0.187 |
| 近 26 周 mean / t | 0.0494 / 1.52 |

| 项 | 值 |
|----|----|
| spread | 0.00091 |
| D1 / D10 | 0.00177 / 0.00086 |

### 判定

- vs amihud（amount 口径）：IC -23%（0.0357→0.0276）、t 2.50（2.96）——
  **换手率口径不更纯：amount 的规模成分有信息**（与 netflow 绝对量结论
  一致——规模信息有值）。
- **近 26 周 t=1.52（强）**——换手率口径非流动性近期有效。
- 结论：**无效（全期证伪）**——Amihud 保持 amount 口径；
  换手率口径为近期观察项。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `amihud_illiq_turn_20d`（初始） | 批次 4 轮 16：分母→turnover | 0.0276 | 2.50 | 无效：amount 更优 |

## 6. 风险与备注

- **规模信息结论**（与 netflow_pct 一致）：绝对量口径含规模成分且规模
  信息有值——换手率归一化方向关闭。
- 种子 [`amihud_illiq_20d.md`](amihud_illiq_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
