# FactorLab M3a 数据层（本地核心）设计文档

日期：2026-08-15
状态：待评审
依赖主设计：`docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md`（下文简称"主 spec"）

## 1. 背景与范围

主 spec 的 M3 里程碑 = 数据层（DuckDB 只读 + teajoin 增量）+ 前向收益 + 处理管线。
因 teajoin 增量拉取依赖外部服务（API key 8/22 到期、需真实网络与限流验证），
拆为两期：

- **M3a（本文档）**：DuckDB 只读加载、universe 过滤、交易日历与停牌补全、
  前向收益与周频对齐、process 处理管线、最小端到端链路（真实数据小样本跑通）。
- **M3b（另行设计）**：teajoin 增量客户端、平台缓存库（parquet + duckdb）、
  `factorlab data refresh` 命令。

M3a 完成标准：`run_factor(spec, ctx)` 能用真实 `quant.duckdb` 数据小样本
（约 50 只股票 × 2 年）跑通「universe 解析 → 数据加载 → 因子计算 → process 链 →
前向收益 → 落盘（parquet + JSON 摘要）」并输出可复核结果。

## 2. 架构与模块

```
src/factorlab/
├── data/
│   ├── source.py      # load_daily(db, codes, rules, date, cols, float32) -> pl.LazyFrame
│   ├── universe.py    # resolve_universe(spec.universe | 引用 | 默认, db) -> list[str]
│   └── calendar.py    # 交易日历 + 停牌补全
├── process/
│   ├── registry.py    # register_processor / get_processor / run_process_chain
│   └── processors.py  # winsorize/standardize/csranknorm/robustzscore/neutralize/clip/fillna
├── engine/
│   ├── forward.py     # compute_forward_returns + align_weekly
│   └── compute.py     # 新增 run_factor(spec, ctx) 装配
└── spec.py            # UniverseSpec 增加命名引用与互斥校验
```

### 2.1 data/source.py

```python
def load_daily(
    db_path: Path,
    codes: list[str] | None,          # 纯数字代码（universe 解析结果）
    date_start: str | None, date_end: str | None,
    cols: list[str] | None = None,    # 列裁剪；None 时读取因子公式实际引用的列
    float32: bool = True,
) -> pl.LazyFrame
```

- DuckDB 只读连接：`connect(db_path, read_only=True)`；每次连接设置
  `memory_limit='4GB'`、`threads=2`（主 spec 6.1）。
- SQL-first：`SELECT date, code, <cols> FROM daily WHERE date BETWEEN ? AND ? [AND code IN (...)]`，
  禁止无过滤整表加载。
- `code IN (...)` 为空列表时视为「无有效股票」，由上层明确报错（不静默返回空）。
- float32：`use_float32` 时对数值列 cast float32（`date/code` 保持原类型）。
- 返回 `pl.LazyFrame`，由上层 `.collect()`。

### 2.2 data/universe.py + universe 三层解析

**解析优先级（高 → 低）**：

1. 运行参数 `--universe <name>`（调试覆盖，M4 接入 CLI；engine 层先预留参数）
2. spec 内联 universe（`codes` 或 `rules` 对象）
3. 全局默认 universe（`config.default_universe`，`FACTORLAB_DEFAULT_UNIVERSE`）

`UniverseSpec` 支持三种形式（互斥，model_validator 校验）：

```yaml
# 形式 1：命名引用（推荐挖掘使用）
universe: research_50          # 查 ~/.factorlab/universes/research_50.yaml

# 形式 2：内联 codes
universe:
  codes: ["000001.SZ", "600519.SH"]

# 形式 3：内联 rules
universe:
  rules: {exclude_st: true, min_list_days: 120, exchanges: ["SSE", "SZSE"]}
```

**universe 文件**（`~/.factorlab/universes/<name>.yaml`）：内容与内联形式相同
（`codes` 或 `rules` 二选一），独立编辑、多处复用。`--universe`/引用处接受
**name**（查 universes 目录）或**文件路径**（直接读取）；文件缺失报错并提示路径。

**解析结果**：统一返回**纯数字代码列表**（`daily.code` 格式）。
代码标准化：`'000001.SZ'` → `'000001'`（strip 后缀）；已纯数字的直通。

