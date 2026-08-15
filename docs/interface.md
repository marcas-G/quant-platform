# FactorLab M1 接口文档

本文件描述 M1 已交付的 CLI、Spec、因子脚本和 Python API。实现与设计文档冲突时以
`docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md` 为准。

## 1. CLI

安装 editable 包后，命令入口为 `factorlab`。

| 命令 | 说明 |
|------|------|
| `factorlab version` | 打印包版本 |
| `factorlab lint <spec.yaml>` | 校验 Spec 与因子脚本 AST，失败时以非 0 退出 |
| `factorlab op list` | 列出已注册算子 |
| `factorlab op doc <name>` | 查看算子名称、类别、版本与 docstring |
| `factorlab op add <plugin.py> [--force]` | 校验并注册用户插件；同名冲突需 `--force` |
| `factorlab op remove <name>` | 禁用用户插件，保留已计算历史结果 |

## 2. Spec 文件

Spec 为 YAML。最小单因子示例：

```yaml
name: demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
date:
  start: "2020-01-01"
  end: "2021-01-01"
formula: |
  from polars_ta.prefix.wq import ts_delay
  signal = ts_delay(close, 1)
```

字段：

- `name`：必填，`^[A-Za-z_][A-Za-z0-9_]{0,63}$`。
- `category`：必填，`ohlcv_core | ohlcv_retail | valuation | custom`。
- `direction`：必填，`1` 或 `-1`。
- `universe.codes` 与 `universe.rules`：二选一。
- `date.start` / `date.end`：可选，`YYYY-MM-DD`。
- `target`：`forward_return_5d | forward_return_20d`，默认 `forward_return_5d`。
- `process`：可选字符串列表。
- `operators`：可选 DSL 宏映射。**注意：当前未实现消费（M4 接入），spec 中声明会被静默忽略；公式引用宏名会报未知算子。**
- `formula` 或 `factors`：二选一。
- 使用 `factors` 时必须提供 `combine`。
- `combine.method`：`ic_weight | equal_weight | weight_sum`；`weight_sum` 时
  `weights` 非空且数量等于 `factors` 数量。

多因子示例：

```yaml
name: composite_demo
category: custom
direction: 1
universe:
  rules: {exclude_st: true, min_list_days: 120}
factors:
  - name: a
    formula: "signal = close / open - 1"
  - name: b
    formula: "signal = close - open"
combine:
  method: equal_weight
```

## 3. 因子脚本

`formula` 是受白名单限制的 Python 代码块，最终保留输出列 `signal`。

允许：

- 赋值
- `def` 自定义函数
- `class`
- 白名单 `import`
- 表达式、算术、比较、布尔、`a if cond else b`
- 下标 `x[0]`
- `#` 注释

禁止：

- `for` / `while`
- 副作用、文件/网络/子进程/系统调用
- `eval`、`exec`、`open`、`compile`、`__import__`
- 属性调用，例如 `pl.read_csv(...)`
- 白名单以外的 `import`

白名单 import 前缀：

- `polars`
- `polars_ta.prefix.`
- `factorlab.ops.`

### 分区与 lookback

- `ts_*` 按 asset 排序并只使用历史窗口。
- `cs_*` 按 date 分组。
- `gp_*` 按 date + group key 分组。
- `ts_delay(x, d)` 和 `ts_delta(x, d)` 的位移不能为负：字面量（含可折叠表达式如
  `1 - 2`、`d=-1`、`-1.0`）在执行前被拒绝；非常量变量位移无法静态判断，放行。
- 未知算子会在执行前被拒绝。
- **`def` 内禁止窗口/截面算子**：expr_codegen 把用户 def 当黑盒整体在元素级分区
  执行，def 内的 `ts_/cs_/gp_` 调用会在全表上跑窗口、跨资产泄漏，因此直接拒绝
  （带源码位置）。`def` 内只允许元素级纯函数；窗口语义请直接写在公式顶层。
- 平台薄封装算子（`returns/vwap/adv20`）在解析期**展开为 `ts_` 表达式**再交给
  `expr_codegen`，保证按 asset 分区；`group_rank/group_mean` 自带 `.over(key)`
  分组语义，不展开。import 别名（`returns as ret`）同样生效。
- 元素级纯函数白名单（与 codegen 作用域核对）：`abs/log/log1p/sqrt/exp/sign/floor/if_else`。

平台薄封装算子从 `factorlab.ops.platform_ops` 导入；注册到注册表的算子可通过
`factorlab op list` 查看。

## 4. Python API

### `factorlab.spec.load_spec(path) -> FactorSpec`

读取 YAML 并返回 Pydantic `FactorSpec`。校验失败抛出 `pydantic.ValidationError`。

### `factorlab.factor.ast_gate.validate_formula(source: str) -> None`

校验因子脚本。失败抛出 `factorlab.factor.errors.FactorDSLError`。

### `factorlab.engine.compute.compute_formula(df, formula, asset="code", date="date") -> pl.DataFrame`

在小样本 Polars DataFrame 上执行因子脚本，返回按 `date, asset` 排序的
`[date, asset, signal]` 面板。当前不加载 DuckDB。

