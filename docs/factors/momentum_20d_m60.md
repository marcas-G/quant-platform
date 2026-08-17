---
xname: momentum_20d_m60
formula: |
  signal = ts_mean(close, 60) / ts_delay(close, 60) - 1   # direction=1（动量方向对照）
tags: [mine_b3r15, momentum_60d, reversal_spectrum, control]
params: {}
status: 无效（60 日仍是反转区；方向对照）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_m60 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_m60`（= `factor/momentum_20d_m60.yaml`） |
| 类别 | custom |
| 方向 | `1`（60 日动量方向对照） |
| 状态 | 无效——60 日仍是反转区（动量方向亏损） |
| 标签 | mine_b3r15, momentum_60d, reversal_spectrum, control |
| 创建 | 2026-08-18（批次 3 轮次 15，种子 `momentum_20d_net60`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `momentum_20d_net60` 的 _m60 成分方向未单独测过。检验
60 日动量方向（direction=1，中期动量延续假设）——反转尺度上界。

**数学表达**：

```
signal = MA(close, 60) / close[t-60] - 1
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
name: momentum_20d_m60
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
  from polars_ta.prefix.wq import ts_mean, ts_delay
  signal = ts_mean(close, 60) / ts_delay(close, 60) - 1
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_m60/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 170 |
| 平均股票数 | 4868 |
| 信号缺失率 | 0.1183 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0377 |
| t 值 | -3.14 |
| IR | -0.241 |
| 近 26 周 mean / t | -0.0436 / -1.15 |
| PearsonIC mean | -0.0198（t=-1.84） |

| 项 | 值 |
|----|----|
| spread | -0.00327（负值 = 动量方向档位反向） |
| D1 / D10 | 0.00035 / 0.00362 |

### 判定

- **60 日动量方向显著亏损**：IC=-0.0377（t=-3.14）、IR=-0.241、spread 负。
- **关键发现——反转尺度谱**：20 日（-0.0409）与 60 日（-0.0377）动量方向
  均显著亏损且幅度接近——反转是 20-60 日连续谱（强度随窗口缓慢衰减），
  非孤立于 20 日。这解释 net60 证伪：两个同向反转信号的差互相抵消。
- 结论：**无效（尺度谱确认）**——动量方向在 60 日尺度仍亏损；
  反转尺度上界 >60 日（后续可测 120 日）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `momentum_20d_m60`（初始） | 批次 3 轮 15：60 日动量方向对照 | -0.0377 | -3.14 | 无效：60 日仍是反转区 |

## 6. 风险与备注

- **尺度谱结论**：反转在 20-60 日连续存在——差分/剥离类变异天然破坏
  同向信号（net60 教训），未来不做窗口差分。
- 反转方向的可交易版本 = direction=-1 的 60 日版（反转幅度略低于 20 日）。
- 种子 [`momentum_20d_net60.md`](momentum_20d_net60.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
