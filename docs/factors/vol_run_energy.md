---
xname: vol_run_energy
formula: |
  signal = -ts_rank(run_length(volume), 500) * oi_energy(volume, win) * gain
tags: [free_form_first, run_length, oi_energy, bell_modulation, volume]
params: {win: 200, gain: 2.0}
status: 候选
created_ts: 2026-08-17
updated_ts: 2026-08-17
---

# vol_run_energy 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `vol_run_energy`（= `factor/vol_run_energy.yaml`） |
| 类别 | custom |
| 方向 | `-1`（信号高 → 做空） |
| 状态 | 候选（全期显著；变体 win100_gain1.5 更优） |
| 标签 | free_form_first, run_length, oi_energy, bell_modulation, volume |
| 创建 | 2026-08-17（自由代码公式首个因子） |
| 最近更新 | 2026-08-17 |

## 2. 逻辑

**动机**：验证平台**自由代码表达**（formula 内 `def` 自定义算子、含窗口算子、
`${param}` 参数化、`run --set` 变体）的端到端可用性；同时把期货/商品研究中的
RunLength × OI-Energy 钟形调制思路（参考 RunLengthEnergyModulation.h）移植为
A 股日频 volume 版。

**核心逻辑**：两个正交的成交活跃度信号相乘后取负：
1. **量能能量**：`|Δvolume|` 在 `win` 窗口内的分位 rank——放量/缩量越极端能量越高；
   钟形 `sqrt(e·(1-e))` 使**中能量区**（非极端放量缩量）突出、高/低能区被压制。
2. **上涨游程**：volume 连续上涨天数（`sign(Δvolume)==1` 的游程计数）在 500 日
   窗口内的分位。负号对应"游程高 → 未来收益低"（连续放量上涨后回落）。

**数学表达**：

```
e     = ts_rank(|ts_delta(volume, 1)|, win)              # 量能分位
bell  = sqrt(e * (1 - e))                                # 钟形调制（中能区峰）
rl    = ts_count(sign(ts_delta(volume, 1)) == 1, 500)    # 上涨游程
signal = -ts_rank(rl, 500) * bell * gain
```

**输入数据**：`volume`（日频）。

## 3. 参数与实现

### 参数表

| 参数 | 默认值 | 含义 | 有效范围 |
|------|--------|------|----------|
| `win` | 200 | 量能窗口（|Δvol| 的 rank 窗口） | 正整数，>1 |
| `gain` | 2.0 | 信号振幅 | >0 |

（500 日游程窗口为公式内写死，未参数化。）

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
name: vol_run_energy
category: custom
direction: -1
params: {win: 200, gain: 2.0}
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

  _energy = oi_energy(volume, ${win})
  _rl = ts_count(sign(ts_delta(volume, 1)) == 1, 500)
  signal = -ts_rank(_rl, 500) * _energy * ${gain}
