---
xname: low_vol_20d
formula: |
  signal = -ts_std_dev(returns(close), 20)
tags: [classic_seed, low_vol, strong]
params: {}
status: 候选（强：IC 0.0696, t=4.40）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# low_vol_20d 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `low_vol_20d`（= `factor/low_vol_20d.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 候选（强：IC 0.0696, t=4.40） |
| 标签 | classic_seed, low_vol, strong |
| 创建 | 2026-08-18（经典因子种子扩充） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

20 日收益波动率取负（低波动溢价）——低波动股票预期收益更高。

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
name: low_vol_20d
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
  signal = -ts_std_dev(returns(close), 20)
```

## 4. 验证结果

> 数据快照自 `results/low_vol_20d/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0696 |
| t 值 | 4.40 |
| IR | 0.329 |
| 近 26 周 mean / t | 0.0761 / 1.56 |
| PearsonIC mean | 0.0227（t=1.73） |

| 项 | 值 |
|----|----|
| spread | 0.00344 |
| D1 / D10 | 0.00214 / -0.00130 |

### 判定

**t=4.40 强显著、IR 0.329 优秀、近 26 周 t=1.56 近期仍有效**——低波动溢价
确认；与反转家族正交的新维度强种子。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`low_downside_vol_20d` | 批次4轮13：总波动→下行波动，见 [`low_downside_vol_20d.md`](low_downside_vol_20d.md) | 0.0511 | 3.20 | **无效**：总波动更优（近 26 周亮点） |
| 2026-08-18 | `low_vol_20d`（初始） | 经典种子扩充 | 0.0696 | 4.40 | 候选（强：IC 0.0696, t=4.40） |

## 6. 风险与备注

- **正交种子价值**：与反转家族低相关（预期）——挖因子新种子池成员。
- 缺失率 0.0723。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
