---
xname: reversal_20d_pricevolcorr60
formula: |
  signal = ts_corr(returns(close), ts_delta(volume, 1), 60)
tags: [mine_b3r34, reversal, price_vol_corr60, recent_strong]
params: {}
status: 无效（全期略降；近 26 周亮点）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_pricevolcorr60 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_pricevolcorr60`（= `factor/reversal_20d_pricevolcorr60.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——corr 20 日是谱峰；60 日近期更强 |
| 标签 | mine_b3r34, reversal, price_vol_corr60, recent_strong |
| 创建 | 2026-08-18（批次 3 轮次 34，种子 `vol_run_energy_rl120_turn`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量价相关（结构维度）的窗口谱——长窗口（60 日）结构是否更稳。

**数学表达**：

```
signal = corr(returns(close), Δvolume, 60d)
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
name: reversal_20d_pricevolcorr60
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
  from polars_ta.prefix.wq import ts_corr, ts_delta
  signal = ts_corr(returns(close), ts_delta(volume, 1), 60)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_pricevolcorr60/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 170 |
| 平均股票数 | 4868 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0382 |
| t 值 | 5.34 |
| IR | 0.410 |
| 近 26 周 mean / t | 0.0329 / 1.81（**近期强**） |
| PearsonIC mean | -0.0100（t=-1.71） |

| 项 | 值 |
|----|----|
| spread | 0.00213 |
| D1 / D10 | 0.00310 / 0.00096 |

### 判定

- vs corr20（IR 纪录）：IC 0.0382（0.0425，-10%）、t 5.34（6.36）、
  IR 0.410（0.477）——全期略劣（20 日是谱峰）。
- **近 26 周 t=1.81**（corr20 的 1.00 更高）——长窗口结构近期更有效。
- 结论：**无效（全期劣化）**——corr 20 日保持；60 日作为近期观察项。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_pricevolcorr60`（初始） | 批次 3 轮 34：W2 corr 60 日 | 0.0382 | 5.34 | 无效：20 日是峰；近 26 周亮点 |

## 6. 风险与备注

- **窗口结论**：corr 谱峰 20 日；60 日作为近期环境（2026）的备选观察。
- 基准 [`reversal_20d_pricevolcorr.md`](reversal_20d_pricevolcorr.md)（IR 纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
