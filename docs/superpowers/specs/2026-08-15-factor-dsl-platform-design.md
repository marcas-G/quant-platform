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
- JoinQuant 公式目录：626 条公式（Alpha101/Alpha191/技术指标），算子风格对标 WorldQuant/JoinQuant。
- teajoin.com Tushare 兼容代理：已验证可用（API Key 已兑换，到期 2026-08-22），
  用于增量补数据（450 次/分钟，建议间隔 0.2s）。

目标：在 `quant-platform/` 从零构建一个**更规范的因子 DSL 计算平台**——个人使用、单机运行、
命令行提交声明式因子 DSL、本地计算因子值与基础评估、Web 展示结果。

## 2. 范围

### v1 包含

- 声明式 DSL（YAML spec + 公式字符串），对标 WorldQuant/JoinQuant 算子体系。
- Python 引擎解析 DSL 并计算因子（按 code 分组、pandas 向量化）。
- 评估指标插件：RankIC / PearsonIC / 十分位收益 / 覆盖度 / 换手率（复用 Rust `quant_core`）。
- 因子与结果本地存储（parquet + JSON 摘要 + 算子版本快照）。
- CLI：`run / list / show / serve / data refresh / op list / op doc`。
- Web 可视化：FastAPI + Jinja2 + Plotly。
- 新算子双通道扩展：DSL 内宏组合 + Python 算子插件注册表。
- 数据源：本地 DuckDB（只读）为主，teajoin 增量补数据到平台自有缓存库。

### v1 明确不做

- 多用户 / 权限 / 计费。
- 实时行情、分钟线。
- DSL 编译进 Rust（`cargo build` 集成）。
- 行业中性化算子（`industry_neutral`，v2）。
- Web 端编辑 DSL。
- 因子库管理后台（S1/S2 分级、R²/信息增益率/残差分析——v2，架构上已预留）。

## 3. 已确认的关键决策

| 主题 | 决策 |
|------|------|
| 使用形态 | 个人工具，单机 |
| 交互 | CLI 为主，Web 只做结果可视化 |
| 引擎 | Python 解析 DSL 并计算；评估复用 Rust `quant_core` |
| 数据范围 | 自选股票池；全 A 是可选范围而非默认加载量 |
| 历史深度 | DSL 内 `date.start/end` 可调 |
| 过滤位置 | universe 是 DSL 一等公民（显式列表或规则），数据层按需拉取 |
| DSL 文件 | YAML spec + formula 字符串 |
| 算子集 | 对标 WorldQuant/JoinQuant（约 45 个 v1 算子），注册表实现 |
| 新算子 | 宏组合（不写代码）+ Python 插件（注册表），带版本钉住 |
| Web 栈 | FastAPI + Jinja2 + Plotly |
| 产出 | 因子值面板 + 基础评估；评估指标插件化，为 R²/信息增益/残差预留 |

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
│   │   ├── lexer.py         # 词法分析
│   │   ├── parser.py        # 递归下降 -> AST
│   │   ├── ast.py           # AST 节点
│   │   ├── expand.py        # 宏展开（spec 内联 + 本地算子库）
│   │   ├── validate.py      # 语义校验（算子存在、参数个数、列名）
│   │   └── errors.py        # DSLParseError（带行列号）
│   ├── ops/
│   │   ├── registry.py      # @factor_op 注册表（名称、实现、版本）
│   │   ├── math_ops.py      # 数学/基础算子
│   │   ├── ts_ops.py        # 时序算子
│   │   ├── cs_ops.py        # 横截面算子
│   │   └── macros.py        # 内置宏算子
│   ├── data/
│   │   ├── source.py        # 本地 DuckDB 只读读取（daily、stock_basic_tushare）
│   │   ├── teajoin.py       # Tushare 兼容 HTTP 客户端（限流、重试）
│   │   ├── universe.py      # universe 解析（显式列表 / 规则过滤）
│   │   └── cache.py         # 平台自有缓存（parquet + duckdb）
│   ├── engine/
│   │   ├── compute.py       # AST -> 按 code 分组计算 -> date×code×value 面板
│   │   └── forward.py       # 前向收益计算与周频对齐
│   ├── eval/
│   │   ├── base.py          # Metric 抽象接口
│   │   ├── registry.py      # 指标注册表
│   │   ├── rust_ic.py       # quant_core.evaluate_factor 桥接
│   │   └── metrics.py       # 轻量指标（coverage 等，本地实现）
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
│   ├── test_engine.py
│   ├── test_eval.py
│   └── test_cli.py
```

依赖（Python 3.13）：`pandas`、`numpy`、`duckdb`、`pyyaml`、`typer`、`fastapi`、
`uvicorn`、`jinja2`、`plotly`、`requests`，以及已安装的 `quant_core`。

## 5. 数据流

```
factorlab run spec.yaml
  → 解析 YAML + formula（lexer/parser）
  → 宏展开 + 语义校验
  → 解析 universe（显式列表 / 规则过滤，查 stock_basic_tushare）
  → 加载数据：本地 quant.duckdb 只读；缺日期段时 teajoin 增量补到平台缓存库
  → 引擎按 code 分组执行 AST，得到 date×code×value 因子面板
  → 计算前向收益（daily close），按周频对齐（匹配 Rust 评估语义）
  → 调 quant_core.evaluate_factor 得评估指标 + 本地轻量指标
  → 结果落盘：parquet（因子值）+ JSON（摘要/指标/算子版本快照）
  → factorlab serve 起 Web 展示
