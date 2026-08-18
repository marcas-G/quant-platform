---
xname: volume_ratio_directional
formula: |
  signal = volume_ratio * sign(returns(close))
tags: [mine_b4r18, volume_ratio, directional, falsified]
params: {}
status: 无效（定向量比无增益——放量方向被覆盖）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# volume_ratio_directional 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `volume_ratio_directional`（= `factor/volume_ratio_directional.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——定向量比无增益 |
| 标签 | mine_b4r18, volume_ratio, directional, falsified |
| 创建 | 2026-08-18（批次 4 轮次 18，种子 `volume_ratio`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**隐含假设深挖**：量比只有强度没有方向——检验放量方向（追涨 vs 恐慌）
是否携带独立信息。

**数学表达**：

```
signal = volume_ratio × sign(returns)
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
name: volume_ratio_directional
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
  signal = volume_ratio * sign(returns(close))
```

## 4. 验证结果

> 数据快照自 `results/volume_ratio_directional/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 4884 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0169 |
| t 值 | 2.01 |
| IR | 0.149 |
| 近 26 周 mean / t | 0.0036 / 0.16 |

| 项 | 值 |
|----|----|
| spread | 0.00036 |
| D1 / D10 | 0.00107 / 0.00071 |

### 判定

- vs volume_ratio：IC 0.0169（0.0189，-11%）、t 2.01（3.14）、IR 0.149（0.233）——
  **方向加权无增益**：量比放量事件信息**方向无关**（放量方向已被
  反转/日内家族覆盖）。
- 与 netflow（方向加权有效）对比：netflow 用绝对金额（方向信息独立），
  量比×sign 的方向已冗余。
- 结论：**无效（H1' 否定）**——量比保持无方向表达。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `volume_ratio_directional`（初始） | 批次 4 轮 18：定向量比 | 0.0169 | 2.01 | 无效：方向无增益 |

## 6. 风险与备注

- **量比结构**：放量事件信息方向无关——量比保持强度表达。
- 种子 [`volume_ratio.md`](volume_ratio.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
