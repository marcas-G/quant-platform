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
- `expr_codegen` / `polars_ta`：TS/CS/GP 表达式自动分层、公共子表达式消除、
  Polars 原生算子库，作为 v1 计算内核。
- `FastPlus` / `KunQuant`：WorldQuant Fast Expression 解析与 C++ 编译后端，
  分别作为可选校验器和 v2 高性能路径。

## 2. 范围

### v1 包含

- 声明式 DSL：YAML 元数据 + `expr_codegen` 受限 Python 因子块（赋值、自定义函数、
  条件逻辑、注释、无循环/副作用）。
- 算子集：复用 `polars_ta` 的 `wq/ta/tdx/talib` 算子族，平台补别名与薄封装；
  Alpha101/191 语料作为兼容性回归目标。
- 处理管线：表达式之后独立执行 `winsorize / zscore / csranknorm / robustzscore /
  neutralize / clip / fillna`。
- `expr_codegen` 解析并生成 Polars 执行图；TS/CS/GP 算子自动分层、嵌套表达式中间物化、防未来函数。
- 评估：RankIC / PearsonIC / 十分位收益 / 覆盖度 / 换手率（复用 Rust `quant_core`），
  叠加分层回测累计净值、因子对比、组合合成。
- 因子与结果本地存储（parquet + JSON 摘要 + 算子版本快照）。
- 运行时内存护栏：SQL-first、float32、分块执行、RSS 熔断、独立评估进程。
- CLI：`run / list / show / compare / serve / data refresh / op list / op doc /
  op add / op remove`。
- Web 可视化：FastAPI + Jinja2 + Plotly。
- 新算子扩展：公式内 `def`/白名单 `import` + Python 算子插件注册表 + DSL 宏。
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
| 引擎 | `expr_codegen` + `polars_ta` 生成并执行 Polars 因子；评估复用 Rust `quant_core` |
| 数据范围 | 自选股票池；全 A 是可选范围而非默认加载量 |
| 历史深度 | DSL 内 `date.start/end` 可调 |
| 过滤位置 | universe 是 DSL 一等公民（显式列表或规则），数据层按需拉取 |
| 内存策略 | SQL-first + float32 + 分块执行 + 独立评估进程；CLI 可设内存/分块预算，超限拒绝启动 |
| DSL 文件 | YAML 元数据 + `expr_codegen` 受限 Python 因子块（赋值/def/条件，无循环） |
| 算子集 | 复用 `polars_ta` wq/ta/tdx/talib 算子族 + 平台别名/薄封装；Alpha101/191 兼容 |
| 新算子 | 公式内 `def`/白名单 `import` + Python 插件注册表，带版本钉住 |
| 处理管线 | 表达式后独立 process 链（对齐 qlib processors） |
| 评估产出 | 因子值 + IC/分层/换手 + 分层回测净值 + 因子对比 + 组合合成 |
| Web 栈 | FastAPI + Jinja2 + Plotly |

## 4. 开源组件选型与复用边界

原则：数值内核尽量复用经过测试的开源实现，我们只自研“产品编排层”和因子平台特有的 glue。以下选型已核对许可证、
Python 3.13 / Windows 可用性与当前环境兼容性。

### 4.1 v1 运行时依赖（采用）

