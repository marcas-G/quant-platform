---
xname: momentum_20d_turnrank
formula: |
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * cs_rank(turnover)
tags: [mine_round_1, reversal, turnover_conditional, hypothesis_precision]
params: {}
status: 观察中
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# momentum_20d_turnrank 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_turnrank`（= `factor/momentum_20d_turnrank.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 观察中（全期与对照持平、spread 增强；近 26 周衰减） |
| 标签 | mine_round_1, reversal, turnover_conditional, hypothesis_precision |
| 创建 | 2026-08-17（挖因子 skill 轮次 1，种子 `momentum_20d`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `momentum_20d` 的两个隐含假设——(H9) 动量方向在 A 股存在
（已证伪：IC=-0.0409, t=-3.47）；(H5) 横截面同质性：反转强度与换手率无关。
本因子变异 H9（取反转方向）并精确化 H5：**反转强度随换手率递增**——A 股
短期反转由投机/流动性冲击驱动的超调回摆，高换手子样本超调更大（彩票偏好
文献）。通过 `× cs_rank(turnover)` 把信号集中于反转最强的投机子样本，
实现"更详细准确的因子表达"（表达式深度不增）。

**核心逻辑**：20 日反转信号 × 当日换手率横截面分位（高换手权重≈1、低换手≈0）。

**数学表达**：

```
signal = (MA(close, 20) / close[t-20] - 1) × cs_rank(turnover)   (cs_rank ∈ [0,1])
```

**输入数据**：`close`（前复权）、`turnover`（daily_basic.turnover_rate 映射）。

## 3. 参数与实现

### 参数表

无参数（20 日窗口 + 换手率条件化固定表达）。

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
name: momentum_20d_turnrank
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
  signal = (ts_mean(close, 20) / ts_delay(close, 20) - 1) * cs_rank(turnover)
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_turnrank/summary.json`（2026-08-17）。

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
| RankIC mean（方向调整后） | 0.0419 |
| t 值 | 3.37 |
| IR | 0.255 |
| 近 26 周 mean | -0.0105 |
| 近 26 周 t | -0.34 |
| PearsonIC mean（原始信号） | -0.0281（t=-2.60） |

> 语义说明：RankIC 为方向调整后；Pearson 未乘方向（原始信号线性相关为负 =
> 高动量高换手股票未来收益低，与反转+投机超调一致）。

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00470（0.47%/周） |
| 单调性 | false |
| D1 mean_ret | 0.00293 |
| D10 mean_ret | -0.00177 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- |t|=3.37 > 2 显著；spread 0.47%/周 > 0.2% 关注线（0.36% → 0.47%，
  **较同向对照 reversal_20d 提升 30%**——条件化有效拉开两端档位）；
  IC 0.0419 与对照 0.0409 基本持平；IR 0.255 略低（0.260）。
- 近 26 周衰减（t=-0.34）与 reversal_20d（t=0.05）一致——2026 年以来
  20 日反转整体走弱，非条件化引入。
- 结论：**观察中**——换手率条件化在档位区分度上有效（H5' 得到部分支持），
  但整体预测力未显著超越不加条件化的反转。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-17 | 衍生：`momentum_20d_turnrank_quad` | 挖因子轮 4：H3 线性 → 凸化 `**2`，见 [`momentum_20d_turnrank_quad.md`](momentum_20d_turnrank_quad.md) | 0.0411 | 3.38 | **无效**：相对种子无改善，线性条件化已充分 |
| 2026-08-17 | `momentum_20d_turnrank`（初始） | 挖因子轮 1：变异 H9（方向→反转）+ H5（同质性→换手率条件化） | 0.0419 | 3.37 | 全期显著；spread +30%；近 26 周衰减 |

## 6. 风险与备注

- **近期失效**：近 26 周 t=-0.34，与 20 日反转家族（reversal_20d）同步衰减。
- **换手率方向性**：采用"高换手反转更强"（投机超调），若实际为流动性补偿
  （低换手更强）则应取 `1 - cs_rank(turnover)`——本轮结果 spread 增强支持
  高换手方向，但未做反向对照，待迭代。
- **缺失率**：9.42% > 对照 7.23%（turnover 缺失贡献），影响边际。
- **相关性**：与 [`reversal_20d.md`](reversal_20d.md) 高度相关（共享 20 日反转
  核心），组合使用时注意冗余；种子 [`momentum_20d.md`](momentum_20d.md) 为
  方向对照（已废弃）。变异记录见 `results/_mine_round_1.md`。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
