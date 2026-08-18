---
xname: turnover_level
formula: |
  signal = turnover
tags: [classic_seed, turnover, strong, recent_alive]
params: {}
status: 候选（强：IC 0.0719, t=5.11, 近 26 周 t=1.75）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# turnover_level 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `turnover_level`（= `factor/turnover_level.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强：IC 0.0719, t=5.11, 近 26 周 t=1.75） |
| 标签 | classic_seed, turnover, strong, recent_alive |
| 创建 | 2026-08-18（经典因子种子扩充） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

换手率水平——高换手（投机活跃）股票预期收益低。

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
name: turnover_level
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
  signal = turnover
```

## 4. 验证结果

> 数据快照自 `results/turnover_level/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 182 |
| 平均股票数 | 4887 |
| 信号缺失率 | 0.0492 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0719 |
| t 值 | 5.11 |
| IR | 0.379 |
| 近 26 周 mean / t | 0.0786 / 1.75 |
| PearsonIC mean | -0.0521（t=-5.04） |

| 项 | 值 |
|----|----|
| spread | 0.00601 |
| D1 / D10 | 0.00229 / -0.00371 |

### 判定

**IC 0.0719 接近全库纪录（0.0744）、t=5.11 强显著、IR 0.379 优秀、
近 26 周 t=1.75（近期最强之一）**——纯换手率水平即强因子
（投机维度直接表达）。
结论：**候选（强）**——turnover_level 为经典种子中表现最佳，
可作反转家族外的最强新维度。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`turnover_accel` | 批次4轮11：T1 水平→变化（加速比），见 [`turnover_accel.md`](turnover_accel.md) | 0.0382 | 5.52 | 候选：事件维度独立显著 |
| 2026-08-18 | `turnover_level`（初始） | 经典种子扩充 | 0.0719 | 5.11 | 候选（强：IC 0.0719, t=5.11, 近 26 周 t=1.75） |

## 6. 风险与备注


- 缺失率 0.0492。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