| 组件 | 用途 | 许可证 | 状态 | 备注 |
|------|------|--------|------|------|
| `expr_codegen` 0.16.6 | 受限 Python 因子块 → Polars 代码；TS/CS/GP 自动分组、公共子表达式消除、中间列物化 | BSD-3-Clause | 采用 | 纯 Python wheel，`requires_python>=3.9`；核心替代自研 lexer/parser/engine 分区 |
| `polars_ta` 0.5.17 | WorldQuant `wq` / `ta` / `tdx` / `talib` 算子族，输出 `pl.Expr` | MIT | 采用 | 纯 Python wheel，`requires_python>=3.8`；替代自研 80-90 个算子实现 |
| `polars` 1.38.0 | 因子面板计算与分组 | MIT | 已安装 | 与 `expr_codegen`/`polars_ta` 同一生态 |
| `duckdb` 1.5.3 | 本地只读数据库 SQL 过滤与加载 | MIT | 已安装 | 平台不改 `quant-data` 任何文件 |
| `pyarrow` 24.0.0 | parquet 结果落盘 | Apache-2.0 | 已安装 | |
| `quant_core` 0.1.0 | RankIC / PearsonIC / 十分位收益 / 换手率 | 本地 PyO3 | 已安装 | 保留为评估内核 |
| `TA-Lib` 0.7.1 | `talib` 精确语义技术指标与数值对拍 | BSD | 可选 | PyPI 0.7.1 提供 Windows cp313 wheel；缺省时 `polars_ta.ta/tdx` 仍可用 |
| `fastapi`/`uvicorn`/`jinja2`/`plotly` | Web 可视化 | MIT/BSD | 已安装 | |
| `typer`/`rich`/`pydantic-settings` | CLI、进度输出、配置 | MIT | 已安装 | |
| `sympy` 1.14.0 | `expr_codegen` 表达式化简与 CSE | BSD | 已安装 | 传递依赖 |

### 4.2 不纳入 v1 运行时，但复用/参考（或作为未来后端）

| 组件 | 角色 | 许可证 | 决定 |
|------|------|--------|------|
| `FastPlus` (`py-fastplus` 0.3.5) | WorldQuant Fast Expression 解析/签名校验 | MIT | 仅作开发期算子签名目录与兼容性参考；不进入 v1 主解析路径，避免双解析器 |
| `KunQuant` 0.1.11 | 因子表达式 → C++ 编译执行 | Apache-2.0 | 预留 v2 高性能后端；当前机器无 MSVC/g++，v1 不装 |
| `microsoft/qlib` | 表达式算子与 processor 语义 | MIT | 不直接依赖（数据格式不匹配 DuckDB），借用其 process/回归算子语义并在平台侧复现 |
| `HKUDS/Vibe-Trading` Alpha Zoo | 462 因子语料、lookahead 哨兵测试、bench/compare 参考 | MIT | 用作测试语料和基准参考；不运行时集成 |
| `CharlesJ-ABu/FactorMiner` V4 | 因子挖掘工作台架构 | MIT | 仅架构参考，不整体 fork |
| `alphalens-reloaded` 0.4.6 | 因子 tearsheet | Apache-2.0 | v1 不采用：官方约束 pandas<3.0，本机为 pandas 3.0.2；保留为后续隔离环境选项 |
| `pandas-ta` 及社区 fork | 技术指标 | 混杂/维护弱 | 由 `polars_ta` + `TA-Lib` 替代 |
| `tushare` SDK | Tushare 数据客户端 | 未知/BSD | 不采用：其 endpoint 硬编码为 `api.waditu.com/dataapi`，teajoin 需自定义 HTTP 客户端 |

### 4.3 自研边界

必须自研的部分是平台语义，不重复数值内核：

- YAML Spec 数据模型与校验（name/category/universe/date/target/process/version）。
- 因子脚本 AST 白名单安全校验（禁止循环、副作用、外部 IO/网络），以及 DSL 错误定位。
- DuckDB 只读数据层、universe 过滤、teajoin 增量拉取与平台缓存。
- process 链注册表（winsorize/zscore/neutralize 等），用 Polars 表达式实现。
- 算子注册表、用户插件目录 `~/.factorlab/plugins` 的加载/启停、别名映射、
  平台特有算子（returns/vwap/adv20 等薄封装）与版本快照。
- 评估编排：调 `quant_core`，外加分层回测、因子对比、组合合成。
- 运行时资源治理：SQL-first 取数、float32 列裁剪、分块执行、RSS 熔断、独立评估进程。
- CLI、Web、结果持久化与版本追溯。

