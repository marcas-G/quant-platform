# FactorLab M4a 引擎接入与评估设计文档

日期：2026-08-16
状态：待评审
依赖主设计：`docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md`
前置里程碑：M1/M2（骨架/引擎）、M3a（数据层本地核心）、M3b（平台数据平台）

## 1. 背景与目标

M4 拆两期：M4a（本设计）= 引擎接入平台库 + 复权口径消费 + 评估桥接 + run 命令；
M4b = 分层回测 + 因子对比 + 组合合成 + list/show/compare 命令。

M4a 核心目标：**因子从平台库（`data/factorlab.duckdb`）端到端跑通到评估**，
与 `quant-data` 彻底断绝关系（项目外路径/引用全部移除，需要的外部资源一律重构进项目内）。

## 2. 数据层全面切换（platform 化）

### 2.1 项目自包含原则

- `quant-data` 外部路径从代码中**彻底移除**（`config.quant_db` 废弃）。
- 平台库 `data/factorlab.duckdb`（gitignored）是唯一数据源。
- 任何需要的外部资源（数据/模块/路径）一律重构进 `quant-platform` 项目内。

### 2.2 source.py 改造（读平台库）

```python
def load_daily(db_path: Path, codes, date_start=None, date_end=None, cols=None,
               float32=True, include_adj: bool = True) -> pl.LazyFrame
```

- SQL：`SELECT trade_date, ts_code, open, high, low, close, volume, amount, turnover,
  pct_chg, pre_close[, adj_factor] FROM daily [JOIN adj_factor ON (trade_date, ts_code)]`
  WHERE 过滤（code IN / date 范围），与 M3a 同款 SQL-first 纪律。
- **列映射**（加载时）：`trade_date → date`（String → pl.Date）、`ts_code → code`
  （去后缀，`symbol` 列是桥梁，复用 M3a 的 normalize 逻辑）。
- `pre_close` 保留（pct_chg 自检与复权审计用）。
- 返回 `pl.LazyFrame`（date/code/OHLCV/pre_close[/adj_factor]）。

### 2.3 run_factor 装配语义（复权口径消费）

```
run_factor(spec, ctx)：
  1. universe 解析（平台库；override > spec > default_universe）
  2. load_daily（平台库，含 adj_factor）→ 停牌补全（平台库 trade_cal）
  3. view_prices(adjustment 口径) —— FactorSpec.adjustment: raw|qfq|hfq|pit_qfq（默认 qfq）
  4. compute_formula（含 operators 宏展开，见 2.5）
  5. process 链 → 前向收益（raw close）→ 日频面板落盘
```

- **因子值**用复权视图（默认 qfq——价格序列连续，除权日不假崩）。
- **前向收益**用 **total_return 口径**（close×adj 序列计算，含分红再投资——
  M3b 复权架构的"收益率/Total Return 统一计算"；HFQ 收益 = QFQ 收益，
  等比缩放不影响收益率）。M3a 的 raw close 版 forward 在切换到平台库时升级。
- `pit_qfq` 需 asof——M4a 支持 spec 级 `adjustment: raw|qfq|hfq`；`pit_qfq` 预留
  （asof=spec.date.end 研究日语义，审计场景 M4b 消费）。

### 2.4 universe/calendar 平台库适配

- `resolve_codes` 读平台库 `stock_basic`（ts_code/symbol/exchange/list_date/industry——
  tushare 原始列）；返回纯数字代码（daily.code 格式）不变。
- `exclude_st` → 平台库 `stock_st`（ts_code/trade_date/is_st）。
- `trading_calendar` 读平台库 `trade_cal`（cal_date/is_open，is_open 需 cast Int32）。
- 平台库表名/列名与旧 quant-data 的差异在实现中逐项核对（M3b 已建表，schema 已知）。

### 2.5 遗留接线

- **operators 宏消费**：`spec.operators`（内联宏）在 compute_formula 前展开——
  复用/扩展 `ops/platform_ops.py` 的宏展开器（`expand_platform_macros` 模式），
  用户宏按 `name(params) -> formula` 展开进公式。
- **default_universe 接线**：CLI run 的 `--universe` 参数默认值 =
  `settings.default_universe`（`FACTORLAB_DEFAULT_UNIVERSE`），spec 未显式覆盖时生效。
- **verify 对拍**：参考库参数保留（`--compare`），默认无参考（quant-data 清理后
  对拍为可选外部验证，不构成运行时依赖）。

## 3. 评估桥接（eval/）

### 3.1 结构（自包含）

```
src/factorlab/eval/
├── __init__.py
├── alignment.py    # 周频对齐（从 engine/forward.py 重构 align_weekly）
├── rust_ic.py      # quant_core.evaluate_factor 桥接
└── metrics.py      # 轻量本地指标（补 quant_core 缺口，如覆盖率明细）
```