**rules 语义**（对照 `stock_basic_tushare` / `st_status`）：

| 规则 | 实现 |
|------|------|
| `exclude_st` | `st_status` 中最近日期 `is_st=true` 的 code 剔除（当前快照语义） |
| `min_list_days` | `list_date` 距 `date.start` 满 N 自然日；`date.start` 为空时距数据最早日期 |
| `exchanges` | `exchange IN (SSE, SZSE)`；`BSE` 明确不在 v1 集合（含 BSE 时报错提示） |

**挖掘固定约定（文档化）**：挖掘批次内所有因子使用同一 universe（默认池或
`--universe`），同池计算、同池比较；换池必须显式。此约定写入 interface.md 与 README。

### 2.3 data/calendar.py

```python
def trading_calendar(db_path: Path, date_start, date_end) -> pl.Series   # daily 全表 distinct date
def fill_suspensions(df: pl.DataFrame, calendar: pl.Series) -> pl.DataFrame
```

- 交易日历：`SELECT DISTINCT date FROM daily ORDER BY date`（范围内）。
- 停牌补全：`calendar × codes` 全连接，原数据 outer join，缺失行 `date/code` 有值、
  数值列 null（float32）；`forward` 计算基于补全后序列（防滚动窗口错位，主 spec 7.6）。
- 补全后的 null 由 process 链的 `fillna` 或因子计算语义处理，不默认填充。

### 2.4 process/registry.py + processors.py

```python
def register_processor(name: str) -> Callable
def get_processor(name: str) -> ProcessorDef
def run_process_chain(df: pl.DataFrame, chain: list[str], ctx: ProcessCtx) -> pl.DataFrame
```

- `chain` 为字符串列表，如 `["winsorize(quantile=0.99)", "standardize()", "neutralize(by: industry)"]`；
  简易参数解析：`name(args)`，参数 `key: value` 或 `value` 形式（与主 spec 7.4 一致）。
- 全部处理器为 Polars 表达式，截面语义 `.over("date")`；`signal` 列经链处理。
- **neutralize 数据依赖**：`by: industry` join `stock_basic_tushare`（静态当前行业，
  主 spec 注明局限）；`by: size` join `daily_basic.total_mv`（`ts_code` → symbol 映射）；
  `by: market` 全截面 demean。join 列为中间列，链后释放。
- 处理器清单与语义（主 spec 7.4）：
  - `winsorize(quantile=0.99)`：截面分位数去极值（可加 `std=` 模式，M3a 先实现 quantile）
  - `standardize()` / `zscore()`：截面 z-score
  - `csranknorm()`：截面排名归一化 [0,1]
  - `robustzscore()`：中位数/MAD 稳健标准化
  - `neutralize(by: ...)`：截面中心化
  - `clip(lower, upper)`：截断
  - `fillna(method: industry_mean|value|forward)`：缺失处理（M3a 实现 value/forward，
    industry_mean 依赖静态行业，一并实现）

### 2.5 engine/forward.py

```python
def compute_forward_returns(df: pl.DataFrame, horizons: tuple[int, ...] = (5, 20)) -> pl.DataFrame
def align_weekly(df: pl.DataFrame) -> pl.DataFrame
```

- `forward_return_h = close[t+h] / close[t] - 1`，h 为**交易日**（补全后序列的索引差）。
- 周频对齐：ISO 周内最后一个交易日（`date` 分组取组内 max；非固定周五，
  以该周实际最后交易日为准）；因子面板与 forward 均对齐到周频
  （匹配 `factor_weekly` 与 Rust 评估语义，主 spec 6 数据流）。
- 对齐输出：`date（ISO 周最后交易日）, code, signal, forward_return_h, close`。

### 2.6 engine/compute.py 的 run_factor 装配

```python
def run_factor(spec: FactorSpec, ctx: RunContext) -> FactorResult
```

装配顺序（主 spec 6 数据流）：

1. universe 解析（三层优先级）→ 代码列表；空集报错
2. 数据加载 `load_daily`（列裁剪按公式 AST 引用列 ∪ process 依赖列）
3. 停牌补全（calendar.fill_suspensions）
4. 因子计算 `compute_formula`（M1/M2 已有，含宏展开与分区校验）
5. process 链 `run_process_chain`
6. `compute_forward_returns` + `align_weekly`
7. 落盘：parquet（周频面板）+ JSON 摘要（spec 原文、universe 解析结果、
   处理链、行数、内存设置、算子版本快照——版本快照完整实现随 M4 registry/store）