## 5. 架构

```
quant-platform/
├── pyproject.toml
├── README.md
├── .gitignore
├── docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md
├── src/factorlab/
│   ├── __init__.py
│   ├── config.py            # pydantic-settings 路径与环境变量（DuckDB、teajoin key、插件目录等）
│   ├── spec.py              # YAML Spec 数据模型与字段校验
│   ├── factor/
│   │   ├── loader.py        # 读取 YAML + formula Python 代码块
│   │   ├── ast_gate.py      # AST 白名单校验（禁循环/副作用/外部 IO）
│   │   ├── codegen.py       # 把受限 Python 因子块送入 expr_codegen
│   │   └── errors.py        # DSL 错误统一包装（含源码位置）
│   ├── ops/
│   │   ├── registry.py      # factor_op 注册表、别名映射、版本
│   │   ├── plugins.py       # ~/.factorlab/plugins 发现、加载、启停
│   │   ├── polars_ta_wrappers.py  # 适配 polars_ta wq/ta/tdx/talib 族
│   │   ├── platform_ops.py  # returns/vwap/adv20 等平台薄封装
│   │   └── macros.py        # 内置宏算子
│   ├── process/
│   │   ├── registry.py      # 处理步骤注册表
│   │   └── processors.py    # winsorize/zscore/csranknorm/robustzscore/neutralize/clip/fillna
│   ├── data/
│   │   ├── source.py        # 本地 DuckDB 只读 -> Polars LazyFrame
│   │   ├── teajoin.py       # Tushare 兼容 HTTP 客户端（限流、重试）
│   │   ├── universe.py      # universe 解析（显式列表 / 规则过滤）
│   │   └── cache.py         # 平台自有缓存（parquet + duckdb）
│   ├── engine/
│   │   ├── compute.py       # 组装数据 -> expr_codegen -> 因子面板
│   │   ├── partitions.py    # 记录/校验 TS/CS/GP 分区，防未来函数断言
│   │   ├── memory.py        # 内存预算、RSS 监控、分块计划、超限熔断
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
│   │   └── versions.py      # 算子集/依赖版本快照
│   ├── cli/
│   │   └── main.py          # typer CLI
│   └── web/
│       ├── app.py           # FastAPI 应用
│       ├── templates/       # Jinja2 模板
│       └── static/          # plotly.js 等静态资源
├── tests/
│   ├── conftest.py
│   ├── test_spec_ast_gate.py # YAML Spec 与 AST 白名单
│   ├── test_codegen.py       # expr_codegen 分层/CSE/错误定位
│   ├── test_ops.py
│   ├── test_process.py
│   ├── test_engine.py
│   ├── test_alpha_corpus.py # Alpha101/191 公式对拍
│   ├── test_ta_ops.py       # TA 算子与 talib 数值对拍
│   ├── test_eval.py
│   └── test_cli.py
```

依赖（Python 3.13）：`polars`、`pandas`、`numpy`、`duckdb`、`pyarrow`、`pyyaml`、
`expr_codegen`、`polars_ta`、`sympy`、`typer`、`fastapi`、`uvicorn`、`jinja2`、
`plotly`、`requests`、`pydantic-settings`、`psutil`，以及已安装的 `quant_core`。
`TA-Lib` 作为可选依赖，缺省时 `polars_ta.ta/tdx` 仍可用；需要 talib 精确对拍的
`talib` 族算子会给出明确提示。

## 6. 数据流

