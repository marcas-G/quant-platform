---
xname: reversal_20d_pricevolcorr
formula: |
  signal = ts_corr(returns(close), ts_delta(volume, 1), 20)
tags: [mine_b3r32, reversal, price_vol_corr, ir_record, recent_alive]
params: {}
status: 候选（强候选：IR 0.477/t 6.36 全库纪录）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_pricevolcorr 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_pricevolcorr`（= `factor/reversal_20d_pricevolcorr.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强候选：IR 0.477/t 6.36 全库纪录） |
| 标签 | mine_b3r32, reversal, price_vol_corr, ir_record, recent_alive |
| 创建 | 2026-08-18（批次 3 轮次 32，种子 `reversal_20d_volconf`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：量价关系维度（ts_corr 首次使用）——20 日收益×Δ量滚动相关：
量价齐升（正相关=追涨）与量价背离（放量跌=恐慌）的结构差异。

**核心逻辑**：量价齐升（追涨）股票未来收益低（反转做空）——
量价结构是正交于收益幅度的新维度。

**数学表达**：

```
signal = corr(returns(close), Δvolume, 20d)
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
name: reversal_20d_pricevolcorr
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
  signal = ts_corr(returns(close), ts_delta(volume, 1), 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_pricevolcorr/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0425 |
| t 值 | 6.36（**全库纪录**） |
| IR | 0.477（**全库纪录**） |
| 近 26 周 mean / t | 0.0164 / 1.00（**近期仍有信息**） |
| PearsonIC mean | -0.0113（t=-2.10） |

| 项 | 值 |
|----|----|
| spread | 0.00297 |
| D1 / D10 | 0.00296 / -0.00000 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- **IR 0.477 / t 6.36 全库纪录**；IC 0.0425 显著；spread 0.30%/周。
- **近 26 周 t=1.00**——反转家族中近期唯一仍带信息的成员
  （家族其他成员近 26 周 t≈0 或负）。
- 结论：**候选（强候选）**——量价结构维度高稳定性、近期有效；
  与日内核心（收益幅度）正交——组合待测（后续轮次）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_pricevolcorr`（初始） | 批次 3 轮 32：C2 量价相关 | 0.0425 | 6.36 | **强候选**：IR/t 全库纪录 |

## 6. 风险与备注

- **近期有效性**：近 26 周 t=1.00——量价结构信号在 2026 年仍有效
  （收益幅度反转衰减但量价结构未衰减）。
- **组合方向**：量价相关 × 日内核心（正交维度）组合是明确待做项。
- 种子 [`reversal_20d_volconf.md`](reversal_20d_volconf.md)；基准
  [`reversal_20d_intraday.md`](reversal_20d_intraday.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
