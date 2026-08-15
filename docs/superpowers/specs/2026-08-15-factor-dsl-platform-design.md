# 因子 DSL 计算平台 — 设计文档

日期：2026-08-15
状态：待评审
路径：`quant-platform/`（新项目）

## 1. 背景与目标

用户已有完整的量化研究体系（`C:\Users\ThinkPad\quant-data`）：

- `quant-core`：Rust + polars 因子引擎，`FactorSpec`（name/category/direction/inputs/expr），
  `compute_factor` 与 `backtest::evaluate`（RankIC、PearsonIC、十分位收益、换手率、覆盖率、正交性），
  已编译为 PyO3 绑定 `quant_core`（cp313 Windows wheel 已安装）。
- `quant.duckdb`（6.3GB）：`daily` 表（2000-01-04 至 2026-07-31，17.2M 行，5875 只股票，
  列 `date/open/high/low/close/volume/amount/turnover/pct_chg/code`）、`stock_basic_tushare`、
  财务报表、指数成分等；`quant_tushare_full.duckdb`（7.7GB）为全量镜像。
- `quant_factor.duckdb`：`factor_weekly`（2010 至 2026-07，date/code × 50+ 因子列 +
  `forward_return_5d/20d`），可作评估交叉验证。
- JoinQuant 公式目录：626 条公式（Alpha101/Alpha191/技术指标）。
- teajoin.com Tushare 兼容代理：已验证可用（API Key 已兑换，到期 2026-08-22），
  用于增量补数据（450 次/分钟，建议间隔 0.2s）。

目标：在 `quant-platform/` 从零构建一个**更规范的因子 DSL 计算平台**——个人使用、单机运行、
命令行提交声明式因子 DSL、本地计算因子值与研究级评估、Web 展示结果。

设计参考了市面主流因子 DSL 的调研结论：

- WorldQuant BRAIN：`ts_* / cs_* / group_*` 算子命名事实标准，中性化作为独立流程。
- Microsoft qlib：独立 processor 处理链；滚动 `Slope/Rsquare/Resi` 回归算子；自定义算子注册。
- BigQuant bigexpr：分组算子、TA-LIB 技术指标族、自定义函数。
- 米筐 RQFactor：横截面中性化与回归残差算子、`jqfactor_analyzer` 式评估输出。
- AKQuant：TS/CS/EL 算子分类、嵌套表达式自动中间物化、防未来函数。
- FactorBench / DolphinDB：受限表达式与流批一致的工程理念。

## 2. 范围

### v1 包含

- 声明式 DSL：YAML 元数据 + 受限因子脚本（变量 `let`、自定义函数 `def`、条件逻辑、注释）。
- 算子集：WorldQuant/JoinQuant 全量对齐，含 Alpha101/191、回归族、分组族、TA 技术指标子集
  （约 80-90 个算子），全部经注册表实现，支持别名兼容。
- 处理管线：表达式之后独立执行 `winsorize / zscore / csranknorm / robustzscore /
  neutralize / clip / fillna`。
- Python 引擎解析并计算因子；TS/CS/EL 算子分类，嵌套表达式自动中间物化，防未来函数。
- 评估：RankIC / PearsonIC / 十分位收益 / 覆盖度 / 换手率（复用 Rust `quant_core`），
  叠加分层回测累计净值、因子对比、组合合成。
- 因子与结果本地存储（parquet + JSON 摘要 + 算子版本快照）。
- CLI：`run / list / show / compare / serve / data refresh / op list / op doc`。
- Web 可视化：FastAPI + Jinja2 + Plotly。
- 新算子双通道扩展：DSL 内宏组合 + Python 算子插件注册表。
- 数据源：本地 DuckDB（只读）为主，teajoin 增量补数据到平台自有缓存库。

### v1 明确不做

- 多用户 / 权限 / 计费。
- 实时行情、分钟线。
- DSL 编译进 Rust（`cargo build` 集成）。
- Web 端编辑 DSL。
- 事件驱动 / 跨资产 context 语法（FactorBench 风格，v2）。
- 信息增益率等后续统计指标（接口已预留，v2）。

## 3. 已确认的关键决策

