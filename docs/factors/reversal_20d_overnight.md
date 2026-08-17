---
xname: reversal_20d_overnight
formula: |
  signal = ts_sum(open/ts_delay(close,1) - 1, 20)   # 20 日累计隔夜收益
tags: [mine_b3r26, reversal, overnight, momentum_continuation, split_complete]
params: {}
status: 无效（隔夜是延续方向——拆分图景补全）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_overnight 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_overnight`（= `factor/reversal_20d_overnight.yaml`） |
| 类别 | custom |
| 方向 | `-1`（与日内版同向对照） |
| 状态 | 无效——隔夜成分是延续方向（反转方向亏损） |
| 标签 | mine_b3r26, reversal, overnight, momentum_continuation, split_complete |
| 创建 | 2026-08-18（批次 3 轮次 26，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：轮 25 日内成分纪录（IC 0.0591）后，隔夜成分（open/close[t-1]）
方向补全——隔夜跳空是噪声、延续、还是也反转？

**数学表达**：

```
signal = Σ (open/close[t-1] - 1) over 20d
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
name: reversal_20d_overnight
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
  from polars_ta.prefix.wq import ts_sum, ts_delay
  signal = ts_sum(open/ts_delay(close, 1) - 1, 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_overnight/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | -0.0223（负 = 反转方向亏损） |
| t 值 | -4.06 |
| IR | -0.304 |
| 近 26 周 mean / t | -0.0288 / -1.94 |

| 项 | 值 |
|----|----|
| spread | -0.00316（负值 = 档位反向） |
| D1 / D10 | -0.00100 / 0.00216 |

### 判定

- **隔夜成分显著延续/动量方向**：反转方向下 IC=-0.022（t=-4.06）——
  高隔夜跳空股未来收益继续高。
- **日内/隔夜拆分完整图景**：

  | 成分 | 方向 | IC（方向调整后） |
  |------|------|------|
  | 日内（close/open） | 反转 | +0.059（纪录） |
  | 隔夜（open/close[t-1]） | 延续 | -0.022 |
  | 混合（cumret） | 反转（被稀释） | +0.050 |

- 结论：**无效（图景补全）**——反转只存在于日内成分；隔夜为反向的
  延续成分。混合累计收益被隔夜稀释（解释 cumret 0.0503 < 日内 0.0591）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_overnight`（初始） | 批次 3 轮 26：O2 隔夜成分 | -0.0223 | -4.06 | 无效：隔夜延续，拆分图景补全 |

## 6. 风险与备注

- **图景结论**：日内反转 + 隔夜延续（A 股散户日内交易模式）；
  可交易信号应纯日内（`reversal_20d_intraday`）。
- 姊妹因子 [`reversal_20d_intraday.md`](reversal_20d_intraday.md)（纪录）；
  基准 [`reversal_20d_cumret.md`](reversal_20d_cumret.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
