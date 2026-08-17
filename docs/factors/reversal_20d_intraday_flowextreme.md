---
xname: reversal_20d_intraday_flowextreme
formula: |
  signal = intraday20 * mask(cs_rank(netflow30) > 0.8)
tags: [mine_b4r8, reversal, intraday, flow_extreme, marginal]
params: {}
status: 观察中（t/IR 升、IC 降）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_intraday_flowextreme 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_intraday_flowextreme`（= `factor/reversal_20d_intraday_flowextreme.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 观察中（t/IR 升、IC 降） |
| 标签 | mine_b4r8, reversal, intraday, flow_extreme, marginal |
| 创建 | 2026-08-18（批次 4 轮次 8，种子 `reversal_20d_intraday_flow30`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：极端换手聚焦通用有效——资金流维度极端（净流入 top 20%）是否同样。

**数学表达**：

```
signal = Σ(close/open-1, 20) × 1{cs_rank(netflow30) > 0.8}
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
name: reversal_20d_intraday_flowextreme
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
  from polars_ta.prefix.wq import ts_sum, cs_rank
  _sig = ts_sum(close/open - 1, 20)
  _flow = ts_sum(amount * sign(returns(close)), 30)
  _w = sign(sign(cs_rank(_flow) - 0.8) + 1) / 2
  signal = _sig * _w
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_intraday_flowextreme/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 176 |
| 平均股票数 | 4878 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0437 |
| t 值 | 6.38 |
| IR | 0.481 |
| 近 26 周 mean / t | -0.0002 / -0.01 |

| 项 | 值 |
|----|----|
| spread | 0.00569 |
| 分层 | 组数 6（掩码 0 值聚集） |

### 判定

- vs 日内（基准）：IC -26%（0.0591→0.0437）、**t +22%（5.22→6.38）**、
  **IR +23%（0.391→0.481）**——极端资金流聚焦**稳定性换水平**。
- vs 轮 1/4/6（极端换手）：对比——换手极端是信息密区（IC 升）、
  资金流极端不是（IC 降；方向加权本身已聚焦）。
- 近 26 周 t=-0.01（近期失效）。
- 结论：**观察中（边际）**——资金流极端聚焦仅增稳定性；
  信息聚焦维度以换手率为准。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_intraday_flowextreme`（初始） | 批次 4 轮 8：F3 极端资金流聚焦 | 0.0437 | 6.38 | 观察中：稳定性换水平 |

## 6. 风险与备注

- **聚焦维度选择**：换手率是信息密区（IC+t 双升）、资金流仅稳定性——
  极端聚焦首选换手维度。
- 种子 [`reversal_20d_intraday_flow30.md`](reversal_20d_intraday_flow30.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
