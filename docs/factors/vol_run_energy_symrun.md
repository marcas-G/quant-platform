---
xname: vol_run_energy_symrun
formula: |
  signal = -ts_rank(run_freq(turnover, rl_win), rl_win) * oi_energy(turnover, win) * gain  # run_freq: sign(d_turn)!=0
tags: [mine_r7, run_length, oi_energy, symmetric, divergence, best_so_far]
params: {win: 200, gain: 2.0, rl_win: 120}
status: 候选（强候选：t=8.40, IR=0.65）
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# vol_run_energy_symrun 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy_symrun`（= `factor/vol_run_energy_symrun.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 候选（强候选：t=8.40, IR=0.65 优秀；近 26 周边际 t=1.49） |
| 标签 | mine_r7, run_length, oi_energy, symmetric, divergence, best_so_far |
| 创建 | 2026-08-17（挖因子批次 2 轮次 7，种子 `vol_run_energy`，base `vol_run_energy_rl120_turn`） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：种子 `vol_run_energy` 的隐含假设 (H3) 游程只算放量上涨
（`sign(Δ)==1`，隐含"放量下跌无反转信息"）。变异为**对称游程**
`sign(Δ)!=0`（涨跌都算活跃）：放量下跌（分歧/恐慌）同样是情绪宣泄，
理应预示反转——"量能分歧频率"替代"单边看多频率"。
变异叠加在已知最优 base（rl120_turn：rl_win=120 + turnover 口径）上，
H3 单独归因。

**核心逻辑**：换手率变化活跃频率（120 日，涨跌都算）× 量能钟形调制——
活跃度越高（分歧越大）未来收益越低（回归）。

**数学表达**：

```
e     = ts_rank(|ts_delta(turnover, 1)|, win)
bell  = sqrt(e * (1 - e))
rl    = ts_count(sign(ts_delta(turnover, 1)) != 0, rl_win)   # 对称游程（变异点）
signal = -ts_rank(rl, rl_win) * bell * gain
```

**输入数据**：`turnover`（daily_basic.turnover_rate 映射）。

## 3. 参数与实现

### 参数表

| 参数 | 默认值 | 含义 | 有效范围 |
|------|--------|------|----------|
| `win` | 200 | 量能窗口 | 正整数 >1 |
| `gain` | 2.0 | 信号振幅 | >0 |
| `rl_win` | 120 | 活跃频率窗口 | 正整数 >1 |

### 处理链

```
universe: {exclude_st: true, exchanges: [SSE, SZSE]}
date: 2022-01-01 ~ 2026-07-31
process: winsorize(quantile=0.99) → standardize()
target: forward_return_5d
adjustment: qfq
```

### 实现（YAML 全文）

```yaml
name: vol_run_energy_symrun
category: custom
direction: -1
params: {win: 200, gain: 2.0, rl_win: 120}
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2022-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_rank, ts_delta, ts_count

  def oi_energy(x, n):
      _e = ts_rank(ts_delta(x, 1).abs(), n)
      return sqrt(_e * (1 - _e))

  _energy = oi_energy(turnover, ${win})
  _rl = ts_count(sign(ts_delta(turnover, 1)) != 0, ${rl_win})
  signal = -ts_rank(_rl, ${rl_win}) * _energy * ${gain}
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy_symrun/summary.json`（2026-08-17）。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 167 |
| 平均股票数 | 4566 |
| 复权 | qfq |
| 信号缺失率 | 35.51% |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0276 |
| t 值 | 8.40 |
| IR | 0.650 |
| 近 26 周 mean | 0.0093 |
| 近 26 周 t | 1.49 |
| PearsonIC mean（原始信号） | -0.0187（t=-5.60） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00348（0.35%/周） |
| 单调性 | false |
| D1 mean_ret | 0.00386 |
| D10 mean_ret | 0.00038 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- **t=8.40 强显著（10 轮内最佳）**；IR 0.65 > 0.3 优秀；
  spread 0.35%/周 > 0.2% 关注线。
- 相对 base rl120_turn：IC +82%（0.0152→0.0276）、IR 0.41→0.65、
  spread +38%——H3'（对称游程）**强验证**。
- 近 26 周 t=1.49 边际（base 3.24）：近一年弱于 base，但全期仍显著。
- 结论：**候选（强候选）**——量能分歧频率是核心预测源；
  下一步：近 26 周衰减观察 + 与其他因子正交性分析。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`vol_run_energy_symrun_corr` | 批次3轮39：S3 跨家族秩次加法，见 [`vol_run_energy_symrun_corr.md`](vol_run_energy_symrun_corr.md) | 0.0147 | 2.79 | **无效**：量维度耦合，跨家族不可组合 |
| 2026-08-18 | 衍生：`vol_run_energy_symrun_down` | 批次3轮19：S3 只算下跌活跃，见 [`vol_run_energy_symrun_down.md`](vol_run_energy_symrun_down.md) | 0.0126 | 3.95 | **无效**：上涨活跃是游程主源 |
| 2026-08-18 | 衍生：`vol_run_energy_symrun_bell1` | 批次3轮13：S3 钟形锐度 1.0，见 [`vol_run_energy_symrun_bell1.md`](vol_run_energy_symrun_bell1.md) | 0.0278 | 8.37 | **无效**：与 sqrt 等价 |
| 2026-08-17 | `vol_run_energy_symrun`（初始） | 挖因子轮 7：H3 游程对称化 `==1` → `!=0`（base=rl120_turn） | 0.0276 | 8.40 | **强候选**：IC +82%、IR 0.65 |

## 6. 风险与备注

- **近 26 周走弱**：t=1.49 边际（base 3.24）——需观察分歧因子是否在近期
  环境衰减。
- **与家族相关**：与 [`vol_run_energy_rl120_turn.md`](vol_run_energy_rl120_turn.md)
  同源（能量钟形部分共享），差异在游程定义；种子
  [`vol_run_energy.md`](vol_run_energy.md) 的原始游程（上涨频率）被本因子
  证伪/替代。
- 变异记录 `results/_mine_round_7.md`。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
