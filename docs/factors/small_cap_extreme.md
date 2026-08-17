---
xname: small_cap_extreme
formula: |
  signal = -log(circ_mv) * mask(cs_rank(circ_mv) < 0.2)
tags: [mine_b4r10, size, small_cap, extreme, inverted]
params: {}
status: 无效（极端小盘负溢价——方向反转）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# small_cap_extreme 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `small_cap_extreme`（= `factor/small_cap_extreme.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效——极端小盘负溢价（方向反转） |
| 标签 | mine_b4r10, size, small_cap, extreme, inverted |
| 创建 | 2026-08-18（批次 4 轮次 10，种子 `small_cap`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：全样本小市值无效（t=1.53）——检验溢价是否集中在极端小盘（bottom 20%）。

**数学表达**：

```
signal = -log(circ_mv) × 1{cs_rank(circ_mv) < 0.2}
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
name: small_cap_extreme
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
  from polars_ta.prefix.wq import cs_rank
  _sig = -log(circ_mv)
  _w = sign(sign(0.2 - cs_rank(circ_mv)) + 1) / 2
  signal = _sig * _w
```

## 4. 验证结果

> 数据快照自 `results/small_cap_extreme/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 4887 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0213 |
| t 值 | -2.29 |
| IR | -0.170 |
| 近 26 周 mean / t | -0.0064 / -0.30 |

| 项 | 值 |
|----|----|
| spread | -0.00199（负值） |
| 分层 | 组数 3（掩码聚集） |

### 判定

- vs small_cap（全样本）：**IC 0.0219 → -0.0213 方向反转**（t=-2.29 显著负）——
  **极端小盘（bottom 20%）是负溢价**：2023-2026 环境（微盘流动性危机、
  退市新规）下极端小盘持续跑输；全样本弱正值来自中盘。
- 结论：**无效（方向反转）**——小市值溢价在极端小盘不成立（反向）；
  规模维度当前环境整体弱（批次 3 small_cap 已记录）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `small_cap_extreme`（初始） | 批次 4 轮 10：S2 极端小盘聚焦 | -0.0213 | -2.29 | 无效：极端小盘负溢价 |

## 6. 风险与备注

- **规模维度结论**：当前环境小市值溢价不成立（全样本弱、极端小盘反向）——
  规模种子保留但非有效方向。
- 种子 [`small_cap.md`](small_cap.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