| 主题 | 决策 |
|------|------|
| 使用形态 | 个人工具，单机 |
| 交互 | CLI 为主，Web 只做结果可视化 |
| 引擎 | Python 解析 DSL 并计算；评估复用 Rust `quant_core` |
| 数据范围 | 自选股票池；全 A 是可选范围而非默认加载量 |
| 历史深度 | DSL 内 `date.start/end` 可调 |
| 过滤位置 | universe 是 DSL 一等公民（显式列表或规则），数据层按需拉取 |
| DSL 文件 | YAML 元数据 + 受限因子脚本（let/def/条件逻辑） |
| 算子集 | WorldQuant 命名 + Alpha101/191 全量 + 回归族 + 分组族 + TA 子集，注册表实现 |
| 新算子 | 宏组合（不写代码）+ Python 插件（注册表），带版本钉住 |
| 处理管线 | 表达式后独立 process 链（对齐 qlib processors） |
| 评估产出 | 因子值 + IC/分层/换手 + 分层回测净值 + 因子对比 + 组合合成 |
| Web 栈 | FastAPI + Jinja2 + Plotly |

## 4. 架构

```
quant-platform/
├── pyproject.toml
├── README.md
├── .gitignore
├── docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md
├── src/factorlab/
│   ├── __init__.py
│   ├── config.py            # 路径与环境变量（本地 DuckDB 路径、teajoin key 等）
│   ├── dsl/
│   │   ├── lexer.py         # 词法分析（数字、标识符、注释、运算符）
│   │   ├── parser.py        # 递归下降 -> AST（let/def/表达式/三元/布尔）
│   │   ├── ast.py           # AST 节点
│   │   ├── expand.py        # 宏展开（spec 内联 + 本地算子库）
│   │   ├── validate.py      # 语义校验（算子存在、参数个数、列名、作用域）
│   │   └── errors.py        # DSLParseError（带行列号）
│   ├── ops/
│   │   ├── registry.py      # @factor_op 注册表（名称、实现、版本、算子类别）
│   │   ├── el_ops.py        # 元素级算子（abs/log/sign/if/clip…）
│   │   ├── ts_ops.py        # 时序算子（ts_mean/ts_rank/ts_resi…）
│   │   ├── cs_ops.py        # 横截面算子（rank/zscore/cs_regression_residual…）
│   │   ├── group_ops.py     # 分组算子（group_rank/group_mean…）
│   │   ├── ta_ops.py        # TA-LIB 技术指标算子（rsi/macd/atr…）
│   │   └── macros.py        # 内置宏算子
│   ├── process/
│   │   ├── registry.py      # 处理步骤注册表
│   │   └── processors.py    # winsorize/zscore/csranknorm/robustzscore/neutralize/clip/fillna
│   ├── data/
│   │   ├── source.py        # 本地 DuckDB 只读读取（daily、stock_basic_tushare）
│   │   ├── teajoin.py       # Tushare 兼容 HTTP 客户端（限流、重试）
│   │   ├── universe.py      # universe 解析（显式列表 / 规则过滤）
│   │   └── cache.py         # 平台自有缓存（parquet + duckdb）
│   ├── engine/
│   │   ├── compute.py       # AST -> 因子面板
│   │   ├── partitions.py    # TS/CS/EL 分类、嵌套中间物化、防未来函数保证
│   │   └── forward.py       # 前向收益计算与周频对齐
│   ├── eval/
│   │   ├── base.py          # Metric 抽象接口
│   │   ├── registry.py      # 指标注册表
│   │   ├── rust_ic.py       # quant_core.evaluate_factor 桥接
│   │   ├── metrics.py       # 轻量指标（coverage 等，本地实现）
│   │   ├── layered.py       # 分层回测与累计净值
│   │   └── compare.py       # 因子对比与组合合成
│   ├── registry/
│   │   ├── store.py         # 因子定义/结果持久化
│   │   └── versions.py      # 算子集版本快照
│   ├── cli/
│   │   └── main.py          # typer CLI
│   └── web/
│       ├── app.py           # FastAPI 应用
│       ├── templates/       # Jinja2 模板
│       └── static/          # plotly.js 等静态资源
├── tests/
│   ├── conftest.py
│   ├── test_lexer_parser.py
│   ├── test_ops.py
│   ├── test_process.py
│   ├── test_engine.py
│   ├── test_alpha_corpus.py # Alpha101/191 公式对拍
│   ├── test_ta_ops.py       # TA 算子与 talib 数值对拍
│   ├── test_eval.py
│   └── test_cli.py
```

