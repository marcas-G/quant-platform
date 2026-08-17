---
xname: momentum_20d_turnrank_extreme
formula: |
  signal = mom20 * mask(cs_rank(turnover) > 0.8)
tags: [mine_b4r1, reversal, turnover_extreme, strong]
params: {}
status: 候选（强候选：t/IR 近翻倍）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# momentum_20d_turnrank_extreme 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `momentum_20d_turnrank_extreme`（= `factor/momentum_20d_turnrank_extreme.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 候选（强候选：t=6.51、IR=0.488、spread 0.76%/周） |
| 标签 | mine_b4r1, reversal, turnover_extreme, strong |
| 创建 | 2026-08-18（批次 4 轮次 1，种子 `momentum_20d_turnrank_lowturn`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：低换手方向证伪后，检验"信息集中在极端高换手区"：
条件化权重改为 top 20% 高换手硬掩码（sign 算术实现，if_else 不在白名单）。

**数学表达**：

```
signal = mom20 × 1{cs_rank(turnover) > 0.8}
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
name: momentum_20d_turnrank_extreme
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
  from polars_ta.prefix.wq import ts_mean, ts_delay, cs_rank
  _mom = ts_mean(close, 20) / ts_delay(close, 20) - 1
  _w = sign(sign(cs_rank(turnover) - 0.8) + 1) / 2
  signal = _mom * _w
```

## 4. 验证结果

> 数据快照自 `results/momentum_20d_turnrank_extreme/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |
| 信号缺失率 | 0.0723 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0448 |
| t 值 | 6.51 |
| IR | 0.488 |
| 近 26 周 mean / t | 0.0044 / 0.23 |
| PearsonIC mean | -0.0290（t=-3.57） |

| 项 | 值 |
|----|----|
| spread | 0.00760（0.76%/周） |
| D1 / D10 | 0.00347 / -0.00413（掩码后 0 值聚集，档位组数 6） |

### 判定

- vs turnrank（线性条件化）：IC +7%（0.0419→0.0448）、**t 3.37→6.51 近翻倍**、
  **IR 0.255→0.488**、**spread +62%**——**极端区掩码大幅提升稳定性与档位区分**。
- 结论：**候选（强候选）**——投机反转信息集中在 top 20% 高换手极端区；
  硬掩码优于线性权重。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `momentum_20d_turnrank_extreme`（初始） | 批次 4 轮 1：L4 极端区掩码 | 0.0448 | 6.51 | **强候选** |

## 6. 风险与备注

- **极端区结论**：换手率条件化信息集中在 top 20% 极端区——线性权重被稀释；
  硬掩码为更优表达（可作组合维度替换）。
- **掩码代价**：80% 股票信号恒 0（分层聚集）——实盘组合需注意信号稀疏。
- 种子 [`momentum_20d_turnrank_lowturn.md`](momentum_20d_turnrank_lowturn.md)。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
