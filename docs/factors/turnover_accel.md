---
xname: turnover_accel
formula: |
  signal = MA(turnover,5) / MA(turnover,20)
tags: [mine_b4r11, turnover, acceleration, event_dimension]
params: {}
status: 候选（变化维度独立显著）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# turnover_accel 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `turnover_accel`（= `factor/turnover_accel.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（IC 0.0382、t=5.52、IR 0.414） |
| 标签 | mine_b4r11, turnover, acceleration, event_dimension |
| 创建 | 2026-08-18（批次 4 轮次 11，种子 `turnover_level`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**隐含假设精确化**：种子"换手率**水平** = 投机强度"——深挖出隐含假设
"投机强度是状态（水平）而非事件（变化）"。变异为**换手加速**（近期/历史比）：
资金涌入/退潮是事件维度，与水平正交。

**数学表达**：

```
signal = MA(turnover, 5) / MA(turnover, 20)   （加速比 > 1 = 换手加速）
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
name: turnover_accel
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
  from polars_ta.prefix.wq import ts_mean
  signal = ts_mean(turnover, 5) / ts_mean(turnover, 20)
```

## 4. 验证结果

> 数据快照自 `results/turnover_accel/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0711 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0382 |
| t 值 | 5.52 |
| IR | 0.414 |
| 近 26 周 mean / t | 0.0014 / 0.07 |
| PearsonIC mean | -0.0272（t=-4.56） |

| 项 | 值 |
|----|----|
| spread | 0.00461 |
| D1 / D10 | 0.00290 / -0.00171 |

### 判定

- vs turnover_level（水平）：IC -47%（0.0719→0.0382）、**t +8%（5.11→5.52）**、
  **IR +9%（0.379→0.414）**——**事件维度独立显著**（t/IR 超水平版）。
- 水平仍是主导信号（IC 差距大）；变化维度提供稳定性补充。
- 近 26 周 t=0.07（近期失效）。
- 结论：**候选**——换手率**变化**是独立维度（与水平正交——组合潜力待测）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `turnover_accel`（初始） | 批次 4 轮 11：T1 水平→变化（加速比） | 0.0382 | 5.52 | 候选：事件维度独立 |

## 6. 风险与备注

- **维度发现**：换手率水平（状态）与变化（事件）是两个独立维度——
  从隐含假设深挖自然产生的结构变异（比率结构）。
- 种子 [`turnover_level.md`](turnover_level.md)（水平版）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
