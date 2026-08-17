---
xname: reversal_20d_skew
formula: |
  signal = ts_skewness(returns(close), 20)
tags: [mine_b3r50, reversal, skew, lottery_preference]
params: {}
status: 候选（显著：t=4.29/IR=0.322）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_skew 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_skew`（= `factor/reversal_20d_skew.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（显著：t=4.29/IR=0.322） |
| 标签 | mine_b3r50, reversal, skew, lottery_preference |
| 创建 | 2026-08-18（批次 3 轮次 50，种子 `momentum_20d_net60`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：收益偏度维度（ts_skewness 首次使用）——彩票偏好假设
（右偏 = 彩票股 → 未来收益低）。

**数学表达**：

```
signal = skewness(returns(close), 20d)
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
name: reversal_20d_skew
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
  from polars_ta.prefix.wq import ts_skewness
  signal = ts_skewness(returns(close), 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_skew/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0245 |
| t 值 | 4.29 |
| IR | 0.322 |
| 近 26 周 mean / t | 0.0079 / 0.51 |
| PearsonIC mean | -0.0064（t=-1.46） |

| 项 | 值 |
|----|----|
| spread | 0.00124 |
| D1 / D10 | 0.00242 / 0.00118 |

### 判定

- IC 0.0245（t=4.29 强显著、IR 0.322 优秀）——**彩票偏好确认**
  （右偏股未来收益低）。
- 信息量中等（低于收益/日内维度）——偏度为有效但次要维度；
  可与四维组合做秩次加法（第五维候选）。
- 结论：**候选**——收益偏度维度独立有效。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_skew`（初始） | 批次 3 轮 50：S2 收益偏度 | 0.0245 | 4.29 | 候选：彩票偏好确认 |

## 6. 风险与备注

- **维度扩展**：skew 与 turn（投机）部分相关但独立显著——
  可作为四维组合候选第五维（五维已证饱和——低优先）。
- 种子 [`momentum_20d_net60.md`](momentum_20d_net60.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
