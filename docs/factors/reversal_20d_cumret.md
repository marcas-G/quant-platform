---
xname: reversal_20d_cumret
formula: |
  signal = ts_sum(returns(close), 20)   # 20 日累计收益（无路径平均）
tags: [mine_b3r18, reversal, cumret, family_best, new_baseline]
params: {}
status: 候选（强候选：IC 0.0503 突破优秀线）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_cumret 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_cumret`（= `factor/reversal_20d_cumret.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强候选：IC 0.0503、t=4.17、IR 0.31——反转家族新基准） |
| 标签 | mine_b3r18, reversal, cumret, family_best, new_baseline |
| 创建 | 2026-08-18（批次 3 轮次 18，种子 `reversal_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：种子 `reversal_20d` 的假设 (R2) MA 锚（平均价/20 日前）是唯一
动量定义。检验第三个动量定义：**20 日累计收益**（`ts_sum(returns, 20)`，
日收益求和，无路径平均）。单点版（near5）与趋势剥离（net60）已证伪，
累计收益版未测。

**核心逻辑**：20 日日收益累计（标准动量定义）× 反转方向——
无 MA 路径平均的纯收益信号。

**数学表达**：

```
signal = sum of returns(close) over t-19..t     （returns = close/close[t-1]-1）
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
name: reversal_20d_cumret
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
  from polars_ta.prefix.wq import ts_sum
  signal = ts_sum(returns(close), 20)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_cumret/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0503（**突破 0.05 优秀线**） |
| t 值 | 4.17 |
| IR | 0.312（>0.3 优秀） |
| 近 26 周 mean / t | -0.0057 / -0.18 |
| PearsonIC mean | -0.0215（t=-1.93） |

| 项 | 值 |
|----|----|
| spread | 0.00422（0.42%/周） |
| D1 / D10 | 0.00225 / -0.00197 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- **IC 0.0503 > 0.05 优秀线（家族首次突破）**；t=4.17 强显著；IR 0.31 优秀；
  spread 0.42%/周 > 0.2% 关注线。
- vs 种子（MA 锚）：IC +23%、t 3.47→4.17、IR 0.26→0.31、spread +17%。
- **R2 强验证**：MA 锚的路径平均（中间价格水平）稀释反转信号；
  累计收益（日收益求和）更纯。
- 近 26 周 t=-0.18（与家族一致衰减）。
- 结论：**候选（强候选）——20 日反转家族新基准**；
  后续条件化/口径变异应以本因子为 base。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_cumret`（初始） | 批次 3 轮 18：R2 累计收益动量 | 0.0503 | 4.17 | **强候选**：IC 突破优秀线，家族新基准 |

## 6. 风险与备注

- **新基准**：后续反转家族变异（换手率条件化/量能确认/vwap 口径）应叠加在
  cumret 上重测（原变异均基于 MA 锚）。
- **近期衰减**：近 26 周 t=-0.18，与 20 日反转家族一致。
- 审核过程：subagent 实测抓到算子签名错误（returns 需裸名引用、ts_sum
  而非 ts_cum_sum）——修复后生效。
- 种子 [`reversal_20d.md`](reversal_20d.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
