---
xname: reversal_20d_nowin
formula: |
  signal = ts_mean(close, 20) / ts_delay(close, 20) - 1   # process: [standardize()]
tags: [mine_r6, reversal, processing, winsorize, equivalent]
params: {}
status: 无效（与 winsorize 版等价）
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# reversal_20d_nowin 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_nowin`（= `factor/reversal_20d_nowin.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 无效——与 winsorize 版完全等价（秩次评估对 0.99 截断不敏感）；确认性对照 |
| 标签 | mine_r6, reversal, processing, winsorize, equivalent |
| 创建 | 2026-08-17（挖因子批次 2 轮次 6，种子 `reversal_20d`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `reversal_20d` 的隐含假设 (H8) winsorize(0.99) 压制 20 日动量极值
（妖股视为噪声）。反转逻辑下极端涨幅恰是超调最充分处——检验"妖股极值是否
携带信息"：移除 winsorize、保留 standardize。

**核心逻辑**：20 日反转，信号处理只做横截面标准化（极值保留）。

## 3. 参数与实现

### 处理链

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2023-01-01 ~ 2026-07-31
process: [standardize()]（移除 winsorize——变异点）
target: forward_return_5d
adjustment: qfq
```

### 实现（YAML 全文）

```yaml
name: reversal_20d_nowin
category: custom
direction: -1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2023-01-01"
  end: "2026-07-31"
process:
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_delay
  signal = ts_mean(close, 20) / ts_delay(close, 20) - 1
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_nowin/summary.json`（2026-08-17）。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 复权 | qfq |
| 信号缺失率 | 7.23% |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0409 |
| t 值 | 3.47 |
| IR | 0.260 |
| 近 26 周 mean | 0.0018 |
| 近 26 周 t | 0.05 |
| PearsonIC mean（原始信号） | -0.0197（t=-1.93） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00363 |
| 单调性 | false |
| D1 mean_ret | 0.00267 |
| D10 mean_ret | -0.00096 |

### 判定

- 与 winsorize 版 `reversal_20d` **完全等价**：IC 0.0409、t 3.47、IR 0.260、
  spread 0.00363（0.00362）——逐位相同。
- 结论：**无效（等价确认）**——0.99 分位截断只影响 ~1% 尾部值的具体幅度，
  秩次评估（RankIC/分层）对并列截断不敏感。处理链 winsorize 对结果无影响。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`reversal_20d_ranknorm` | 批次3轮21：P3 csranknorm，见 [`reversal_20d_ranknorm.md`](reversal_20d_ranknorm.md) | 0.0409 | 3.47 | **无效**：分布形态无关（等价） |
| 2026-08-18 | 衍生：`reversal_20d_nowin_fill0` | 批次3轮12：P3 缺失填充 fillna(0)，见 [`reversal_20d_nowin_fill0.md`](reversal_20d_nowin_fill0.md) | 0.0401 | 3.48 | **无效**：0 值聚集破坏分层 |
| 2026-08-17 | `reversal_20d_nowin`（初始） | 挖因子轮 6：H8 移除 winsorize | 0.0409 | 3.47 | 无效：与 winsorize 版完全等价 |

## 6. 风险与备注

- **确认价值**：处理链（winsorize 截断）不改变秩次评估结果——
  与轮 5（幅度函数无信息）互为印证：**只有改变秩次结构的手段
  （条件化/口径）才影响评估**。
- 种子 [`reversal_20d.md`](reversal_20d.md) 为 20 日反转基准。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
