---
xname: quality_defensive
formula: |
  signal = cs_rank(dv_ratio) + cs_rank(-ts_std_dev(returns,20))
tags: [mine_b4r17, defensive, dividend, low_vol, complementary]
params: {}
status: 候选（防御组合超股息 +123%）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# quality_defensive 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `quality_defensive`（= `factor/quality_defensive.yaml`） |
| 类别 | custom |
| 方向 | `1` |
| 状态 | 候选（防御组合：现金流×风险维度互补） |
| 标签 | mine_b4r17, defensive, dividend, low_vol, complementary |
| 创建 | 2026-08-18（批次 4 轮次 17，种子 `dividend_yield`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**隐含假设深挖**：股息率的隐含属性 = **防御性**（稳定现金回报）——防御是
多维的（现金流防御 ⊕ 风险防御），股息单维 spread 负（防御股弹性差）
说明单独捕捉的是防御特征。

**数学表达**：

```
signal = cs_rank(dv_ratio) + cs_rank(-ts_std_dev(returns, 20))
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
name: quality_defensive
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
  from polars_ta.prefix.wq import ts_std_dev, cs_rank
  signal = cs_rank(dv_ratio) + cs_rank(-ts_std_dev(returns(close), 20))
```

## 4. 验证结果

> 数据快照自 `results/quality_defensive/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4420 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0580 |
| t 值 | 3.65 |
| IR | 0.274 |
| 近 26 周 mean / t | 0.0716 / 1.31 |
| PearsonIC mean | 0.0094（t=0.70） |

| 项 | 值 |
|----|----|
| spread | 0.00163 |
| D1 / D10 | 0.00254 / 0.00091 |

### 判定

- vs 股息（单维）：IC **+123%**（0.0260→0.0580）、t +58%——低波动补充
  股息的风险维度。
- vs 低波动：IC 居中（-17%）——股息补充低波动的现金流维度。
- **两防御维度互补**（现金流 × 风险）；近 26 周 1.31 近期仍有效。
- 结论：**候选**——防御组合为股息单维的显著升级。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `quality_defensive`（初始） | 批次 4 轮 17：防御组合 | 0.0580 | 3.65 | 候选：组合互补 |

## 6. 风险与备注

- **防御维度**：股息（现金流）与低波动（风险）正交互补——
  防御风格因子组合方向。
- 种子 [`dividend_yield.md`](dividend_yield.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