执行前依次：AST 白名单校验 → 幂等注册 `polars_ta` 算子族与平台薄封装 →
分区校验（拒绝未知算子）→ 负 lookback 拒绝（`ts_delay/ts_delta` 负位移）。

### `factorlab.engine.partitions.validate_partition_calls(source) -> None`

校验因子脚本中的调用均为已知算子、公式内 `def` 函数或元素级纯函数，否则抛
`FactorDSLError`（含源码位置）。

### `factorlab.engine.partitions.reject_future_shifts(source) -> None`

拒绝 `ts_delay/ts_delta` 的字面量负位移（防未来函数）。

### 算子族注册

```python
from factorlab.ops.polars_ta_wrappers import register_polars_ta_ops
from factorlab.ops.platform_ops import register_platform_ops

register_polars_ta_ops()  # wq/ta/tdx 算子族
register_platform_ops()   # returns/vwap/adv20/group_rank/group_mean
```

两者均幂等，`compute_formula` 已在内部调用，用户无需手动注册。

### 算子注册

```python
import polars as pl
from factorlab.ops.registry import factor_op

@factor_op("tail_ratio", kind="ts", version="0.1.0")
def tail_ratio(x: pl.Expr, n: int) -> pl.Expr:
    spread = x.rolling_quantile(0.9, window_size=n) - x.rolling_quantile(0.1, window_size=n)
    return spread / x.rolling_std(window_size=n)
```

`kind` 取值：`el | ts | cs | gp | ta`。

### 插件管理

用户插件放在 `~/.factorlab/plugins/`。插件文件必须只定义纯函数，并通过
`factor_op` 注册算子。`op add` 会做 AST 安全扫描。

### `factorlab.engine.compute.run_factor(spec, ctx) -> FactorResult`

装配完整链路：universe 解析 → `load_daily` → 停牌补全 → `compute_formula` →
process 链 → 前向收益 → 周频对齐 → 落盘 `panel.parquet` + `summary.json`。

`RunContext` 字段：`db_path`（默认 `settings.quant_db`）、`output_dir`、
`universe_override`（6 位代码或引用名称/路径，优先级最高）、`float32`。

`FactorResult`：`spec`、`panel`（列：`date, code, signal, forward_return_5d, forward_return_20d, close`）、
`summary`（含 spec 原文、codes、universe_count、panel_rows、signal_null_ratio、process、float32）。

`factors`/`combine` 多因子组合暂不支持（NotImplementedError，M4 实现）。

### `factorlab.data.universe.resolve_codes(spec, db, override=None, settings=settings) -> list[str]`

universe 解析优先级：`override` > spec 内联（`ref` 命名引用 / `codes` / `rules`）。
返回纯数字代码列表（`daily.code` 格式）。命名引用查 `~/.factorlab/universes/<name>.yaml`
（或直接给文件路径）。`default_universe`（`FACTORLAB_DEFAULT_UNIVERSE`）为 M4 CLI 预留，尚未接线。

**挖掘约定**：同批次因子固定同一 universe（`--universe` 或共享 spec 引用），同池计算、同池比较。

`rules` 支持：`exclude_st`（st_status 最新快照）、`min_list_days`（list_date 距 date.start
或数据最早日期满 N 自然日）、`exchanges`（SSE/SZSE，BSE 不在 v1 集合）。

### `factorlab.data.source.load_daily(db_path, codes, date_start=None, date_end=None, cols=None, float32=True) -> pl.LazyFrame`

DuckDB 只读加载；SQL-first 过滤；`date` cast `pl.Date`；数值列 float32。
**注意**：内部实际立即执行查询（`execute().pl()` 后包 `lazy()`），SQL 错误在调用时抛出。

### `factorlab.data.calendar.trading_calendar / fill_suspensions`

交易日历（distinct date，升序）与停牌补全（日历×代码全连接，缺失数值 null，
不默认填充）。补全后输出按日期升序、组内代码顺序未承诺（调用方自行排序）。

### process 链

处理器：`winsorize(quantile=0.99)`、`standardize()`（别名 `zscore`）、`csranknorm()`、
`robustzscore()`、`neutralize(by=market|industry|size)`、`clip(lower, upper)`、
`fillna(method=value|forward|industry_mean)`。截面类处理器按 `.over("date")` 分组；
`fillna(method=forward)` 按代码内日期前向；`clip`/`fillna(value)` 为元素级。

**spec 文件内的链项必须用 `=` 分隔**（`neutralize(by=industry)`），`key: value` 冒号
写法会被 YAML 解析为映射而报错。

`neutralize` 的行业依赖 `stock_basic_tushare` 静态行业（v1 近似）；`size` 按
`daily_basic.total_mv` 每日期内排名十分位分桶后组内 demean（无 daily_basic 匹配时报错）；
截面 N<10 时 size 中性化每桶 1 只股票，demean 恒 0（分组式中性化固有属性）。

零方差截面（standardize/robustzscore）输出 null（NaN 不是 null，fillna 无法处理）。

### `factorlab.engine.forward.compute_forward_returns / align_weekly`

