---
xname: amihud_illiq_20d
formula: |
  signal = ts_mean(abs(returns(close)) / amount, 20)
tags: [classic_seed, amihud, illiquidity]
params: {}
status: 候选（t=2.96 显著）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# amihud_illiq_20d 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `amihud_illiq_20d`（= `factor/amihud_illiq_20d.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 候选（t=2.96 显著） |
| 标签 | classic_seed, amihud, illiquidity |
| 创建 | 2026-08-18（经典因子种子扩充） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

Amihud 非流动性（|收益|/成交额 20 日均）——非流动性溢价。

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
name: amihud_illiq_20d
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
  signal = ts_mean(abs(returns(close)) / amount, 20)
```

## 4. 验证结果

> 数据快照自 `results/amihud_illiq_20d/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0357 |
| t 值 | 2.96 |
| IR | 0.222 |
| 近 26 周 mean / t | 0.0000 / 0.00 |
| PearsonIC mean | nan（t=0.00） |

| 项 | 值 |
|----|----|
| spread | 0.00605 |
| D1 / D10 | 0.00441 / -0.00164 |

### 判定

t=2.96 显著；spread 0.60%/周（档位区分大）；近 26 周 t=0.00（近期失效）。
结论：**候选**——非流动性维度全期有效、近期走弱。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`amihud_illiq_turn_20d` | 批次4轮16：分母→turnover，见 [`amihud_illiq_turn_20d.md`](amihud_illiq_turn_20d.md) | 0.0276 | 2.50 | **无效**：amount 更优（规模信息有值） |
| 2026-08-18 | `amihud_illiq_20d`（初始） | 经典种子扩充 | 0.0357 | 2.96 | 候选（t=2.96 显著） |

## 6. 风险与备注

- **正交种子价值**：与反转家族低相关（预期）——挖因子新种子池成员。
- 缺失率 0.0723。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