依赖（Python 3.13）：`pandas`、`numpy`、`duckdb`、`pyyaml`、`typer`、`fastapi`、
`uvicorn`、`jinja2`、`plotly`、`requests`，以及已安装的 `quant_core`。
TA 算子若采用 talib/pandas-ta，作为可选依赖，缺省时相关算子不可用并给出明确提示。

## 5. 数据流

```
factorlab run spec.yaml
  → 解析 YAML + 因子脚本（lexer/parser，let/def/表达式）
  → 宏展开 + 语义校验（算子类别 TS/CS/EL、作用域、参数）
  → 解析 universe（显式列表 / 规则过滤，查 stock_basic_tushare）
  → 加载数据：本地 quant.duckdb 只读；缺日期段时 teajoin 增量补到平台缓存库
  → 引擎按 TS/CS/EL 分区执行 AST；嵌套分区自动中间物化，保证时序只回溯
  → 处理管线：winsorize → zscore/neutralize 等 process 链
  → 计算前向收益（daily close），按周频对齐（匹配 Rust 评估语义）
  → 评估：quant_core（IC/十分位/换手）+ 分层回测 + 本地轻量指标
  → 结果落盘：parquet（因子值）+ JSON（摘要/指标/回测曲线/算子版本快照）
  → factorlab serve 起 Web 展示
```

平台不修改 `quant-data` 下任何文件；本地 DuckDB 一律只读打开。

## 6. DSL 规范

### 6.1 Spec 文件（YAML + 脚本）

```yaml
name: vol_skew_mom
category: custom
direction: 1
description: 波动率偏度动量示例
universe:
  codes: ["000001.SZ", "600519.SH"]   # 显式列表；与 rules 互斥
  # rules: { exclude_st: true, min_list_days: 120, exchanges: ["SZSE", "SSE"] }
date:
  start: "2020-01-01"
  end: "2026-07-31"
target: forward_return_5d              # 默认 forward_return_5d
process:                               # 表达式之后依次执行的处理链
  - winsorize(quantile=0.99)
  - standardize()
  - neutralize(by: industry)
operators:                             # 可选：内联宏定义
  mom_ratio:
    params: [x, n]
    formula: "delay(x, n) / delay(x, 2*n) - 1"
formula: |
  def momentum(x, n) {
    delay(x, n) / delay(x, 2*n) - 1
  }
  let ret = returns(close)
  let vol = ts_std(ret, 20)
  let cond = (vol < ts_median(vol, 60)) && (close > delay(close, 5))
  rank(momentum(close, 5) - zscore(vol)) - 0.5
```

多因子组合时，`formula` 可替换为 `factors:` 列表，每个元素含 `name`、`formula`、
可选 `process`；配合 `combine: { method: ic_weight | equal_weight | weight_sum, weights: [...] }`
生成复合因子并评估。

字段约束：

- `name`：必填，`^[A-Za-z_][A-Za-z0-9_]{0,63}$`，全局唯一。
- `category`：必填，v1 枚举 `ohlcv_core / ohlcv_retail / valuation / custom`。
- `direction`：必填，`1`（越高越好）或 `-1`（越低越好）。
- `universe.codes` 与 `universe.rules` 二选一；`rules` 支持 `exclude_st`、
  `min_list_days`、`exchanges`（值为 `SSE/SZSE`，与 `stock_basic_tushare` 一致；
  v1 固定集合，后续可加）。
- `date.start/end`：可调历史深度；默认空则取本地库全范围。
- `target`：评估目标，v1 支持 `forward_return_5d / forward_return_20d`。
- `formula` 或 `factors`：二选一。

### 6.2 脚本语法

- 语句：`let name = expr`（变量绑定）、`def name(params) { ... }`（自定义函数）、
  末尾表达式（最终因子值）。
