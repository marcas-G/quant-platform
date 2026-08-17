---
xname: reversal_10d_intraday_extreme
formula: |
  signal = ts_sum(close/open-1, 10) * mask(cs_rank(turnover) > 0.8)
tags: [mine_b4r4, reversal, intraday10, extreme_turn, strong, spread_record]
params: {}
status: 候选（强候选：t=8.20/IR=0.611/spread 全库纪录）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_10d_intraday_extreme 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_10d_intraday_extreme`（= `factor/reversal_10d_intraday_extreme.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强候选：t=8.20/IR=0.611/spread 0.95%/周全库纪录） |
| 标签 | mine_b4r4, reversal, intraday10, extreme_turn, strong, spread_record |
| 创建 | 2026-08-18（批次 4 轮次 4，种子 `reversal_10d_intraday`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：10 日日内弱（谱下界）——检验是否因全样本噪声稀释：极端投机子样本
（top 20% 换手）聚焦。

**数学表达**：

```
signal = Σ(close/open-1, 10) × 1{cs_rank(turnover) > 0.8}
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
name: reversal_10d_intraday_extreme
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
  _sig = ts_sum(close/open - 1, 10)
  _w = sign(sign(cs_rank(turnover) - 0.8) + 1) / 2
  signal = _sig * _w
```

## 4. 验证结果

> 数据快照自 `results/reversal_10d_intraday_extreme/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 180 |
| 平均股票数 | 4884 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0537 |
| t 值 | 8.20 |
| IR | 0.611 |
| 近 26 周 mean / t | -0.0036 / -0.27 |
| PearsonIC mean | nan（t=0.00） |

| 项 | 值 |
|----|----|
| spread | 0.00954（0.95%/周——**全库纪录**） |
| 分层组数 | 6（掩码 0 值聚集） |

### 判定

- vs 10 日日内（种子）：**t 4.49→8.20 近翻倍、IR 0.335→0.611 近翻倍**、
  IC +7%——**10 日弱因确认是噪声稀释**，极端投机聚焦后显著超越。
- vs 20 日日内（0.0591/5.22/0.391）：t/IR 全面超越、IC 略低。
- **spread 0.95%/周 全库纪录**（超 vwap_turn 的 0.76%）。
- 近 26 周 t=-0.27（近期失效——掩码信号近期走弱）。
- 结论：**候选（强候选）**——10 日日内×极端换手为档位区分最强表达。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_10d_intraday_extreme`（初始） | 批次 4 轮 4：I3 极端换手聚焦 | 0.0537 | 8.20 | **强候选**：spread 全库纪录 |

## 6. 风险与备注

- **近期失效**：近 26 周 t=-0.27——极端投机日内反转近期走弱（与反转家族
  衰减一致但更甚）。
- **掩码代价**：80% 股票信号 0（分层聚集、有效样本少）。
- 种子 [`reversal_10d_intraday.md`](reversal_10d_intraday.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