```
factorlab run spec.yaml
  → 解析 YAML Spec 与 formula Python 代码块
  → AST 白名单校验（无循环/副作用/外部 IO；算子名与列名预检）
  → 内存预算预估（行数×列数×dtype×分组系数），超限则拒绝
  → 解析 universe（显式列表 / 规则过滤，查 stock_basic_tushare）
  → 加载数据：本地 quant.duckdb 只读，DuckDB SQL 过滤后转为 Polars LazyFrame；
    缺日期段时 teajoin 增量补到平台缓存库
  → expr_codegen 对 TS/CS/GP 表达式分层，生成 Polars 计算图并按 chunk 执行；
    嵌套分区自动中间物化，时序窗口只回溯
  → 处理管线：winsorize → zscore/neutralize 等 process 链
  → 计算前向收益（daily close），按周频对齐（匹配 Rust 评估语义）
  → 先落 parquet，再由独立进程调 quant_core 评估 + 分层回测 + 本地轻量指标
  → 结果落盘：parquet（因子值）+ JSON（摘要/指标/回测曲线/算子与依赖版本快照）
  → factorlab serve 起 Web 展示
```

平台不修改 `quant-data` 下任何文件；本地 DuckDB 一律只读打开。

### 6.1 运行时内存预算与低内存执行

当前目标机器约 16 GB 物理内存且无页面文件（`SizeStoredInPagingFiles=0`），
因此平台把“避免默认爆内存”作为运行时硬约束，而不是依赖用户自觉。

执行策略：

- **SQL-first 取数**：先用 DuckDB 按 `date / universe / 需要的列` 过滤和聚合，
  再转 Polars LazyFrame；禁止无过滤地把 `quant.duckdb.daily` 整体 `fetchdf()` 或 `.pl()`。
- **列裁剪与 dtype**：因子面板默认 `float32`；只读取因子表达式实际引用的 OHLCV 字段，
  用完的原始列和中间列立即释放。
- **DuckDB 内存上限**：每次只读连接设置 `memory_limit`（默认 4GB）和 `threads`（默认 2），
  避免 DuckDB 抢占系统 commit headroom。
- **Arrow 内存池**：进程启动时设置 `pyarrow.set_memory_pool(pyarrow.system_memory_pool())`。
- **分块计划**：TS/EL 类因子按股票代码分批；含 CS/GP 的因子在 TS/EL 中间结果落盘后，
  再按日期分批做横截面。长窗口不直接在全市场宽表上连续滚动。
- **独立评估进程**：因子计算与 `quant_core` 评估分两个进程。先写 parquet 结果，
  再由评估进程读 parquet 计算 IC/分层/换手，避免两个阶段峰值叠加。
- **运行前预算**：`engine/memory.py` 根据 `行数 × 列数 × dtype × 分组系数` 预估峰值；
  超过 `--max-memory` 时拒绝启动，提示缩小 universe、日期范围或换 chunk size。
- **运行中熔断**：用 `psutil` 监控 RSS，达到预算阈值后中止并给出明确错误，
  不等待系统级 `MemoryError` 或进程被 Windows 杀死。

CLI 默认值：`--max-memory 4GB`、`--chunk-size 1000`、`--float32` 开启；
用户可显式调高，但超出机器实际可用内存时给出警告并要求 `--force`。

## 7. DSL 规范

### 7.1 Spec 文件（YAML + 脚本）

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
  # formula 是受白名单限制的 Python 代码块，交给 expr_codegen 转 Polars。
  # 以 _ 开头的变量为中间变量，最终保留 signal 作为因子输出。
  from factorlab.ops.platform import returns, vwap, adv20
  from factorlab.ops.compat import ts_mean, ts_median, ts_std, delay, rank, zscore

  def momentum(x, n):
      return delay(x, n) / delay(x, 2 * n) - 1

  _ret = returns(close)
  _vol = ts_std(_ret, 20)
  _cond = (_vol < ts_median(_vol, 60)) & (close > delay(close, 5))
  signal = rank(momentum(close, 5) - zscore(_vol)) - 0.5
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
- `formula` 为受限制的 Python 代码块，最终保留列名 `signal` 作为因子输出。
  多因子组合时 `factors[].formula` 各自独立，最终由 `combine` 聚合。

### 7.2 脚本语法

