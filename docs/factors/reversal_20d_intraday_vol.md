---
xname: reversal_20d_intraday_vol
formula: |
  signal = ts_sum(close/open - 1, 20) * ts_rank(volume, 20)
tags: [mine_b3r30, reversal, intraday_vol, stability_record]
params: {}
status: 观察中（t/IR 创纪录，IC 略降）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_intraday_vol 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_intraday_vol`（= `factor/reversal_20d_intraday_vol.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（t=5.33/IR=0.399 创纪录；IC 略降） |
| 标签 | mine_b3r30, reversal, intraday_vol, stability_record |
| 创建 | 2026-08-18（批次 3 轮次 30，种子 `momentum_20d_net60`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：日内纪录因子（轮 25）× 时序量能确认（放量事件维度——
与横截面换手率条件化正交）。

**数学表达**：

```
signal = Σ(close/open - 1) over 20d × ts_rank(volume, 20)
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
name: reversal_20d_intraday_vol
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
  from polars_ta.prefix.wq import ts_sum, ts_rank
  signal = ts_sum(close/open - 1, 20) * ts_rank(volume, 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_intraday_vol/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0547 |
| t 值 | 5.33（创纪录） |
| IR | 0.399（创纪录） |
| 近 26 周 mean / t | 0.0089 / 0.33 |
| PearsonIC mean | -0.0356（t=-3.69） |

| 项 | 值 |
|----|----|
| spread | 0.00555 |
| D1 / D10 | 0.00265 / -0.00290 |

### 判定

- vs intraday（纪录）：IC 0.0547（0.0591，-7%）、**t 5.33（5.22）**、
  **IR 0.399（0.391）**、spread 持平。
- vs intraday_turn（纪录）：IC -9%，t/IR 更高，近 26 周 t=0.33（turn 0.00）。
- 结论：**观察中（边际）**——量能确认**增强稳定性而非水平**：
  t/IR 创纪录、近期不衰减；IC 略降（量能权重稀释部分秩次信息）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_intraday_vol`（初始） | 批次 3 轮 30：V3 量能确认 | 0.0547 | 5.33 | 观察中：t/IR 创纪录，IC 略降 |

## 6. 风险与备注

- **稳定性-水平权衡**：量能确认换稳定性（t/IR/近 26 周）舍水平（IC）；
  换手率条件化（轮 27）换水平（IC 0.0604）——两者可考虑叠加
  （intraday × turn × vol 三层）待测。
- 基准 [`reversal_20d_intraday.md`](reversal_20d_intraday.md)、
  [`reversal_20d_intraday_turn.md`](reversal_20d_intraday_turn.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
