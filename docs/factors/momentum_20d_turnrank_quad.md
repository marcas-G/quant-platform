---
xname: momentum_20d_turnrank_quad
formula: |
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * cs_rank(turnover) ** 2
tags: [mine_r4, reversal, turnover_conditional, convex, no_gain]
params: {}
status: 无效（相对种子无改善）
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# momentum_20d_turnrank_quad 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_turnrank_quad`（= `factor/momentum_20d_turnrank_quad.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 无效——凸化条件化相对种子无改善；保留作对照 |
| 标签 | mine_r4, reversal, turnover_conditional, convex, no_gain |
| 创建 | 2026-08-17（挖因子批次 2 轮次 4，种子 `momentum_20d_turnrank`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `momentum_20d_turnrank` 的隐含假设 (H3) 换手率条件化线性单调。
检验"反转强度随换手率**超线性**递增"（投机集中区超调更陡峭）：
条件权重从 `cs_rank(turnover)` 凸化为 `cs_rank(turnover)**2`
（高换手权重更突出 0.9²=0.81、低换手收敛 0.3²=0.09）。

**数学表达**：

```
signal = (MA(close, 20) / close[t-20] - 1) × cs_rank(turnover)²
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
name: momentum_20d_turnrank_quad
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
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * cs_rank(turnover) ** 2
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_turnrank_quad/summary.json`（2026-08-17）。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 174 |
| 平均股票数 | 4875 |
| 复权 | qfq |
| 信号缺失率 | 9.42% |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0411 |
| t 值 | 3.38 |
| IR | 0.256 |
| 近 26 周 mean | -0.0137 |
| 近 26 周 t | -0.46 |
| PearsonIC mean（原始信号） | -0.0307（t=-2.97） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00499 |
| 单调性 | false |
| D1 mean_ret | 0.00271 |
| D10 mean_ret | -0.00227 |

### 判定

- 与种子 `momentum_20d_turnrank` 对比：IC 0.0411（0.0419）、t 3.38（3.37）、
  spread 0.00499（0.00470，+6%）、近 26 周 t=-0.46（-0.34）。
- 结论：**无效（相对种子无改善）**——凸化仅带来噪声级 spread 微增、IC 略降；
  H3'（超线性条件化）未获支持，线性条件化已充分。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-17 | `momentum_20d_turnrank_quad`（初始） | 挖因子轮 4：H3 线性 → 凸化 `**2` | 0.0411 | 3.38 | 无效：相对种子无改善 |

## 6. 风险与备注

- **证伪价值**：条件化凸性方向已排除——换手率条件化保持线性即可，
  未来迭代不要在权重凸性方向重复探索。
- 种子 [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md) 为换手率条件化
  反转基准（观察中）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