- 采用 `expr_codegen` 支持的受限 Python 子集，不是自造语法：
  赋值、`def` 自定义函数、`class`、`import`（仅允许白名单模块）、
  Python 表达式、`a if cond else b` 三元、`& | ~` 布尔运算、`#` 注释。
- 以 `_` 开头的变量为中间变量，最终从输出中剔除；非下划线变量成为因子输出列，
  v1 约定单因子最终输出名为 `signal`。
- 禁止循环（`for/while`）、`yield`、`lambda` 中副作用、文件/网络/子进程/系统调用、
  任意属性访问。平台在编译前用 AST 白名单校验，违反时报错并给出源码位置。
- 表达式/变量名/算子名预检：未知列或未知算子给出相似名称建议（difflib）。

### 7.3 算子命名与分类

算子实现复用 `polars_ta`，平台负责命名兼容与薄封装，不重复实现数值内核。

- 时序 / 横截面 / 分组：采用 WorldQuant 风格前缀 `ts_*`、`cs_*`、`gp_*`，
  由 `polars_ta.prefix.wq` 提供；平台别名映射保证常用写法兼容：
  `ts_mean/ts_std/ts_sum/ts_rank/ts_corr`、`rank/zscore/cs_rank/cs_zscore`、
  `group_rank/group_mean/group_zscore` 等。
- 技术指标：`polars_ta.prefix.ta`（Polars 风格）和 `prefix.tdx`（A 股常用指标）；
  需要 TA-Lib 精确语义时，`polars_ta.prefix.talib` 按原版签名调用。
- 元素级运算直接用 Python/Polars 语义：`abs/log/sqrt`、`where/if_else`、算术与比较。
- 平台薄封装仅用于已有库未覆盖或需要平台语义的少数算子：`returns`、`vwap`、`adv20`、
  以及 `cross` 等组合宏。
- Alpha101/191 语料作为兼容性测试，运行前将公式映射到上述算子；缺少数值等价算子时
  先以平台宏/插件补齐，而不是改写公式含义。

### 7.4 处理管线（process）

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

### 7.5 新算子扩展（三层 + 版本钉住）

**第 1 层：公式内 `def`/白名单 `import`**。单次使用的新算子直接在 formula 代码块里定义，
经 AST 白名单校验后原样交给 `expr_codegen`，不进入全局注册表。

**第 2 层：DSL 内宏组合**。spec 内联 `operators` 或本地算子库定义，解析期展开：

```yaml
operators:
  event_decay:
    params: [x, n]
    formula: "ts_mean(x, n) / delay(ts_mean(x, n), n)"
```

**第 3 层：Python 算子插件**。可复用、需要版本钉住的新语义写小函数挂注册表：

```python
import polars as pl

from factorlab.ops.registry import factor_op

@factor_op("event_decay", kind="ts", version="0.1.0")
def event_decay(x: pl.Expr, n: int) -> pl.Expr:
    return x.rolling_mean(window_size=n)
```

注册时声明算子类别（`el/ts/cs/group/ta`），并生成 `ts_event_decay` /
`cs_event_decay` 等前缀入口，`expr_codegen` 据此自动分组。
用户插件统一放入 `~/.factorlab/plugins/`，通过 CLI 管理生命周期：

```bash
factorlab op add ./my_ops.py     # 校验并注册插件文件；冲突时要求 --force
factorlab op remove tail_ratio   # 从用户插件清单移除并禁止后续加载
factorlab op list                # 列出内置 + 用户插件算子及版本
factorlab op doc tail_ratio      # 查看签名、类别、版本与文档字符串
```

`op add` 只接受白名单目录中的 `.py` 文件；插件导入前做 AST 安全扫描，
注册表只暴露返回 `pl.Expr` 的纯函数。移除操作保留已计算历史结果和版本快照，
只影响后续新运行。

**版本钉住**：每次计算结果记录所用算子集与处理链的版本快照
（每个算子 name→version 映射 + `expr_codegen` / `polars_ta` / `TA-Lib` 版本 +
注册表总体版本）；算子实现变更后历史结果不变，重跑可复现。