前向收益 `close[t+h]/close[t]-1`（h 交易日索引差，输入须停牌补全）；
`align_weekly` 对齐到 **ISO 周**最后一个交易日（跨年日期同属 ISO 周时合并为该周
最后交易日，与 tushare weekly 语义一致）。

### `factorlab.data.adjust.view_prices / total_return`

价格视图（输入 raw 价格面板，含 `adj_factor` 列；输出含 scaled 价格列）：
`view_prices(df, view="qfq", asof=None)`，`view ∈ raw|qfq|hfq|pit_qfq`：
- RAW 原样；QFQ `×adj/adj[latest]`（最新因子基准）；HFQ `×adj`（连续价格）；
  PIT_QFQ `×adj/adj[asof]`（研究日视角防未来，必须给 `asof`）。
- QFQ/PIT_QFQ 按 code+date 排序后计算，latest 语义基于日期而非行序；跨 code 独立。

`total_return(close, adj)`：HFQ 收益 `close[t]×adj[t]/(close[t-1]×adj[t-1])-1`
（含分红再投资的真实收益；除权日上 RAW 收益率 ≠ QFQ/HFQ 收益率，用 total_return）。

### `factorlab.data.adjust` 审计三查（AdjustmentAudit）

`FactorFn = Callable[[pl.DataFrame], pl.DataFrame]`——输入价格面板
（date/code/价格列），输出 (date, code, signal)；输出缺列时抛 `ValueError`。
`AuditReport(check, passed, details)` dataclass，`details` 含审计指标。

- `lookahead_check(factor_fn, df, asof) -> AuditReport`
  未来信息泄漏：asof 截断重算 vs 全量重算，仅对比 `date <= asof` 的行；
  截断后值变化（含一侧为 null）的行即潜在泄漏（`affected_rows`）。
- `scale_invariance_check(factor_fn, df) -> AuditReport`
  价格尺度不变：RAW vs QFQ 因子值最大绝对差 `< 1e-6` 通过。收益率类因子天然
  不变；**跨除权日**时朴素 RAW 收益率与 QFQ 不同（RAW 除权跳变）——审计对比应
  使用无除权事件的面板或声明口径的因子。
- `adjustment_sensitivity_check(factor_fn, df, views=("raw","qfq","hfq")) -> AuditReport`
  复权口径切换敏感性：各视图因子值相对 raw 的最大绝对差（`max_abs_diff`）。

### `factorlab.data.platform_db.PlatformDB`

`PlatformDB(path)`：duckdb 写库，自动建表、按 keys upsert 去重、完整性自检。
列名沿用 tushare API 原始命名（trade_date/ts_code），与 API 零转换。

- `connect() -> duckdb.DuckDBPyConnection`：打开写连接；rebuild/refresh 批量场景
  复用（每批重开连接 ~24ms，47k 批纯开销 ~19 分钟），调用方负责 close（或用 `with`）。
- `upsert_on(con, table, df, keys, dedup=True)`：在给定连接上 upsert，与 `upsert()`
  同语义。`dedup=False` 纯 INSERT——调用方保证批内无重复（如 rebuild 单日批按
  trade_date 唯一），省去全表扫描 DELETE（~80ms/批）。
- `upsert(table, df, keys)`：公共 API，每次自开连接，`dedup=True` 保持去重语义。
- `query(sql, params=None) -> pl.DataFrame` / `list_tables()` / `describe(table)` /
  `integrity_check() -> dict`。

### `factorlab.data.rebuild` 全量重建编排

- `load_manifest(path) -> dict` / `save_manifest(path, manifest)`：断点续传
  manifest 读写（每批落盘）。结构：`{table: {completed: [dates], failed: [dates]}, last_updated: "YYYYMMDD"}`。
- `RebuildScope(start="20000104", end=None)`：重建日期范围（end 缺省 20261231）。
- `rebuild_all(db, client, scope=RebuildScope(), resume=True, manifest_path=None) -> dict`
  编排时序：trade_cal（is_open=1 过滤，无交易日报错）→ stock_basic（L/D 分页）→
  行情 7 表按日（DAILY_TABLES，单连接复用，completed 跳过、failed 记录）→ 财报 3 表
  按报告期（每季末，空返回正常）→ index_daily（4 指数全历史）+ index_weight（每月
  最后一个交易日当期成分）。manifest_path 缺省 `settings.data_dir / "manifest.json"`。
  resume=True 跳过 completed、重试 failed（成功后移除）；resume=False 忽略既有
  manifest 全量重拉。缺 token 抛 `ValueError`。返回
  `{"tables": {table: {"dates_fetched"/"report_dates"/"month_dates", "rows", "failed"}}}`。

常量：`DAILY_TABLES`（7 行情表）、`FINANCIAL_TABLES`（3 财报表）、`INDEX_CODES`（4 指数）。

## 5. 测试

运行：

```powershell
python -m pytest
```

当前覆盖 Spec 校验、AST 白名单、算子插件生命周期、最小计算路径、polars_ta 算子族、
平台薄封装、分区校验与防未来函数，以及 CLI smoke。