`FactorResult`：`{spec, panel: pl.DataFrame, summary: dict}`。
`RunContext`：`{db_path, output_dir, universe_override, float32, ...}`。

## 3. 关键语义决策

| 主题 | 决策 |
|------|------|
| 代码格式 | spec/文件用 ts_code（`000001.SZ`），`daily.code` 为纯数字（`000001`）；`stock_basic_tushare.symbol` 为桥梁，统一标准化为纯数字 |
| 周频对齐 | ISO 周最后一个交易日 |
| 前向收益 | `close[t+h]/close[t]-1`，h 交易日，补全后序列 |
| neutralize 行业 | 静态当前行业快照，v1 接受前视近似风险，文档注明 |
| 停牌补全 | 交易日历全连接，缺失数值 null，不默认填充 |
| process 参数 | 简易 `name(args)` 解析，与主 spec 7.4 一致 |
| 内存策略（本期） | SQL-first + float32 + DuckDB `memory_limit=4GB`/`threads=2`；RSS 熔断/分块计划留 M4 |
| universe 空集 | 明确报错，提示检查 codes/rules/引用文件 |
| 日期缺失 | 返回空面板前先校验范围：`date.end > 数据最小日期`，否则提示「本地缺数据，可 data refresh（M3b）」 |

## 4. 数据流

```
run_factor(spec, ctx)
  → universe 解析（--universe > spec 内联 > 全局默认）→ 纯数字代码列表
  → load_daily：SQL WHERE date/code + 列裁剪 + float32 → LazyFrame
  → fill_suspensions：日历全连接补全停牌
  → compute_formula：AST 白名单 → 宏展开 → 分区/负 lookback 校验 → expr_codegen
  → run_process_chain：winsorize → zscore → neutralize ... （.over("date")）
  → compute_forward_returns + align_weekly
  → 落盘 parquet + JSON 摘要
```

平台不修改 `quant-data` 任何文件；DuckDB 一律只读。

## 5. 错误处理

- 空 universe：报错 + 建议（检查 codes 拼写、rules 条件、引用文件路径）
- universe 文件缺失：报错并给出期望路径
- 代码格式非法：报错列出非法项
- 日期段超出本地数据范围：提示缺数据，可运行 `data refresh`（M3b 提供）
- process 链未知处理器 / 参数非法：报错列出可用处理器
- neutralize 依赖列缺失（如 daily_basic 无该日数据）：报错提示

## 6. 测试策略

- **单测**（tmp DuckDB 造数据，不依赖真实库）：
  - universe：codes 标准化、rules 各分支、引用文件、三层优先级、互斥校验
  - source：SQL 过滤正确、float32 cast、空列表拒绝、只读连接（写操作失败）
  - calendar：日历生成、停牌补全（构造缺失行验证补全与 null）
  - forward：手工面板验证 5/20 日收益、周频对齐（跨周边界）、补全后索引语义
  - process：每个处理器统计性质（去极值后极值被压、z-score 均值≈0 方差≈1、
    ranknorm 值域 [0,1]、neutralize 后组内均值≈0、clip/fillna 边界）
  - process 参数解析：`name(args)` 各种形式
- **集成 e2e**（`@pytest.mark.integration`，真实 `quant.duckdb` 存在才跑，否则 skip）：
  - 50 只 × 2024–2025：`vol_skew` 类因子 + `winsorize→standardize→neutralize(industry)`
    + forward_5d，验证输出结构（周频、列、行数）、落盘文件存在、JSON 摘要可解析
- **防回归**：M1/M2 全部测试保持通过

## 7. 明确不做（M3a）

- teajoin 增量拉取与平台缓存库（M3b）
- `factorlab data refresh` 命令（M3b）
- `factorlab run` CLI 全命令与配置加载（M4；engine 层接口先定型）
- RSS 熔断与分块执行计划（M4）
- 多因子组合（factors + combine）装配（M4）
- 因子注册表持久化与版本快照完整实现（M4）
- factor_weekly 交叉验证对拍（M6 语料里程碑）
