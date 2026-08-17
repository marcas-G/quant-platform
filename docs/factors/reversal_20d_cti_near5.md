---
xname: reversal_20d_cti_near5
formula: |
  signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(intraday20) + cs_rank(near5)
tags: [mine_b3r84, reversal, cti_near5, diluted]
params: {}
status: 无效（近端弱维度稀释）
created_ts: 2026-08-18
updated_ts: 2026-08-18
---

# reversal_20d_cti_near5 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `reversal_20d_cti_near5`（= `factor/reversal_20d_cti_near5.yaml`） |
| 类别 | custom |
| 方向 | `-1` |
| 状态 | 无效——近端弱维度稀释 |
| 标签 | mine_b3r84, reversal, cti_near5, diluted |
| 创建 | 2026-08-18（批次 3 轮次 84，种子 `momentum_20d`） |
| 最近更新 | 2026-08-18 |

## 2. 逻辑

**动机**：cti 三维（IC 纪录）加第四维近端 5 日——弱维度贡献测试。

**数学表达**：

```
signal = cs_rank(corr10) + cs_rank(turn) + cs_rank(intraday20) + cs_rank(near5)
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
name: reversal_20d_cti_near5
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
  from polars_ta.prefix.wq import ts_corr, ts_delta, ts_sum, ts_delay, cs_rank
  signal = cs_rank(ts_corr(returns(close), ts_delta(volume, 1), 10)) + cs_rank(turnover) + cs_rank(ts_sum(close/open - 1, 20)) + cs_rank(close / ts_delay(close, 5) - 1)
```

## 4. 验证结果

> 数据快照自 `results/reversal_20d_cti_near5/summary.json`（2026-08-18）。

| 项 | 值 |
|----|----|
| 区间 | 2023-01-03 ~ 2026-07-31 |
| 周数（有效） | 178 |
| 平均股票数 | 4881 |

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0694 |
| t 值 | 6.71 |
| IR | 0.503 |
| 近 26 周 mean / t | 0.0320 / 1.14 |

| 项 | 值 |
|----|----|
| spread | 0.00484 |
| D1 / D10 | 0.00251 / -0.00233 |

### 判定

- vs cti 三维（IC 纪录）：IC 0.0694（0.0744，**-7%**）、t 6.71（6.99）、
  IR 0.503（0.524）——近端弱维度（t=2.44）稀释强组合。
- 结论：**无效（稀释确认）**——弱信号维度不加入强组合；
  cti 三维保持全库 IC 纪录。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | `reversal_20d_cti_near5`（初始） | 批次 3 轮 84：F3 近端四维 | 0.0694 | 6.71 | 无效：近端稀释 |

## 6. 风险与备注

- **维度加入准则**：弱信号（近端）稀释强组合——四维扩展仅加
  正交且显著维度（flow 已验证 +6%）。
- 基准 [`reversal_20d_corr_turn_intraday.md`](reversal_20d_corr_turn_intraday.md)
  （全库 IC 纪录 0.0744）。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
