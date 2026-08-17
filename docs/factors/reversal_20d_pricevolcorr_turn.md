---
xname: reversal_20d_pricevolcorr_turn
formula: |
  signal = ts_corr(returns(close), ts_delta(turnover, 1), 20)
tags: [mine_b3r35, reversal, price_vol_corr, proxy_equivalent]
params: {}
status: 无效（量代理等价）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_pricevolcorr_turn 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_pricevolcorr_turn`（= `factor/reversal_20d_pricevolcorr_turn.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——量代理等价（相关归一化吸收股本扰动） |
| 标签 | mine_b3r35, reversal, price_vol_corr, proxy_equivalent |
| 创建 | 2026-08-18（批次 3 轮次 35，种子 `vol_run_energy`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量价相关的量代理——volume（原始）vs turnover（无股本扰动）。

**数学表达**：

```
signal = corr(returns(close), Δturnover, 20d)
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
name: reversal_20d_pricevolcorr_turn
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
  signal = ts_corr(returns(close), ts_delta(turnover, 1), 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_pricevolcorr_turn/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0425 |
| t 值 | 6.37 |
| IR | 0.478 |
| 近 26 周 mean / t | 0.0165 / 1.00 |

| 项 | 值 |
|----|----|
| spread | 0.00297 |
| D1 / D10 | 0.00299 / 0.00002 |

### 判定

- vs corr（volume 口径）：IC 0.0425 相同、t 6.37（6.36）、IR 0.478（0.477）——
  **逐位等价**。
- 结论：**无效（等价确认）**——相关归一化（corr 标准化）吸收了
  volume/turnover 的股本结构差异；量代理对 corr 结构无影响。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_pricevolcorr_turn`（初始） | 批次 3 轮 35：V2 turnover 量代理 | 0.0425 | 6.37 | 无效：量代理等价 |

## 6. 风险与备注

- **代理等价结论**：corr 结构对量代理不敏感——后续 corr 类变异无需
  更换量口径（volume 即最优表达）。
- 基准 [`reversal_20d_pricevolcorr.md`](reversal_20d_pricevolcorr.md)（IR 纪录）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
