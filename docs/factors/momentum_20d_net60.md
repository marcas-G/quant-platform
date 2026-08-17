---
xname: momentum_20d_net60
formula: |
  signal = (MA(close,20)/close[t-20]-1) - (MA(close,60)/close[t-60]-1)
tags: [mine_r8, reversal, trend_strip, falsified]
params: {}
status: 无效（证伪 H1' 趋势剥离）
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# momentum_20d_net60 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_net60`（= `factor/momentum_20d_net60.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 无效——证伪"20 日反转 = 超调 − 趋势"；保留作对照 |
| 标签 | mine_r8, reversal, trend_strip, falsified |
| 创建 | 2026-08-17（挖因子批次 2 轮次 8，种子 `momentum_20d`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `momentum_20d` 的隐含假设 (H1) 20 日收益全为反转信号。
检验"20 日收益 = 近端超调 + 中期趋势成分，趋势应剥离"：
`_m20 - _m60`（20 日超调减去 60 日趋势）。

**核心逻辑**：净超调 = 20 日 MA 收益 − 60 日 MA 收益（趋势成分剥离后反转）。

**数学表达**：

```
signal = (MA(close,20)/close[t-20] - 1) - (MA(close,60)/close[t-60] - 1)
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
name: momentum_20d_net60
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
  from polars_ta.prefix.wq import ts_mean, ts_delay
  _m20 = ts_mean(close, 20) / ts_delay(close, 20) - 1
  _m60 = ts_mean(close, 60) / ts_delay(close, 60) - 1
  signal = _m20 - _m60
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_net60/summary.json`（2026-08-17）。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 170 |
| 平均股票数 | 4881 |
| 复权 | qfq |
| 信号缺失率 | 7.23% |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0060 |
| t 值 | -0.52 |
| IR | -0.040 |
| 近 26 周 mean | -0.0370 |
| 近 26 周 t | -1.28 |
| PearsonIC mean（原始信号） | 0.0071（t=0.74） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | -0.00058（负值 = 档位反向） |
| 单调性 | false |
| D1 mean_ret | 0.00132 |
| D10 mean_ret | 0.00190 |

### 判定

- **完全失败**：方向调整后 IC=-0.006（t=-0.52）、IR=-0.04、spread 负
  （D1 < D10）——反转方向下档位反向。
- 结论：**无效（H1' 证伪）**——20 日反转的预测力不在"超调−趋势"差上；
  减去 60 日趋势破坏了反转信号本身（20 日反转可能与 60 日趋势同源，
  简单差分破坏秩次结构）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`momentum_20d_downtrend` | 批次3轮4：趋势条件化掩码，见 [`momentum_20d_downtrend.md`](momentum_20d_downtrend.md) | 0.0177 | 2.11 | **无效**：掩码损失一半样本 |
| 2026-08-17 | `momentum_20d_net60`（初始） | 挖因子轮 8：H1 趋势剥离 `_m20 - _m60` | -0.0060 | -0.52 | 无效：反转方向下档位反向 |

## 6. 风险与备注

- **证伪价值**：多窗口差分（趋势剥离）方向排除——反转是 20 日单一尺度的
  整体现象；未来迭代不要在"多窗口差分"方向重复探索。
- 种子 [`momentum_20d.md`](momentum_20d.md) 为方向对照；反转基准
  [`reversal_20d.md`](reversal_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