```

平台不修改 `quant-data` 下任何文件；本地 DuckDB 一律只读打开。

## 6. DSL 规范

### 6.1 Spec 文件（YAML）

```yaml
name: momentum_20d
category: ohlcv_core
direction: 1
description: 20日动量因子
universe:
  codes: ["000001.SZ", "600519.SH"]   # 显式列表；与 rules 互斥
  # rules: { exclude_st: true, min_list_days: 120, exchanges: ["SZSE", "SSE"] }
date:
  start: "2024-01-01"
  end: "2026-07-31"
target: forward_return_5d              # 默认 forward_return_5d
operators:                             # 可选：内联宏定义
  mom_ratio:
    params: [x, n]
    formula: "delay(x, n) / delay(x, 2*n) - 1"
formula: "rank(mom_ratio(close, 5))"
```

字段约束：

- `name`：必填，`^[A-Za-z_][A-Za-z0-9_]{0,63}$`，全局唯一。
- `category`：必填，v1 枚举 `ohlcv_core / ohlcv_retail / valuation / custom`。
- `direction`：必填，`1`（越高越好）或 `-1`（越低越好）。
- `universe.codes` 与 `universe.rules` 二选一；`rules` 支持 `exclude_st`、
  `min_list_days`、`exchanges`（值为 `SSE/SZSE`，与 `stock_basic_tushare` 一致；
  v1 固定集合，后续可加）。
- `date.start/end`：可调历史深度；默认空则取本地库全范围。
- `target`：评估目标，v1 支持 `forward_return_5d / forward_return_20d`。
- `formula`：必填，公式字符串。

### 6.2 公式语法

- 列引用：裸标识符 `open/high/low/close/volume/amount/turnover/pct_chg`。
- 数字字面量：整数/浮点（支持负号）。
- 算子调用：`name(arg, ...)`，嵌套任意深度。
- 二元运算：`+ - * /`，一元负号，括号分组。
- 三元表达式：`cond ? a : b`（WorldQuant 风格）。
- 宏引用：spec 内联 `operators` 或本地算子库中的宏，展开为 AST 子图。

解析错误携带行列号；未知算子给出相似算子建议（difflib）。

### 6.3 v1 算子集

**基础/数学**：`returns`（日收益）、`vwap`、`adv20`（20日均量）、`log`、`abs`、`sign`、
`sqrt`、`power`、`signed_power`、`max(a,b)`、`min(a,b)`、`if(cond,a,b)`。

**时序滚动**（窗口参数）：`mean/stddev/sum/median/max/min/variance/skew/kurtosis/
quantile/correlation/covariance/ts_rank/argmax/argmin/count_nonzero/slope/product`。

**时序位移/加权**：`delay`、`delta`、`ts_rank`、`ts_arg_max`、`ts_arg_min`、`wma`、
`ewma`、`decay_linear`、`ts_decay_linear`。

**横截面**（按当日全股票池）：`rank`、`zscore`、`scale`、`winsorize`、`standardize`、
`normalize`。

实现约定：时序算子按 `code` 分组、按日期排序后计算；横截面算子按 `date` 分组计算。
算子全部经注册表注册（名称、实现、版本号），引擎不感知具体算子。

### 6.4 新算子扩展（双通道 + 版本钉住）

**通道 1：DSL 内宏组合**。spec 内联 `operators` 或本地算子库定义：

```yaml
operators:
  event_decay:
    params: [x, n]
    formula: "mean(x, n) / delay(mean(x, n), n)"
```

解析期展开，不写代码。

**通道 2：Python 算子插件**。组合表达不了的新语义写小函数挂注册表：

```python
from factorlab.ops.registry import factor_op

@factor_op("event_decay", version="0.1.0")
def event_decay(x: pd.Series, n: int, *, ctx) -> pd.Series:
    ...
