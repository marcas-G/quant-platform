---
xname: rsi_oversold_14
formula: |
  signal = RSI_ratio   # direction=1（超卖方向）
tags: [mine_b4r19, rsi, oversold, symmetric]
params: {}
status: 无效（RSI 完全对称——超买方向唯一有效）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# rsi_oversold_14 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `rsi_oversold_14`（= `factor/rsi_oversold_14.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 无效——RSI 完全对称（无超卖反弹效应） |
| 标签 | mine_b4r19, rsi, oversold, symmetric |
| 创建 | 2026-08-18（批次 4 轮次 19，种子 `rsi_reversal_14`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**隐含假设深挖**：RSI 超买/超卖对称——种子只测超买（direction=-1）；
检验超卖反弹（RSI 低 → 反弹）非对称性。

**数学表达**：

```
signal = RSI_ratio（同种子公式）   direction=1
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
name: rsi_oversold_14
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
  from polars_ta.prefix.wq import ts_delta, ts_mean
  _d = ts_delta(close, 1)
  signal = ts_mean((_d + abs(_d)) / 2, 14) / (ts_mean((abs(_d) - _d) / 2, 14) + 1e-6)
```

## 4. 验证结果

> 数据快照自 `results/rsi_oversold_14/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 179 |
| 平均股票数 | 4883 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0375 |
| t 值 | -3.56 |
| IR | -0.266 |
| 近 26 周 mean / t | 0.0005 / 0.02 |

| 项 | 值 |
|----|----|
| spread | -0.00184（负值） |

### 判定

- vs rsi_reversal（超买）：**完全镜像**（IC -0.0375 vs +0.0375、t -3.56 vs +3.56、
  IR -0.266 vs +0.266）——**RSI 信息完全对称**。
- 结论：**无效（对称确认）**——超卖方向无独立反弹效应；
  RSI 低 = 弱势延续（非超卖反弹）；超买反转方向唯一有效。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `rsi_oversold_14`（初始） | 批次 4 轮 19：超卖方向 | -0.0375 | -3.56 | 无效：对称确认 |

## 6. 风险与备注

- **RSI 对称性**：超买反转 = 超卖弱势的镜像——技术反转方向已定。
- 种子 [`rsi_reversal_14.md`](rsi_reversal_14.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
