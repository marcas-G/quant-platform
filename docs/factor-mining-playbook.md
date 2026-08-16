# FactorLab 因子挖掘手册（Factor Mining Playbook）

日期：2026-08-16
前置：数据就绪（`factorlab data update` 到最新交易日）——数据运维见 `docs/data-ops-playbook.md`

## 1. 挖掘工作流总览（SOP）

```
① 想法 → ② 写 spec（模板改）→ ③ run 快速验证 → ④ 评估解读 → ⑤ 迭代深化 → ⑥ 入库管理
   （公式假设）   （5-10 分钟）      （1 分钟内）     （判断有效）   （改参数/口径）    （list/show/serve）
```

**单因子迭代循环**（每次 10-20 分钟）：
1. 从模板（§2）选接近的因子类型，替换公式/参数
2. `factorlab run factor/demo.yaml`（或 `--no-backtest` 快速版）
3. 读 `summary.json` 评估（或 `factorlab show demo`）
4. 按 §4 判断：有效 → 深化（调参/换口径/加 process）；无效 → 换思路
5. 有效因子用 `factorlab list` 管理，`factorlab serve` 可视化对比

## 2. 因子类型与模板（可直接运行）

> 全部模板已在真实平台库验证可跑（5 只 × 2 年 ≈ 1 秒）。universe/日期按需替换。

### 2.1 动量类（direction=1，越高越好）

```yaml
name: momentum_20d
category: custom
direction: 1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2020-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_delay
  signal = ts_mean(close, 20) / ts_delay(close, 20) - 1
```

变体：动量 = `ts_delay(close, n) / ts_delay(close, 2*n) - 1`（滞后动量，避开短期反转）；
反转（direction=-1）= `ts_delay(close, 1) / ts_delay(close, 5) - 1`。

### 2.2 波动类（direction=-1，低波动溢价）

```yaml
name: low_vol_20d
category: custom
direction: -1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2020-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_std_dev, ts_delay
  signal = -ts_std_dev(ts_delay(close, 1), 20)
```

变体：波动率偏度（`ts_skewness`）、下行波动（条件 std）、振幅（`(high-low)/open` 的 std）。

### 2.3 量价类（direction=1，放量）

```yaml
name: volume_surge
category: custom
direction: 1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2020-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_mean
  signal = volume / ts_mean(volume, 20) - 1
```

> 公式不引用 close 也可以（close 恒加载，forward 自动可用）。

### 2.4 技术指标类（polars_ta wq/ta/tdx 族）

```yaml
name: rsi_20
category: custom
direction: 1
universe:
  rules: {exclude_st: true, exchanges: ["SSE", "SZSE"]}
date:
  start: "2020-01-01"
  end: "2026-07-31"
process:
  - winsorize(quantile=0.99)
  - standardize()
formula: |
  from polars_ta.prefix.wq import ts_RSI
  signal = ts_RSI(close, 20)
```

可用算子族：`wq`（ts_mean/ts_std_dev/ts_rank/ts_corr/ts_covariance/ts_skewness/ts_kurtosis/
ts_cum_sum/...）、`ta`（RSI/ATR/CCI/MACD/WILLR/TRIX）、`tdx`（BIAS/KDJ/BOLL/RSV）。
用 `factorlab op list` 查全量。

### 2.5 自定义 def 与内联宏（组合多步逻辑）

```yaml
formula: |
  from polars_ta.prefix.wq import ts_mean, ts_std_dev, ts_delay

  def momentum(x, n):
      return ts_delay(x, n) / ts_delay(x, 2 * n) - 1

  _ret = ts_delay(close, 1)
  _vol = ts_std_dev(_ret, 20)
  signal = momentum(close, 5) - _vol
```

> **限制**：`def` 内禁止 ts_/cs_ 算子（分区安全——窗口算子请写顶层）；中间变量用 `_` 前缀。

## 3. Spec 编写规范

### 3.1 必填字段与推荐值

