---
xname: momentum_20d_turnrank_lowturn
formula: |
  signal = (MA(close,20)/close[t-20]-1) * (1 - cs_rank(turnover))
tags: [mine_b3r14, reversal, low_turnover, liquidity_comp_falsified]
params: {}
status: 无效（证伪流动性补偿方向）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_turnrank_lowturn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_turnrank_lowturn`（= `factor/momentum_20d_turnrank_lowturn.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——低换手方向证伪（高换手是唯一有效方向） |
| 标签 | mine_b3r14, reversal, low_turnover, liquidity_comp_falsified |
| 创建 | 2026-08-18（批次 3 轮次 14，种子 `momentum_20d_turnrank_quad`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `momentum_20d_turnrank` 档案标注的**待迭代项**——换手率条件化
反向对照：`1 - cs_rank(turnover)`（低换手反转更强——流动性补偿假设）。
（原设计 target 变异因 spec.target 未接线不可实现，平台缺口已记录。）

**数学表达**：

```
signal = (MA(close,20)/close[t-20] - 1) × (1 - cs_rank(turnover))
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
name: momentum_20d_turnrank_lowturn
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, cs_rank
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * (1 - cs_rank(turnover))
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_turnrank_lowturn/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 174 |
| 平均股票数 | 4875 |
| 信号缺失率 | 0.0942 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0148 |
| t 值 | 1.47 |
| IR | 0.111 |
| 近 26 周 mean / t | 0.0073 / 0.22 |
| PearsonIC mean | 0.0039（t=0.51） |

| 项 | 值 |
|----|----|
| spread | -0.00039（负值 = 档位反向） |
| D1 / D10 | 0.00246 / 0.00285 |

### 判定

- vs turnrank（高换手方向）：IC 0.0148（0.0419，**-65%**）、t 1.47（不显著）、
  spread -0.00039（负值）。
- 结论：**无效（方向性确认）**——**流动性补偿假设被否定**；
  反转-换手率交互是**单方向的**（高换手投机超调），低换手样本无反转增强。
  关闭 turnrank 档案的"反向对照待迭代"项。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`momentum_20d_turnrank_extreme` | 批次4轮1：L4 极端区掩码，见 [`momentum_20d_turnrank_extreme.md`](momentum_20d_turnrank_extreme.md) | 0.0448 | 6.51 | **强候选**：t/IR 近翻倍、spread +62% |
| 2026-08-18 | `momentum_20d_turnrank_lowturn`（初始） | 批次 3 轮 14：Q2 换手率方向反转 | 0.0148 | 1.47 | 无效：证伪流动性补偿方向 |

## 6. 风险与备注

- **方向性结论**：反转-换手率交互单方向（高换手）——后续条件化方向
  变异一律以"高值方向"优先验证。
- **平台缺口记录**：spec.target 未接线（quant_core 固定评估 5d）——
  持有期变异不可实现，待平台接线。
- 种子 [`momentum_20d_turnrank_quad.md`](momentum_20d_turnrank_quad.md)；
  权威记录 [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