### 7.6 防未来函数

引擎层保证，不依赖用户自觉：

- 由 `expr_codegen` 依据 `ts_/cs_/gp_` 前缀自动分层；TS 算子按
  `sort([ASSET, DATE]).groupby(ASSET)` 执行，Polars 滚动窗口仅使用历史区间。
- 嵌套 `CS(TS(...))`、`TS(CS(...))` 自动拆为中间列并物化，避免分区语义歧义。
- 评估某日 T 的因子值只使用 ≤ T 的数据；前向收益取自 T 之后，不参与因子计算。
- 处理链只做同日截面变换；`neutralize` 不引入未来数据。
- 数据加载时按交易日历补全停牌记录，避免滚动窗口错位（对齐 AKQuant 语义）。
- 平台在 `engine/partitions.py` 对生成的执行计划做断言：任何 TS 窗口不得出现
  未来行引用；发现违规直接失败并定位表达式。

## 8. 评估指标插件

接口：

```python
import polars as pl

class Metric:
    name: str
    def compute(self, df: pl.DataFrame, ctx: EvalContext) -> dict: ...
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
`alphalens-reloaded` 不进入 v1 运行时（其 pandas<3.0 约束与本机 pandas 3.0.2 冲突），
如需成熟 tearsheet，可在后续用隔离环境或 vendor 兼容实现。

## 9. CLI 命令

| 命令 | 说明 |
|------|------|
| `factorlab run <spec> [--max-memory 4GB] [--chunk-size 1000] [--float32/--float64] [--force]` | 解析、计算、处理、评估、落盘；超预算默认拒绝 |
| `factorlab lint <spec>` | 预检 YAML/AST/算子，报告源码位置与相似名称建议 |
| `factorlab list` | 列出已保存因子与最近运行 |
| `factorlab show <name>` | 查看某因子摘要与指标 |
| `factorlab compare <name...>` | 多因子对比报告与相关矩阵 |
| `factorlab serve [--port]` | 启动 Web 可视化 |
| `factorlab data refresh [--start] [--end]` | teajoin 增量补数据到平台缓存库 |
| `factorlab op list` | 列出注册算子 |
| `factorlab op doc <name>` | 查看算子签名与文档 |
| `factorlab op add <plugin.py> [--force]` | 校验并注册用户算子插件 |
| `factorlab op remove <name>` | 从用户插件清单移除算子，保留历史结果 |

## 10. Web 可视化（FastAPI + Jinja2 + Plotly）

- `/`：因子列表（名称、类别、方向、最近运行时间、IC 摘要）。
- `/factor/<name>`：因子详情——IC 曲线、十分位收益柱状图、分层回测累计净值曲线、
  覆盖度、spec 原文、算子版本快照。
- `/compare?names=...`：多因子 IC 相关矩阵热力图与两两对比。
- 结果只读自平台结果目录，无需写数据库。

## 11. 错误处理

- AST 白名单违规（循环/副作用/外部 IO）：报错并给出源码位置。
- DSL 语法/语义错误：包装 `expr_codegen`/`sympy` 异常，输出源码位置；
  未知列或算子给出相似名称建议。
- 算子类别错误：如把横截面算子当元素级使用，报错并给出正确前缀用法。
- 空 universe / 无有效股票：报错并提示检查 `codes` 或 `rules`。
- 数据缺失：提示该日期段本地缺失，可运行 `factorlab data refresh`。
- 内存预算不足：在启动前给出预估峰值、当前 `--max-memory` 和建议的缩小方案；
  运行中 RSS 接近阈值时中止并提示，而不是等待系统内存错误。
- teajoin 限流/网络错误：指数退避重试（上限 3 次），保留进度可断点续传。
- 评估数据不足（有效行过少）：返回指标为 null 并在摘要中标注，不中断流程。

## 12. 测试策略

- AST 白名单单测：合法 assignment/def/import/三元通过；循环、文件/网络/系统调用被拒。
- 解析/错误定位单测：未知列、未知算子、作用域错误返回源码位置与相似名称建议。
- 算子数值单测：`polars_ta` 的 `ts_/cs_/gp_` 结果与 pandas/numpy 原生实现逐值对照。
- TA 算子对拍：`polars_ta.ta/tdx/talib` 与 TA-Lib（可用时）逐值对照，容差内一致。
- Alpha101/191 语料对拍：626 条公式在样本数据上运行不报错，并与本地已实现因子交叉验证。
- `expr_codegen` 生成代码黄金用例：校验 TS/CS/GP 分层与公共子表达式消除后结果一致。
- 引擎黄金用例：用现有 `factor_weekly` 中的已知因子（如 `value_reversal_20d`）
  在相同输入下对拍，误差阈值内一致。
- 防未来函数测试：构造停牌/缺失数据，验证滚动窗口与前瞻收益不串期，
  并断言执行计划不含未来行引用。
- 内存护栏测试：用预算预估器验证超限拒绝、chunk 计划正确、RSS 熔断触发；
  小样本下确认 TS/EL 分块结果与全量结果一致。
- 处理管线单测：每个 process 步骤的截面统计性质。
- 评估集成测试：小样本调 `quant_core.evaluate_factor`，核对返回结构。
- 插件生命周期测试：`op add/remove/list/doc`，含冲突、AST 拒绝、版本快照保留。
- CLI 端到端：`run → list → show → compare` 冒烟。
- Web smoke test：`/`、`/factor/<name>`、`/compare` 返回 200。

## 13. 复用清单

| 资产 | 用途 |
|------|------|
| `expr_codegen` / `polars_ta` | DSL 解析、TS/CS/GP 分层、算子实现与 Polars 代码生成 |
| `TA-Lib`（可选） | talib 精确语义技术指标与数值对拍 |
| `quant_core`（PyO3 已装） | IC/十分位/换手/覆盖率评估 |
| `quant.duckdb`（只读） | daily、stock_basic_tushare 数据源 |
| `quant_tushare_full.duckdb`（可选只读） | 更全历史数据源 |
| `quant_factor.duckdb`（只读，测试用） | 已知因子对拍、forward return 交叉验证 |
| JoinQuant 公式目录（CSV/JSON，626 条） | 算子命名参考 + Alpha101/191 回归语料 |
| Vibe-Trading Alpha Zoo 语料 | 462 因子兼容性/基准/lookahead 哨兵测试参考 |
| teajoin API key | 增量补数据 |

## 14. 里程碑

1. M1：项目骨架 + YAML Spec 模型 + AST 白名单校验 + `expr_codegen` 接入 + 算子注册表。
2. M2：`polars_ta` 算子适配/别名 + TS/CS/GP 分区验证 + 防未来函数。
3. M3：数据层（DuckDB 只读 + teajoin 增量）+ 前向收益 + 处理管线。
4. M4：评估指标 + 分层回测 + 因子对比 + 组合合成 + CLI 全命令。
5. M5：Web 可视化。
6. M6：Alpha101/191 与 Vibe-Trading Alpha Zoo 语料对拍 + TA 对拍 + 文档。

详细拆分见实施计划（writing-plans 产物）。

## 15. 未来扩展（v2 候选）

- 因子库管理后台（注册、分级、对比、淘汰）。
- 信息增益率、残差诊断等统计指标（算子已内置，指标插件预留）。
- 风格中性化（size/beta 等更多维度）。
- 可选高性能后端：安装 MSVC 后接 `KunQuant` 或 `FastPlus.compile()`，用编译后代码替换 Polars 执行。
- 事件驱动 / 跨资产 context 语法。
- Web 端 DSL 编辑与实时预览。
- 多用户与权限。
