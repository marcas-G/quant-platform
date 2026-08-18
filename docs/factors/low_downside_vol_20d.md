---
xname: low_downside_vol_20d
formula: |
  signal = -ts_std_dev((returns - abs(returns))/2, 20)
tags: [mine_b4r13, low_vol, downside, falsified, recent_strong]
params: {}
status: 无效（总波动更优；近 26 周亮点）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# low_downside_vol_20d 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `low_downside_vol_20d`（= `factor/low_downside_vol_20d.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效——总波动更优（近 26 周亮点） |
| 标签 | mine_b4r13, low_vol, downside, falsified, recent_strong |
| 创建 | 2026-08-18（批次 4 轮次 13，种子 `low_vol_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**隐含假设深挖**：种子"总波动 = 风险"隐含"涨跌波动同等敏感"；损失厌恶下
**下行波动**才是真风险——半方差检验。

**数学表达**：

```
_neg = (r - |r|) / 2        # 负收益半部分
signal = -ts_std_dev(_neg, 20)
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
name: low_downside_vol_20d
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
  from polars_ta.prefix.wq import ts_std_dev
  _neg = (returns(close) - abs(returns(close))) / 2
  signal = -ts_std_dev(_neg, 20)
```

## 4. 验证结果

> 数据快照自 `results/low_downside_vol_20d/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0511 |
| t 值 | 3.20 |
| IR | 0.240 |
| 近 26 周 mean / t | 0.0809 / 1.84 |
| PearsonIC mean | 0.0168（t=1.33） |

| 项 | 值 |
|----|----|
| spread | 0.00258 |
| D1 / D10 | 0.00211 / -0.00047 |

### 判定

- vs low_vol（总波动）：IC -27%（0.0696→0.0511）、t 3.20（4.40）——
  **低波动异象不纯由下行风险驱动**（上行波动同样有信息，总波动更优）。
- **近 26 周 t=1.84（强）**——下行波动近期是有效风险度量。
- 结论：**无效（全期证伪）**——半方差假设不成立；
  总波动保持；近 26 周作为观察项。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `low_downside_vol_20d`（初始） | 批次 4 轮 13：总波动→下行波动 | 0.0511 | 3.20 | 无效：总波动更优 |

## 6. 风险与备注

- **波动结构结论**：低波动异象 = 总波动现象（上下行同等信息）；
  半方差方向关闭（近 26 周观察项）。
- 种子 [`low_vol_20d.md`](low_vol_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