| 字段 | 规则 | 挖掘建议 |
|------|------|---------|
| `universe` | codes 或 rules 二选一 | **挖掘批次固定同一 universe**（同池计算、同池比较）；全市场用 rules（exclude_st + exchanges） |
| `date` | 可调历史深度 | 验证期建议 ≥3 年（统计稳健）；全历史 2000 起回测更长 |
| `direction` | 1 或 -1 | 按因子经济学含义（动量=1、反转/波动=-1） |
| `adjustment` | raw/qfq/hfq/pit_qfq | **默认 qfq**（除权日不假崩）；价差类因子可试 raw；pit_qfq 用于严格防未来研究 |
| `process` | 处理链 | 推荐 `winsorize(quantile=0.99) → standardize()` 基线；neutralize 按需（行业/市值） |
| `target` | forward_return_5d（当前） | 20d 暂未接线（quant_core 固定 5d） |

### 3.2 process 链组合

```
基线：    winsorize(quantile=0.99) → standardize()
截面：    + neutralize(by=industry)   # 行业中性（静态行业，v1 近似）
         + neutralize(by=size)        # 市值分桶中性（十分位）
缺失：    fillna(method=value, value=0.0) 或 method=forward
```

**链内注意**：neutralize 需要行业/市值数据（平台库 daily_basic 支撑）；截面 N<10 时 size 中性化每桶 1 只退化（demean 恒 0——已知局限）。

### 3.3 防未来三原则（平台已强制 + 用户自查）

1. **TS 窗口只回溯**（平台强制：负 lookback 拒绝、def 内窗口算子拒绝）
2. **因子值只用到当日数据**（平台强制：前向收益独立于因子计算）
3. **复权口径一致性**（用户自查：动量/技术指标用 qfq；评估目标 forward 用 total_return 含分红）

## 4. 评估解读指南

`factorlab run` 产出 `summary.json.evaluation`，逐项解读：

### 4.1 核心指标与参考阈值

| 指标 | 字段 | 解读 | 参考（A 股周频） |
|------|------|------|-----------------|
| **RankIC mean** | `ic.mean` | 因子与未来 5 日收益的秩相关均值 | 0.02-0.05 可关注；>0.05 优秀；\|<0.01\| 无效 |
| **IC t_stat** | `ic.t_stat` | 显著性（mean/std×√n） | \|t\|>2 显著；1-2 边际 |
| **IC IR** | `ic.ir` | mean/std（稳定性） | >0.3 优秀；0.1-0.3 可研究 |
| **十分位单调性** | `decile_returns.monotonic` | 档间收益是否单调 | true 理想；false 但两端区分也可 |
| **十分位 spread** | `decile_returns.spread.ret` | 最佳-最差档周收益差 | >0.2%/周 可关注 |
| **分层回测年化** | `layered_backtest.summary.long_short.annual_return` | long-short 年化 | >10% 可关注（无成本） |
| **long-short 夏普** | `...long_short.sharpe` | 风险调整 | >1 优秀 |
| **换手** | `turnover.monthly` | 因子调仓频率 | <50%/月 可实盘化；高换手容量差 |
| **覆盖** | `coverage.pct_valid` | 有效行比例 | >80% 正常；低覆盖需查 fillna |

### 4.2 净值曲线形态判断（serve 详情页）

- **单调分层**：D1 净值向上、D10 向下、中间档有序 → 强因子
- **两端分化**：D1/D10 拉开但中间乱 → 非线性有效（可用排序/分组利用）
- **长期平**：净值贴地 → 无效；**后期陡峭**：可能过拟合近期
- **long-short 稳定向上** → 有效；**宽幅震荡** → IC 不稳定

### 4.3 过拟合警示

- 5 只小样本的 IC 无统计意义——**正式评估至少 50-100 只 × 3 年**
- 参数微调 IC 大幅跳变 → 过拟合信号（换区间验证）
- 同一思路的多个变体都有效才可信（非单个"最好参数"）
- 报告期外验证（前 2 年训练 / 后 1 年验证）是黄金标准

## 5. 常见陷阱

