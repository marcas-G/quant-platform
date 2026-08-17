---
xname: reversal_20d_skew_extreme
formula: |
  signal = skew20 * mask(cs_rank(turnover) > 0.8)
tags: [mine_b4r6, skew, lottery, extreme_turn, strong]
params: {}
status: 候选（强候选：t=7.50/IR=0.562）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_skew_extreme 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_skew_extreme`（= `factor/reversal_20d_skew_extreme.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强候选：t=7.50/IR=0.562） |
| 标签 | mine_b4r6, skew, lottery, extreme_turn, strong |
| 创建 | 2026-08-18（批次 4 轮次 6，种子 `reversal_20d_skew`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：轮 4 证明极端换手聚焦显著提升（日内版）；检验彩票（偏度）信息是否
同样集中在极端投机子样本。

**数学表达**：

```
signal = skewness(returns, 20) × 1{cs_rank(turnover) > 0.8}
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
name: reversal_20d_skew_extreme
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
  from polars_ta.prefix.wq import ts_skewness, cs_rank
  _skew = ts_skewness(returns(close), 20)
  _w = sign(sign(cs_rank(turnover) - 0.8) + 1) / 2
  signal = _skew * _w
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_skew_extreme/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0367 |
| t 值 | 7.50 |
| IR | 0.562 |
| 近 26 周 mean / t | 0.0230 / 1.39 |
| PearsonIC mean | -0.0138（t=-2.60） |

| 项 | 值 |
|----|----|
| spread | 0.00103 |
| 分层 | 组数 6（掩码 0 值聚集） |

### 判定

- vs skew（种子）：**IC +50%**（0.0245→0.0367）、**t 4.29→7.50**、
  **IR 0.322→0.562**——彩票信息集中在极端投机区（与日内版同模式）。
- 近 26 周 t=1.39（近期仍有效）。
- 结论：**候选（强候选）**——极端换手聚焦是跨维度通用增强（日内/彩票均有效）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_skew_extreme`（初始） | 批次 4 轮 6：S2 极端换手聚焦 | 0.0367 | 7.50 | **强候选** |

## 6. 风险与备注

- **极端聚焦通用性**：轮 1（换手条件化）/轮 4（日内）/轮 6（彩票）——
  极端换手掩码是跨维度通用增强器。
- 种子 [`reversal_20d_skew.md`](reversal_20d_skew.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