- 表达式：数字字面量、列引用、算子调用、括号嵌套、一元负号。
- 二元运算：算术 `+ - * / %`，比较 `< <= > >= == !=`，布尔 `&& ||`。
- 条件：`if(cond, a, b)`、三元 `cond ? a : b`。
- 注释：`#` 至行尾。
- 作用域：函数局部变量遮蔽外层变量；`let` 只读不可重绑定（避免隐藏副作用）。
- 禁止：循环、副作用、外部导入、任意外部对象访问（保持声明式与安全）。

解析错误携带行列号；未知算子给出相似算子建议（difflib）。

### 6.3 算子命名与分类

命名采用 WorldQuant 事实标准：`ts_*` 时序、`cs_*`/裸 `rank/zscore` 横截面、
`group_*` 分组、`ta_*` 技术指标；同时保留 Alpha101 别名以保证 626 条公式可直接运行。

**元素级（EL，逐行无窗口）**

`abs`、`sign`、`log`、`log10`、`log1p`、`exp`、`expm1`、`sqrt`、`power(x,e)`、
`signed_power(x,e)`、`min(a,b)`、`max(a,b)`、`if(cond,a,b)`、`clip(x,lo,hi)`、
`ceil`、`floor`、`round`、`isnan(x)`。

**时序（TS，按 code 分组、按日期排序、只回溯）**

`delay(x,d)`（别名 `ref`）、`delta(x,d)`、`pct_change(x,d)`、`ts_mean(x,d)`
（别名 `mean/ma/sma`）、`ts_std(x,d)`（别名 `stddev/std`）、`ts_sum(x,d)`（别名 `sum`）、
`ts_product(x,d)`（别名 `product`）、`ts_min(x,d)`（别名 `llv`）、`ts_max(x,d)`
（别名 `hhv`）、`ts_median(x,d)`、`ts_var(x,d)`、`ts_skew(x,d)`、`ts_kurt(x,d)`、
`ts_quantile(x,d,q)`、`ts_mad(x,d)`、`ts_count(x,d)`、`ts_count_nonzero(x,d)`、
`ts_rank(x,d)`、`ts_arg_max(x,d)`（别名 `ts_argmax`）、`ts_arg_min(x,d)`
（别名 `ts_argmin`）、`ts_zscore(x,d)`、`ts_corr(x,y,d)`（别名 `correlation/corr`）、
`ts_cov(x,y,d)`（别名 `covariance/cov`）、`ts_slope(x,d)`、`ts_rsquare(x,d)`、
`ts_resi(x,d)`、`ts_regression(y,x,d)`、`wma(x,d)`、`ewma(x,d)`（别名 `ema`）、
`decay_linear(x,d)`（别名 `ts_decay_linear`）、`cross(a,b)`（a 从下向上穿越 b）、
`returns`（日收益，`close / delay(close, 1) - 1`）、`vwap`（当日成交额/成交量）、
`adv20`（20 日均成交量）。

**横截面（CS，按 date 分组）**

`rank(x)`（别名 `cs_rank`）、`zscore(x)`（别名 `cs_zscore/standardize`）、
`scale(x,a=1)`、`demean(x)`、`quantile(x,bins=5)`、`top(x,threshold,pct)`、
`bottom(x,threshold,pct)`、`cs_regression_residual(y, *x, add_const=true)`、
`cs_fillna(x, by=industry)`。

**分组（date + key，key 默认 industry）**

`group_rank(key, x)`、`group_mean(key, x)`、`group_zscore(key, x)`、
`group_scale(key, x)`。

**技术指标（TA，插件族）**

`ta_sma`、`ta_ema`、`ta_wma`、`ta_mom`、`ta_roc`、`ta_rsi`、`ta_atr(high,low,close,d)`、
`ta_adx(high,low,close,d)`、`ta_cci(high,low,close,d)`、`ta_bbands_u/m/l(close,d)`、
`ta_bias(close,d)`、`ta_macd_dif/dea/hist(close)`、`ta_kdj_k/d/j(high,low,close)`、
`ta_willr`、`ta_trix`。其中布林带拆为 `ta_bbands_u(close,d)`、`ta_bbands_m(close,d)`、
`ta_bbands_l(close,d)`；MACD 拆为 `ta_macd_dif`、`ta_macd_dea`、`ta_macd_hist`；
KDJ 拆为 `ta_kdj_k`、`ta_kdj_d`、`ta_kdj_j`。实现基于可选依赖 talib/pandas-ta，
注册表挂载。

