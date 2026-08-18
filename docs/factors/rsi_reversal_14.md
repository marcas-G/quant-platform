---
xname: rsi_reversal_14
formula: |
  from polars_ta.prefix.wq import ts_delta, ts_mean
  _d = ts_delta(close, 1)
  signal = ts_mean((_d + abs(_d)) / 2, 14) / (ts_mean((abs(_d) - _d) / 2, 14) + 1e-6)
tags: [classic_seed, rsi, technical]
params: {}
status: 候选（t=3.56 显著）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# rsi_reversal_14 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `rsi_reversal_14`（= `factor/rsi_reversal_14.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（t=3.56 显著） |
| 标签 | classic_seed, rsi, technical |
| 创建 | 2026-08-18（经典因子种子扩充） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

14 日相对强弱比（手动 RSI 核心：平均涨幅/平均跌幅）——超买股票预期回落。

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
name: rsi_reversal_14
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
  from polars_ta.prefix.wq import ts_delta, ts_mean
  _d = ts_delta(close, 1)
  signal = ts_mean((_d + abs(_d)) / 2, 14) / (ts_mean((abs(_d) - _d) / 2, 14) + 1e-6)
```

## 4. 验证结果

> 数据快照自 `results/rsi_reversal_14/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 179 |
| 平均股票数 | 4883 |
| 信号缺失率 | 0.0654 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0375 |
| t 值 | 3.56 |
| IR | 0.266 |
| 近 26 周 mean / t | -0.0005 / -0.02 |
| PearsonIC mean | -0.0130（t=-1.56） |

| 项 | 值 |
|----|----|
| spread | 0.00191 |
| D1 / D10 | 0.00233 / 0.00042 |

### 判定

t=3.56 显著、IR 0.266；近 26 周 t=-0.02（近期失效）。
结论：**候选**——RSI 超买超卖全期有效、近期走弱。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`rsi_oversold_14` | 批次4轮19：超卖方向，见 [`rsi_oversold_14.md`](rsi_oversold_14.md) | -0.0375 | -3.56 | **无效**：RSI 完全对称 |
| 2026-08-18 | `rsi_reversal_14`（初始） | 经典种子扩充 | 0.0375 | 3.56 | 候选（t=3.56 显著） |

## 6. 风险与备注

- **平台记录**：tdx/ta 的 ts_RSI 在平台 float32 环境崩溃（SchemaMismatch：
  rolling list 构建 dtype 混合）——本因子用手动相对强弱比实现（等价语义）。
- 缺失率 0.0654。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
