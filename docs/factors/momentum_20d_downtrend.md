---
xname: momentum_20d_downtrend
formula: |
  signal = _m20 * (1 - sign(_m60)) / 2
tags: [mine_b3r4, reversal, downtrend_mask, falsified]
params: {}
status: 无效（证伪：反转是全趋势状态现象）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_downtrend 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_downtrend`（= `factor/momentum_20d_downtrend.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——趋势掩码劣化 |
| 标签 | mine_b3r4, reversal, downtrend_mask, falsified |
| 创建 | 2026-08-18（批次 3 轮次 4，种子 `momentum_20d_net60`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `momentum_20d_net60` 证伪"趋势线性剥离"；本轮换结构——检验
"反转只在中期（60 日）下跌趋势中有效"（超跌反弹）：`× (1 - sign(_m60)) / 2`
下跌趋势掩码（下跌=1、上涨=0、持平=0.5）。

**数学表达**：

```
signal = _m20 × (1 - sign(_m60)) / 2
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
name: momentum_20d_downtrend
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
  from polars_ta.prefix.wq import ts_mean, ts_delay
  _m20 = ts_mean(close, 20) / ts_delay(close, 20) - 1
  _m60 = ts_mean(close, 60) / ts_delay(close, 60) - 1
  signal = _m20 * (1 - sign(_m60)) / 2
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_downtrend/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 169 |
| 平均股票数 | 4868 |
| 信号缺失率 | 0.1238 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0177 |
| t 值 | 2.11 |
| IR | 0.162 |
| 近 26 周 mean / t | 0.0092 / 0.40 |
| PearsonIC mean | -0.0066（t=-0.92） |

| 项 | 值 |
|----|----|
| spread | 0.00238 |
| D1 / D10 | 0.00306 / 0.00067 |

### 判定

- vs reversal_20d（无掩码）：IC 0.0177（0.0409，-57%）、t 2.11（3.47）、
  spread 0.00238（0.00362，-34%）。
- 结论：**无效（证伪超跌反弹假设）**——反转在全部趋势状态下同样有效；
  上涨趋势中被置 0 的样本（约一半）同样含反转信息，掩码信息损失大。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `momentum_20d_downtrend`（初始） | 批次 3 轮 4：趋势条件化掩码 | 0.0177 | 2.11 | 无效：掩码损失一半样本 |

## 6. 风险与备注

- **证伪价值**：趋势方向掩码排除（与 net60 相减式同被证伪）——60 日趋势
  与 20 日反转无结构性交互；后续不再探索趋势-反转交互方向。
- 种子 [`momentum_20d_net60.md`](momentum_20d_net60.md)（已证伪）；反转基准
  [`reversal_20d.md`](reversal_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
