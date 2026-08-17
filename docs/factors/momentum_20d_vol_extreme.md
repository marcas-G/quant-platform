---
xname: momentum_20d_vol_extreme
formula: |
  signal = mom20 * mask(ts_rank(volume,20) > 0.8)
tags: [mine_b4r2, reversal, vol_extreme, continuous]
params: {}
status: 无效（量能信息连续分布）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_vol_extreme 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_vol_extreme`（= `factor/momentum_20d_vol_extreme.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——量能信息连续分布（极端掩码稀释） |
| 标签 | mine_b4r2, reversal, vol_extreme, continuous |
| 创建 | 2026-08-18（批次 4 轮次 2，种子 `momentum_20d_turnrank_vol`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：轮 1 证明换手率信息集中在 top 20% 极端区；检验量能（放量事件）是否同样。

**数学表达**：

```
signal = mom20 × 1{ts_rank(volume, 20) > 0.8}
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
name: momentum_20d_vol_extreme
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, ts_rank
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  _w = sign(sign(ts_rank(volume, 20) - 0.8) + 1) / 2
  signal = _mom * _w
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_vol_extreme/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0221 |
| t 值 | 3.84 |
| IR | 0.288 |
| 近 26 周 mean / t | 0.0021 / 0.14 |
| PearsonIC mean | -0.0187（t=-2.98） |

| 项 | 值 |
|----|----|
| spread | 0.00566 |
| D1 / D10 | 0.00263 / -0.00303 |

### 判定

- vs turnrank（连续量能条件化对照）：IC 0.0221（0.0419，**-47%**）、t 3.84（3.37）、
  IR 0.288（0.255）、spread 0.00566（0.00470，+20%）。
- vs 轮 1（极端换手）：**对比鲜明**——换手极端区信息密（t 翻倍）、量能极端区
  信息稀（IC 减半）。
- 结论：**无效（V4' 否定）**——量能确认信息**连续分布**，不集中在极端放量；
  极端掩码适用于换手维度、不适用于量能维度。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `momentum_20d_vol_extreme`（初始） | 批次 4 轮 2：V4 极端放量掩码 | 0.0221 | 3.84 | 无效：量能连续分布 |

## 6. 风险与备注

- **维度性质区分**：换手率（投机水平）→ 极端聚集；量能（事件）→ 连续——
  掩码策略按维度性质选择。
- 种子 [`momentum_20d_turnrank_vol.md`](momentum_20d_turnrank_vol.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
