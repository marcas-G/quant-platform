---
xname: volume_ratio
formula: |
  signal = volume_ratio
tags: [classic_seed, volume_ratio, technical]
params: {}
status: 候选（t=3.14 显著但弱）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# volume_ratio 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `volume_ratio`（= `factor/volume_ratio.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（t=3.14 显著但弱） |
| 标签 | classic_seed, volume_ratio, technical |
| 创建 | 2026-08-18（经典因子种子扩充） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

量比（当日成交量/过去 5 日均量）——高量比（放量）股票预期收益低。

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
name: volume_ratio
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
  signal = volume_ratio
```

## 4. 验证结果

> 数据快照自 `results/volume_ratio/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 4884 |
| 信号缺失率 | 0.0497 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0189 |
| t 值 | 3.14 |
| IR | 0.233 |
| 近 26 周 mean / t | 0.0067 / 0.51 |
| PearsonIC mean | -0.0188（t=-3.66） |

| 项 | 值 |
|----|----|
| spread | 0.00206 |
| D1 / D10 | 0.00230 / 0.00024 |

### 判定

t=3.14 显著、IR 0.233、IC 0.019 弱；近 26 周 t=0.51。
结论：**候选（弱）**——量比维度显著但信息量小（与换手率水平相关）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `volume_ratio`（初始） | 经典种子扩充 | 0.0189 | 3.14 | 候选（t=3.14 显著但弱） |

## 6. 风险与备注


- 缺失率 0.0497。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