```

挂上即可在 DSL 中使用。`factorlab op list` 查看全部已注册算子，
`factorlab op doc <name>` 查看签名与文档。

**版本钉住**：每次计算结果记录所用算子集的版本快照（每个算子 name→version 映射 +
注册表总体版本）；算子实现变更后历史结果不变，重跑可复现。

## 7. 评估指标插件

接口：

```python
class Metric:
    name: str
    def compute(self, df: pd.DataFrame, ctx: EvalContext) -> dict: ...
```

v1 指标：

- `rank_ic`：调 `quant_core.evaluate_factor`（mean/std/t_stat/ir/n_weeks 等）。
- `pearson_ic`：同上，取 Pearson IC 部分。
- `decile_returns`：同上，十分位收益与单调性。
- `turnover`：同上，月度/季度换手率。
- `coverage`：本地计算（有效行占比、股票覆盖数）。

指标经注册表按 name 调用；后续 R²、信息增益率、残差分析作为新 Metric 挂入，不改主流程。
评估目标（前向收益）来源：v1 从本地 `daily` 的 close 自行计算并周频对齐；
`quant_factor.duckdb.factor_weekly` 仅作测试交叉验证，不做运行时依赖。

## 8. CLI 命令

| 命令 | 说明 |
|------|------|
| `factorlab run <spec>` | 解析、计算、评估、落盘 |
| `factorlab list` | 列出已保存因子与最近运行 |
| `factorlab show <name>` | 查看某因子摘要与指标 |
| `factorlab serve [--port]` | 启动 Web 可视化 |
| `factorlab data refresh [--start] [--end]` | teajoin 增量补数据到平台缓存库 |
| `factorlab op list` | 列出注册算子 |
| `factorlab op doc <name>` | 查看算子签名与文档 |

## 9. Web 可视化（FastAPI + Jinja2 + Plotly）

- `/`：因子列表（名称、类别、方向、最近运行时间、IC 摘要）。
- `/factor/<name>`：因子详情——IC 曲线（Plotly）、十分位收益柱状图、覆盖度、
  spec 原文、算子版本快照、参数摘要。
- 结果只读自平台结果目录，无需写数据库。

## 10. 错误处理

- DSL 语法/语义错误：明确信息 + 行列号；未知算子给出相似算子建议。
- 空 universe / 无有效股票：报错并提示检查 `codes` 或 `rules`。
- 数据缺失：提示该日期段本地缺失，可运行 `factorlab data refresh`。
- teajoin 限流/网络错误：指数退避重试（上限 3 次），保留进度可断点续传。
- 评估数据不足（有效行过少）：返回指标为 null 并在摘要中标注，不中断流程。

## 11. 测试策略

- 解析器单测：语法正确性、错误行列号、宏展开、三元表达式、优先级。
- 算子数值单测：与 pandas 原生实现逐值对照。
- 引擎黄金用例：用现有 `factor_weekly` 中的已知因子（如 `value_reversal_20d`）
  在相同输入下对拍，误差阈值内一致。
- 评估集成测试：小样本调 `quant_core.evaluate_factor`，核对返回结构。
- CLI 端到端：`run → list → show` 冒烟。
- Web smoke test：`/` 与 `/factor/<name>` 返回 200。

## 12. 复用清单

| 资产 | 用途 |
|------|------|
| `quant_core`（PyO3 已装） | 评估指标计算 |
| `quant.duckdb`（只读） | daily、stock_basic_tushare 数据源 |
| `quant_tushare_full.duckdb`（可选只读） | 更全历史数据源 |
| `quant_factor.duckdb`（只读，测试用） | 已知因子对拍、forward return 交叉验证 |
| JoinQuant 公式目录（CSV/JSON） | 算子集参考 + Alpha101 测试用例 |
| teajoin API key | 增量补数据 |

## 13. 里程碑

1. M1：项目骨架 + DSL 词法/语法/校验 + 算子注册表。
2. M2：数据层（DuckDB 只读 + teajoin 增量）+ 计算引擎 + 前向收益。
3. M3：评估指标插件 + CLI 全命令。
4. M4：Web 可视化。
5. M5：测试补全、文档、算子对拍验证。

详细拆分见实施计划（writing-plans 产物）。

## 14. 未来扩展（v2 候选）

- 因子库管理后台（注册、分级、对比、淘汰）。
- R²、信息增益率、残差分析等统计指标。
- 行业中性化、风格中性化算子。
- DSL 编译进 Rust 引擎（高性能路径）。
- Web 端 DSL 编辑与实时预览。
- 多用户与权限。