| 陷阱 | 表现 | 规避 |
|------|------|------|
| 前视偏差 | 因子用了未来数据（如未来 adj 基准） | 默认 qfq（最新因子）；严格研究用 pit_qfq |
| 幸存者偏差 | 只看了现存活股票 | universe 用全历史（rules 不排除退市——平台已含） |
| 复权口径错误 | 除权日因子假崩 | 默认 qfq；价差类自查 |
| 稀疏字段 | 因子大部分 null | `factorlab data verify` 的稀疏报告；fillna |
| 小样本 IC | t_stat 虚高/虚低 | ≥50 只 × 3 年；看 t_stat 不看 mean |
| 除权周前向收益扭曲 | forward 在除权周异常 | 平台已用 total_return（含分红） |
| 涨跌停日 | 一字板不可成交 | 回测/实盘需 Raw Execution 过滤（平台数据有 stk_limit 表） |
| ST/停牌污染 | 异常值 | universe exclude_st；fill_suspensions 已补停牌 |

## 6. 算子扩展（三层机制）

平台提供三层算子扩展——按使用场景选择：

| 层 | 机制 | 适用 | 示例 |
|----|------|------|------|
| **1** | 公式内 `def` | 单次使用的元素级逻辑（无窗口） | `def flip(x, n): return x * n` |
| **2** | DSL 内联宏（spec.operators） | 公式内复用、可参数化 | `mom_ratio(x, n)` 宏 |
| **3** | Python 算子插件（`op add`） | 可复用、需版本钉住的新语义 | `@factor_op("event_decay", kind="ts", ...)` |

**选择建议**：临时逻辑用第 1 层；同 spec 内复用用第 2 层；跨因子复用/需要版本管理用第 3 层（`~/.factorlab/plugins/`，AST 安全扫描 + 版本快照）。

**第 1 层——公式内 def（元素级）**：

```yaml
formula: |
  def flip(x, n):
      return x * n
  signal = flip(close, 2) - close
```

> **限制**：`def` 内禁止 ts_/cs_ 窗口算子（分区安全——请写顶层）；中间变量用 `_` 前缀。

**第 2 层——DSL 内联宏**：

```yaml
operators:
  mom_ratio:
    params: [x, n]
    formula: "delay(x, n) / delay(x, 2 * n) - 1"
formula: |
  from polars_ta.prefix.wq import ts_delay as delay
  signal = mom_ratio(close, 5)
```

**第 3 层——Python 算子插件**：

```python
# my_ops.py —— factorlab op add ./my_ops.py
import polars as pl
from factorlab.ops.registry import factor_op

@factor_op("event_decay", kind="ts", version="0.1.0")
def event_decay(x: pl.Expr, n: int) -> pl.Expr:
    return x.rolling_mean(window_size=n)
```

```bash
factorlab op add ./my_ops.py      # AST 安全扫描 + 注册（冲突需 --force）
factorlab op list                 # 列出用户插件算子
factorlab op doc event_decay      # 签名/类别/版本
factorlab op remove event_decay   # 禁用（保留历史结果）
```

**内置算子**（直接可用，无需扩展）：`wq` 族（ts_mean/ts_std_dev/ts_rank/ts_corr/ts_covariance/
ts_skewness/ts_kurtosis/ts_cum_sum/ts_delay/ts_delta 等）、`ta/tdx` 族（RSI/ATR/CCI/MACD/BIAS/KDJ/BOLL）、
平台薄封装（returns/vwap/adv20/group_rank/group_mean）。

## 7. 因子入库与管理

```
factorlab run factor/my_factor.yaml          # 计算 + 评估 + 分层回测
factorlab list                               # 查看所有因子（IC/spread 排序）
factorlab show my_factor                     # 单因子完整摘要
factorlab serve                              # Web 可视化（IC 曲线/净值曲线）
```

**因子命名约定**：`<类别>_<逻辑>_<窗口>`（如 `momentum_20d`、`low_vol_20d`）；
方向写入 spec（direction）——评估输出自动按方向调整。

## 7. 数据刷新提醒

- 数据停在 2026-08-14：`factorlab data update`（增量到最新交易日）
- token 8/22 到期：到期前 `data refresh` 或续费（teajoin redeem）
- 定期 verify：`factorlab data verify`（完整性自检）