```

## 4. 验证结果

> 数据快照自 `results/vol_run_energy/summary.json`（默认参数，2026-08-17）。
> 变体数据见 §5；重跑后按新 summary 更新。

### 样本

| 项 | 值 |
|----|----|
| 区间 | 2022-01-04 ~ 2026-07-31 |
| 周数（有效） | 86 |
| 平均股票数 | 4492 |
| 复权 | qfq |
| 信号缺失率 | 67.99% |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean（方向调整后） | 0.0128 |
| t 值 | 3.12 |
| IR | 0.336 |
| 近 26 周 mean | 0.0076 |
| 近 26 周 t | 1.39 |
| PearsonIC mean（原始信号） | -0.0048（t=-1.56） |

> 语义说明：RankIC 方向调整后为正（按 direction=-1 有效）；Pearson 未乘方向，
> 负值对应"游程高/能量高 → 未来收益低"的原始方向。

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | 0.00151（0.15%/周） |
| 单调性 | false |
| D1 mean_ret | 0.00455 |
| D10 mean_ret | 0.00304 |

### 判定

对照 `docs/factor-mining-playbook.md` §4.1 阈值：

- |t|=3.12 > 2 显著；IR 0.34 > 0.3 优秀；近 26 周 t=1.39（边际，未失效）。
- spread 0.15%/周 略低于 0.2% 关注线；单调性 false 但 D1 明显高于 D10（两端区分）。
- **信号缺失率 67.99% 偏高**：500 日游程窗口冷启动 + 停牌段缺失，实际覆盖
  主要集中在新上市满 500 日的股票——需关注覆盖偏误。
- 结论：**候选**——显著性/稳定性达标，缺失率需治理；最优参数见 §5 变体。

## 5. 迭代历史

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| 2026-08-18 | 衍生：`reversal_20d_five_dim_ctfi` | 批次3轮82：F3 五维加法，见 [`reversal_20d_five_dim_ctfi.md`](reversal_20d_five_dim_ctfi.md) | 0.0713 | 6.91 | **无效**：skew 持平 |
| 2026-08-18 | 衍生：`reversal_20d_four_dim_ctfi` | 批次3轮81：F3 四维加法，见 [`reversal_20d_four_dim_ctfi.md`](reversal_20d_four_dim_ctfi.md) | 0.0717 | 6.77 | 候选：接近全库最强 |
| 2026-08-18 | 衍生：`reversal_20d_wcorr_cti` | 批次3轮100：W3 corr 双倍，见 [`reversal_20d_wcorr_cti.md`](reversal_20d_wcorr_cti.md) | 0.0689 | 7.22 | 观察中：收官确认等权最优 |
| 2026-08-18 | 衍生：`reversal_20d_five_dim_tsvf` | 批次3轮99：F3 flow30 替换，见 [`reversal_20d_five_dim_tsvf.md`](reversal_20d_five_dim_tsvf.md) | 0.0700 | 7.48 | **无效**：intraday 更优 |
| 2026-08-18 | 衍生：`reversal_20d_five_dim_all` | 批次3轮98：F3 五维加法，见 [`reversal_20d_five_dim_all.md`](reversal_20d_five_dim_all.md) | 0.0728 | 6.95 | **无效**：五维饱和 |
| 2026-08-18 | 衍生：`reversal_20d_four_dim_tsfi` | 批次3轮97：F3 四维加法，见 [`reversal_20d_four_dim_tsfi.md`](reversal_20d_four_dim_tsfi.md) | 0.0727 | 6.73 | 候选：接近纪录 |
| 2026-08-18 | 衍生：`reversal_20d_four_dim_ctfs30` | 批次3轮96：F3 flow30，见 [`reversal_20d_four_dim_ctfs30.md`](reversal_20d_four_dim_ctfs30.md) | 0.0706 | 6.91 | 候选：微升 |
| 2026-08-18 | 衍生：`reversal_20d_turn_skew_flow30` | 批次3轮95：T3 三维加法，见 [`reversal_20d_turn_skew_flow30.md`](reversal_20d_turn_skew_flow30.md) | 0.0697 | 6.31 | 候选：投机系最强三维 |
| 2026-08-18 | 衍生：`reversal_20d_intraday_flow30` | 批次3轮94：F3 flow30，见 [`reversal_20d_intraday_flow30.md`](reversal_20d_intraday_flow30.md) | 0.0589 | 5.50 | 候选：谱峰应用 |
| 2026-08-18 | 衍生：`reversal_20d_corr_flow30` | 批次3轮93：F3 flow30，见 [`reversal_20d_corr_flow30.md`](reversal_20d_corr_flow30.md) | 0.0559 | 6.55 | 候选：双谱峰 |
| 2026-08-18 | 衍生：`reversal_20d_corr10_intraday` | 批次3轮92：C3 corr10，见 [`reversal_20d_corr10_intraday.md`](reversal_20d_corr10_intraday.md) | 0.0607 | 6.16 | 候选：谱峰应用 |
| 2026-08-18 | 衍生：`reversal_20d_cti_flow30` | 批次3轮91：F3 四维加法，见 [`reversal_20d_cti_flow30.md`](reversal_20d_cti_flow30.md) | 0.0736 | 6.85 | **无效**：flow30 边际 |
| 2026-08-18 | 衍生：`reversal_20d_corr_turn_flow30` | 批次3轮90：F3 flow30，见 [`reversal_20d_corr_turn_flow30.md`](reversal_20d_corr_turn_flow30.md) | 0.0717 | 6.74 | 候选：flow30 微升 |
| 2026-08-18 | 衍生：`reversal_20d_netflow30` | 批次3轮89：F2 netflow30，见 [`reversal_20d_netflow30.md`](reversal_20d_netflow30.md) | 0.0447 | 5.32 | 候选：谱峰 30 日 |
| 2026-08-18 | 衍生：`reversal_20d_vol_flow` | 批次3轮74：V3 vol×flow，见 [`reversal_20d_vol_flow.md`](reversal_20d_vol_flow.md) | 0.0461 | 6.22 | 候选：IC 超 netflow |
| 2026-08-18 | 衍生：`reversal_20d_flow_skew` | 批次3轮61：F3 flow×skew，见 [`reversal_20d_flow_skew.md`](reversal_20d_flow_skew.md) | 0.0464 | 5.75 | 候选：IC 超两父本 |
| 2026-08-18 | 衍生：`reversal_20d_corr_flow_intraday` | 批次3轮59：T3 三维加法，见 [`reversal_20d_corr_flow_intraday.md`](reversal_20d_corr_flow_intraday.md) | 0.0607 | 5.96 | 候选：三维 IC 纪录 |
| 2026-08-18 | 衍生：`reversal_20d_drawdown` | 批次3轮49：R2 回撤结构，见 [`reversal_20d_drawdown.md`](reversal_20d_drawdown.md) | -0.0160 | -1.20 | **无效**：回撤无反转信息（含方向修正） |
| 2026-08-18 | 衍生：`reversal_20d_pricevolcorr_turn` | 批次3轮35：V2 turnover 量代理，见 [`reversal_20d_pricevolcorr_turn.md`](reversal_20d_pricevolcorr_turn.md) | 0.0425 | 6.37 | **无效**：量代理等价 |
| 2026-08-18 | 衍生：`reversal_20d_overnight` | 批次3轮26：O2 隔夜成分（图景补全），见 [`reversal_20d_overnight.md`](reversal_20d_overnight.md) | -0.0223 | -4.06 | **无效**：隔夜延续、日内反转——拆分图景闭环 |
| 2026-08-18 | 衍生：`vol_run_energy_symrun_lin` | 批次3轮5：H3 去钟形（base=symrun），见 [`vol_run_energy_symrun_lin.md`](vol_run_energy_symrun_lin.md) | -0.0441 | -8.16 | **无效**：信号反转，钟形是秩次核心 |
| 2026-08-17 | 衍生：`vol_run_energy_symrun` | 挖因子轮 7：H3 游程对称化 `==1`→`!=0`（base=rl120_turn），见 [`vol_run_energy_symrun.md`](vol_run_energy_symrun.md) | 0.0276 | 8.40 | **强候选**：IC +82%、IR 0.65；原始"上涨游程"被证伪/替代 |
| 2026-08-17 | 衍生：`vol_run_energy_rl120_turn` | 挖因子轮 1：H2 游程窗口参数化 rl_win=120 + H8 volume→turnover，见 [`vol_run_energy_rl120_turn.md`](vol_run_energy_rl120_turn.md) | 0.0152 | 5.26 | **全面更优**：覆盖翻倍（有效周 167）、近 26 周不衰减（t=3.24）、IR 0.41 |
| 2026-08-17 | `vol_run_energy_win100_gain1.5` | `run --set win=100 gain=1.5`：缩短能量窗口 + 降振幅 | 0.0131 | 3.86 | **更优**：t 3.12→3.86、IR 0.34→0.37、spread 0.15%→0.26%/周、缺失率 68%→60% |
| 2026-08-17 | `vol_run_energy`（初始） | 自由代码公式端到端验证 | 0.0128 | 3.12 | 显著；缺失率高（67.99%） |

变体 `win100_gain1.5` 细节（快照自 `results/vol_run_energy_win100_gain1.5/summary.json`）：
样本 2022-01-04 ~ 2026-07-31、108 有效周、4554 股均、缺失率 59.59%；
spread 0.00255、D1 0.00686 / D10 0.00431。

## 6. 风险与备注

- **缺失率**：500 日游程窗口冷启动导致新上市/停牌股大量缺失（默认 68%）；
  变体 win=100 通过缩短能量窗口把有效周从 86 提到 108。若实盘化需明确缺失股
  的处理语义（剔除 vs 填充）。
- **变体选择偏差**：win100_gain1.5 是在同一数据集上挑选的更优参数，存在
  in-sample 选择风险；需换样本期（如 2019-2021）外样本复验后才能实盘。
- **游程逻辑过度简化**：A 股日频 volume 的"连续上涨天数"对停牌敏感——停牌
  前后 Δvolume 为 0/异常值，游程可能失真。
- **相关系数**：`_energy` 与 `_rl` 相乘是否有交互增益（vs 单独使用）未做
  消融实验——待迭代项。

---
*档案规范见 `_template.md`；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