- **eval/ 自包含**：输入日频面板（date/code/signal/forward_return_5d），输出评估 dict；
  唯一外部依赖 quant_core（PyO3，项目依赖）。不 import engine/data。
- **engine → eval 单向**：`run_factor` 装配到日频面板后，评估阶段调 eval。

### 3.2 周频对齐（alignment.py）

`align_weekly(df) -> pl.DataFrame`——从 `engine/forward.py` 重构（ISO 周语义，
M3a 已实现+测试，原样迁移；`engine/forward.py` 保留 `compute_forward_returns`）。

### 3.3 quant_core 桥接（rust_ic.py）

```python
def evaluate_factor_weekly(panel: pl.DataFrame, factor_name: str, direction: int,
                           target: str = "forward_return_5d") -> dict
```

- 输入：日频面板（date/code/signal/forward_return_*）——内部做周频对齐后评估。
- 内部调用（已实测打通）：`quant_core.evaluate_factor(dates, codes, factor_vals,
  forward_returns, "_factor", direction)`——**factor_name 参数必须传 `"_factor"`**
  （quant_core 内部列名约定，文档未记载）。
- 返回结构（实测）：`{factor, target, direction, n_weeks, n_stocks_avg, ic{mean/std/
  t_stat/ir/n_weeks/recent_26w_mean/recent_26w_t/sign_consistent}, pearson_ic{mean/
  t_stat}, decile_returns{weighting/monotonic/spread/groups}, turnover{monthly/
  quarterly}, coverage{pct_valid/total_rows/valid_rows}}`。
- **局限**：quant_core target 内部固定 `forward_return_5d`——M4a 评估 5d；
  20d 评估在实现时试传验证，不可行则记录局限（M4b 或重编译 Rust 内核解决）。

### 3.4 评估输入语义

- 因子值：周频对齐后的 signal（对齐日取值）。
- 前向收益：`forward_return_5d`（total_return 口径——close×adj 序列，含分红再投资）。
- direction：spec.direction（1/-1）——评估时传入（IC 符号与十分位方向）。

## 4. `factorlab run <spec>` 命令

```
factorlab run <spec> [--universe <name|path>] [--max-memory 4GB] [--chunk-size 1000]
                    [--float32/--float64] [--force]
```

行为：load_spec → run_factor（平台库 + 复权 + operators 宏 + default_universe）
→ 周频评估（eval）→ 落盘：

```
results/<name>/
├── panel.parquet        # 日频面板（date/code/signal/forward_return_5d/close）
├── weekly.parquet       # 周频对齐面板（评估输入）
└── summary.json         # spec 原文 + 计算摘要 + 评估结果（ic/decile/turnover/coverage）
```

错误处理（主 spec §11）：空 universe、日期段无数据、评估数据不足（有效行过少 →
指标 null 标注不中断）、内存预算超限拒绝启动。

## 5. quant-data 清理流程

1. M4a 验收：真实因子 run 端到端（平台库）→ 评估结果合理（IC 非全 nan、十分位有区分度）。
2. 输出平台库与 quant-data 对比摘要（verify --compare，可选）。
3. **用户显式确认后**删除 `C:/Users/ThinkPad/quant-data`。
4. 清理代码残留：`config.quant_db` 移除、CLAUDE.md 环境事实更新、
   文档（interface.md/playbook）中 quant-data 引用清理。

## 6. 测试策略

- **平台库加载**：映射（trade_date→date、ts_code→code）、复权 join、float32、列裁剪、
  空 universe 报错（fixture 改平台库风格：trade_date/ts_code/adj_factor 列）。
- **universe 平台库适配**：codes/rules 各分支（stock_st/stock_basic 平台库列）。
- **复权消费**：run_factor 装配中 adjustment 口径（qfq 默认——除权日因子值连续；
  raw 原样；hfq 乘积）——构造除权序列验证。
- **operators 宏展开**：spec.operators 内联宏 → 公式展开 → 计算正确。
- **default_universe**：settings.default_universe 生效路径。
- **eval 桥接**：真实 quant_core 小样本（周频面板 → 评估 dict 结构完整、
  IC 计算合理、direction 影响符号）。
- **run e2e**：平台库小样本（含真实数据——用 data/factorlab.duckdb 3-5 只股票
  子集）端到端 run → 落盘文件 + summary 评估字段。
- **防回归**：M1-M3b 全部测试（数据层切换影响的旧测试 fixture 更新为平台库风格）。

## 7. 明确不做（M4a）

- 分层回测、因子对比、组合合成（M4b）。
- `pit_qfq` 的 spec 级消费（预留；M4b 审计场景）。
- 20d 评估（quant_core 局限，验证后记录）。
- Web 可视化（M5）。
- RSS 熔断与分块执行计划（后续）。
- 因子库管理后台（v2）。
