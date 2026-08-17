---
xname: momentum_20d_vwap
formula: |
  signal = ts_mean(amount/volume, 20) / ts_delay(amount/volume, 20) - 1
tags: [mine_r2, reversal, vwap_condition, price_manipulation]
params: {}
status: 观察中
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# momentum_20d_vwap 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_vwap`（= `factor/momentum_20d_vwap.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 观察中（IC 与 close 口径持平、spread +78%；近 26 周衰减） |
| 标签 | mine_r2, reversal, vwap_condition, price_manipulation |
| 创建 | 2026-08-17（挖因子批次 2 轮次 2，种子 `momentum_20d`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `momentum_20d` 的隐含假设 (H3) close 是无偏价格——A 股收盘价
受尾盘操纵/收盘竞价扰动（拉尾盘、做收盘价）。本因子变异 H3：价格口径改为
**真实日频 VWAP = amount/volume**（成交量加权真值，尾盘单笔操纵影响被摊薄）。
平台 vwap 薄封装为累计式（自上市累计），不适用 20 日短期口径，故直算。

**核心逻辑**：20 日 VWAP 均值动量（反转方向）× 尾盘操纵污染免疫。

**数学表达**：

```
vwap    = amount / volume
signal  = MA(vwap, 20) / vwap[t-20] - 1
```

**输入数据**：`amount`、`volume`（daily 表字段，自动加载）。

## 3. 参数与实现

### 参数表

无参数（固定 20 日窗口）。

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
name: momentum_20d_vwap
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
  _vwap = amount / volume
  signal = ts_mean(_vwap, 20) / ts_delay(_vwap, 20) - 1
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_vwap/summary.json`（2026-08-17）。

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
| RankIC mean（方向调整后） | 0.0390 |
| t 值 | 3.45 |
| IR | 0.259 |
| 近 26 周 mean | -0.0071 |
| 近 26 周 t | -0.30 |
| PearsonIC mean（原始信号） | nan（t=0.00） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00646（0.65%/周） |
| 单调性 | false |
| D1 mean_ret | 0.00355 |
| D10 mean_ret | -0.00291 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- t=3.45 显著；IR 0.26；spread 0.65%/周，**较 close 口径 reversal_20d（0.36%/周）
  提升 78%**（D10 档更负：-0.0029 vs -0.0010）——VWAP 口径的档位区分更强。
- IC 0.039 与 close 版 0.041 基本持平：口径精确化未提升整体预测力，
  但显著增强了横截面区分度。
- 近 26 周衰减（t=-0.30）与 20 日反转家族一致。
- 结论：**观察中**——尾盘操纵污染假设（H3'）得到部分支持（档位区分增强）。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`momentum_20d_vwap_turn` | 批次3轮9：V3 换手率条件化叠加，见 [`momentum_20d_vwap_turn.md`](momentum_20d_vwap_turn.md) | 0.0411 | 3.41 | **候选**：spread 0.76%/周 全库最高 |
| 2026-08-17 | `momentum_20d_vwap`（初始） | 挖因子轮 2：H3 close→日频 VWAP + H9 方向→反转 | 0.0390 | 3.45 | 全期显著；spread +78%；近 26 周衰减 |

## 6. 风险与备注

- **近期失效**：近 26 周 t=-0.30，与 20 日反转家族同步衰减。
- **口径对比**：与 [`reversal_20d.md`](reversal_20d.md)（close 口径）同结构，
  差异仅价格口径；与 [`momentum_20d_turnrank.md`](momentum_20d_turnrank.md)
  （换手率条件化）正交——两者可组合（VWAP × 换手率条件化）待迭代。
- **amount 口径**：amount 为全天成交额，VWAP 含尾盘竞价成交（竞价量少权重小），
  污染已大幅摊薄但未完全消除。
- 种子 [`momentum_20d.md`](momentum_20d.md) 为方向对照（已废弃）。变异记录
  `results/_mine_round_2.md`。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