### 6.4 处理管线（process）

`process:` 链为可插拔步骤，顺序执行于因子表达式之后：

- `winsorize(quantile=0.99)` 或 `winsorize(std=3)`：截面去极值。
- `standardize()`：截面 z-score。
- `zscore()`：`standardize` 别名。
- `csranknorm()`：截面排名归一化到 [0,1]。
- `robustzscore()`：中位数/MAD 稳健标准化。
- `neutralize(by: industry | market | size)`：截面中心化。`industry` 用
  `stock_basic_tushare.industry`，`size` 用 `daily_basic.total_mv`，`market` 为全市场 demean。
- `clip(lower, upper)`：截断。
- `fillna(method: industry_mean | value | forward)`：缺失值处理。

处理步骤同样经注册表实现，新增步骤不改主流程。

### 6.5 新算子扩展（双通道 + 版本钉住）

**通道 1：DSL 内宏组合**。spec 内联 `operators` 或本地算子库定义，解析期展开：

```yaml
operators:
  event_decay:
    params: [x, n]
    formula: "ts_mean(x, n) / delay(ts_mean(x, n), n)"
```

**通道 2：Python 算子插件**。组合表达不了的新语义写小函数挂注册表：

```python
from factorlab.ops.registry import factor_op

@factor_op("event_decay", kind="ts", version="0.1.0")
def event_decay(x: pd.Series, n: int, *, ctx) -> pd.Series:
    ...
```

注册时声明算子类别（`el/ts/cs/group/ta`），引擎据此选择分区语义。
`factorlab op list` 查看全部已注册算子，`factorlab op doc <name>` 查看签名与文档。

**版本钉住**：每次计算结果记录所用算子集与处理链的版本快照
（每个算子 name→version 映射 + 注册表总体版本）；算子实现变更后历史结果不变，重跑可复现。

### 6.6 防未来函数

引擎层保证，不依赖用户自觉：

- TS 算子一律使用截至当前行的历史窗口，禁止前视窗口。
- 嵌套 `CS(TS(...))`、`TS(CS(...))` 自动拆为中间列并物化，避免分区语义歧义。
- 评估某日 T 的因子值只使用 ≤ T 的数据；前向收益取自 T 之后，不参与因子计算。
- 处理链只做同日截面变换；`neutralize` 不引入未来数据。
- 数据加载时按交易日历补全停牌记录，避免滚动窗口错位（对齐 AKQuant 语义）。

## 7. 评估指标插件

接口：

```python
class Metric:
    name: str
    def compute(self, df: pd.DataFrame, ctx: EvalContext) -> dict: ...
```

v1 指标：

- `rank_ic` / `pearson_ic`：调 `quant_core.evaluate_factor`。
- `decile_returns`：十分位收益与单调性。
- `turnover`：月度/季度换手率。
- `coverage`：本地计算（有效行占比、股票覆盖数）。
- `layered_backtest`：分层组合累计净值曲线（等权，含 long-short）。
- `factor_compare`：多个因子 IC 相关矩阵与两两对比报告。
- `composite`：IC 加权/等权合成复合因子并评估。

指标经注册表按 name 调用；后续信息增益率、残差分析等作为新 Metric 挂入，不改主流程。
评估目标（前向收益）来源：v1 从本地 `daily` 的 close 自行计算并周频对齐；
`quant_factor.duckdb.factor_weekly` 仅作测试交叉验证，不做运行时依赖。

## 8. CLI 命令

