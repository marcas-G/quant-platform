---
xname: reversal_20d_corr_skew
formula: |
  signal = cs_rank(corr10) + cs_rank(skew20)
tags: [mine_b3r52, reversal, corr_skew, redundant]
params: {}
status: 无效（skew 冗余于 corr）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_corr_skew 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_corr_skew`（= `factor/reversal_20d_corr_skew.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——skew 冗余于 corr |
| 标签 | mine_b3r52, reversal, corr_skew, redundant |
| 创建 | 2026-08-18（批次 3 轮次 52，种子 `momentum_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量价结构（corr10）× 彩票偏好（skew20）秩次加法——不同信息源组合。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(skew20)
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
name: reversal_20d_corr_skew
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_skewness, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(ts_skewness(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_corr_skew/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0425 |
| t 值 | 6.45 |
| IR | 0.483 |
| 近 26 周 mean / t | 0.0149 / 0.97 |

| 项 | 值 |
|----|----|
| spread | 0.00238 |
| D1 / D10 | 0.00305 / 0.00067 |

### 判定

- vs corr10：IC 0.0425（0.0439，-3%）、IR 0.483（0.481，+0.4%）——基本持平。
- 结论：**无效（冗余确认）**——skew 信息被 corr 覆盖（量价关系异常的
  股票偏度也异常——两维度同源）；组合无增益。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_corr_skew`（初始） | 批次 3 轮 52：C3 秩次加法 | 0.0425 | 6.45 | 无效：skew 冗余于 corr |

## 6. 风险与备注

- **信息源映射**：corr 覆盖 skew（量价结构含偏度信息）——
  组合维度选择需信息源正交（corr/intraday/turn/vol 已是最优集）。
- 基准 [`reversal_20d_pricevolcorr10.md`](reversal_20d_pricevolcorr10.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