| 命令 | 说明 |
|------|------|
| `factorlab run <spec>` | 解析、计算、处理、评估、落盘 |
| `factorlab list` | 列出已保存因子与最近运行 |
| `factorlab show <name>` | 查看某因子摘要与指标 |
| `factorlab compare <name...>` | 多因子对比报告与相关矩阵 |
| `factorlab serve [--port]` | 启动 Web 可视化 |
| `factorlab data refresh [--start] [--end]` | teajoin 增量补数据到平台缓存库 |
| `factorlab op list` | 列出注册算子 |
| `factorlab op doc <name>` | 查看算子签名与文档 |

## 9. Web 可视化（FastAPI + Jinja2 + Plotly）

- `/`：因子列表（名称、类别、方向、最近运行时间、IC 摘要）。
- `/factor/<name>`：因子详情——IC 曲线、十分位收益柱状图、分层回测累计净值曲线、
  覆盖度、spec 原文、算子版本快照。
- `/compare?names=...`：多因子 IC 相关矩阵热力图与两两对比。
- 结果只读自平台结果目录，无需写数据库。

## 10. 错误处理

- DSL 语法/语义错误：明确信息 + 行列号；未知算子给出相似算子建议。
- 算子类别错误：如把横截面算子当元素级使用，报错并给出正确用法。
- 空 universe / 无有效股票：报错并提示检查 `codes` 或 `rules`。
- 数据缺失：提示该日期段本地缺失，可运行 `factorlab data refresh`。
- teajoin 限流/网络错误：指数退避重试（上限 3 次），保留进度可断点续传。
- 评估数据不足（有效行过少）：返回指标为 null 并在摘要中标注，不中断流程。

## 11. 测试策略

- 解析器单测：语法正确性、错误行列号、let/def 作用域、宏展开、三元与布尔优先级。
- 算子数值单测：TS/CS/EL/group 算子与 pandas/numpy 原生实现逐值对照。
- TA 算子对拍：与 talib（可用时）逐值对照，容差内一致。
- Alpha101/191 语料对拍：626 条公式在样本数据上运行不报错，并与本地已实现因子交叉验证。
- 引擎黄金用例：用现有 `factor_weekly` 中的已知因子（如 `value_reversal_20d`）
  在相同输入下对拍，误差阈值内一致。
- 防未来函数测试：构造停牌/缺失数据，验证滚动窗口与前瞻收益不串期。
- 处理管线单测：每个 process 步骤的截面统计性质。
- 评估集成测试：小样本调 `quant_core.evaluate_factor`，核对返回结构。
- CLI 端到端：`run → list → show → compare` 冒烟。
- Web smoke test：`/`、`/factor/<name>`、`/compare` 返回 200。

## 12. 复用清单

| 资产 | 用途 |
|------|------|
| `quant_core`（PyO3 已装） | IC/十分位/换手/覆盖率评估 |
| `quant.duckdb`（只读） | daily、stock_basic_tushare 数据源 |
| `quant_tushare_full.duckdb`（可选只读） | 更全历史数据源 |
| `quant_factor.duckdb`（只读，测试用） | 已知因子对拍、forward return 交叉验证 |
| JoinQuant 公式目录（CSV/JSON，626 条） | 算子命名参考 + Alpha101/191 回归语料 |
| talib / pandas-ta（可选） | TA 算子实现与数值对拍 |
| teajoin API key | 增量补数据 |

## 13. 里程碑

1. M1：项目骨架 + DSL 词法/语法/校验（let/def/作用域）+ 算子注册表。
2. M2：TS/CS/EL/group 算子 + 引擎分区与中间物化 + 防未来函数。
3. M3：数据层（DuckDB 只读 + teajoin 增量）+ 前向收益 + 处理管线。
4. M4：评估指标 + 分层回测 + 因子对比 + 组合合成 + CLI 全命令。
5. M5：Web 可视化。
6. M6：Alpha101/191 语料对拍 + TA 对拍 + 文档。

详细拆分见实施计划（writing-plans 产物）。

## 14. 未来扩展（v2 候选）

- 因子库管理后台（注册、分级、对比、淘汰）。
- 信息增益率、残差诊断等统计指标（算子已内置，指标插件预留）。
- 风格中性化（size/beta 等更多维度）。
- DSL 编译进 Rust 引擎（高性能路径）。
- 事件驱动 / 跨资产 context 语法。
- Web 端 DSL 编辑与实时预览。
- 多用户与权限。
