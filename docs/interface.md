# FactorLab 接口文档（M1–M4b）

本文件描述 M1–M4b 已交付的 CLI、Spec、因子脚本和 Python API。实现与设计文档
冲突时以 `docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md` 为准。

## 0. M4b 汇总：分层回测与因子清单

M4b 在 M4a 评估链路之上补齐单因子评估闭环：

- **分层回测**（`factorlab.eval.layered.layered_backtest`，见 §4）：周频面板按
  signal 分档（默认十分位）等权组合累计净值 + long-short + 摘要指标；`factorlab run`
  默认产出并写入 `summary.json.evaluation.layered_backtest`（`--no-backtest` 关闭，
  `--groups N` 调整档数）。
- **CLI `list` / `show`**：已保存因子清单与单因子完整摘要（见 §1）。
- **M4a 遗留接线**：`pit_qfq` 消费（`run_factor` 传 `asof=spec.date.end`）、
  `weekly.parquet` 周频对齐面板落盘（替代原日频冗余）、`results_dir` 锚定
  （`--output-dir` 缺省 `results/<name>/`）。
- 回测期数口径与 quant_core 评估周数一致：signal/forward 全 null 的周（头部窗口
  未满/尾部无未来收益）不计入，`bt["periods"] == evaluation["n_weeks"]`（实测）。

## 0.1 M4a 汇总：端到端评估链路

M4a 打通「平台库数据 → 因子计算 → 复权视图 → 周频评估」端到端链路：

- **数据源切换**：平台库 `data/factorlab.duckdb`（`settings.platform_db`，
  `FACTORLAB_PLATFORM_DB` 覆盖）为**唯一数据源**，项目自包含；外部只读库路径
  已从代码彻底移除。`load_daily` 加载平台库 `daily`（`trade_date/ts_code` →
  `date/code` 映射、`adj_factor` 恒 join，见 §4）。
- **`factorlab run <spec.yaml>`**：计算 + 评估端到端命令（见 §1）：run_factor 日频
  面板 → 周频对齐 → `quant_core` 评估 → `summary.json` 追加 `evaluation` 字段，
  另落盘 `weekly.parquet`（评估输入面板）。
- **复权视图（adjustment）**：spec `adjustment` 字段（`raw|qfq|hfq|pit_qfq`，
  默认 `qfq`）决定因子计算所用价格口径（`view_prices`，见 §4）；前向收益恒用
  **total_return 口径**（raw close×adj，先于复权视图计算、避免二次复权）。
- **eval 包**（`factorlab.eval`）：`alignment.align_weekly`（ISO 周最后交易日
  对齐）、`metrics.coverage_report`（覆盖率）、`rust_ic.evaluate_factor_weekly`
  （`quant_core` 周频评估桥接，见 §4）。
- **`default_universe` 接线**：`factorlab run` 缺省 `--universe` 时回落
  `settings.default_universe`（`FACTORLAB_DEFAULT_UNIVERSE`），未配置再用 spec
  内联 universe（见 §4 `resolve_codes`）。

## 1. CLI

安装 editable 包后，命令入口为 `factorlab`。

| 命令 | 说明 |
|------|------|
| `factorlab version` | 打印包版本 |
| `factorlab lint <spec.yaml>` | 校验 Spec 与因子脚本 AST，失败时以非 0 退出 |
| `factorlab run <spec.yaml> [--universe U] [--max-memory M] [--output-dir DIR] [--no-float32] [--backtest/--no-backtest] [--groups N]` | 计算因子并周频评估 + 分层回测（默认），落盘 `results/<name>/` |
| `factorlab list` | 列出已保存因子与最近运行摘要（扫描 `results_dir/*/summary.json`，按运行时间倒序） |
| `factorlab show <name>` | 查看单因子完整摘要（spec 原文/评估/分层回测） |
| `factorlab op list` | 列出已注册算子 |
| `factorlab op doc <name>` | 查看算子名称、类别、版本与 docstring |
| `factorlab op add <plugin.py> [--force]` | 校验并注册用户插件；同名冲突需 `--force` |
| `factorlab op remove <name>` | 禁用用户插件，保留已计算历史结果 |

### `factorlab run <spec.yaml>`

计算因子并评估的端到端命令（平台库数据源）：

- 数据源：`settings.platform_db`（`data/factorlab.duckdb`，可用 `FACTORLAB_PLATFORM_DB`
  环境变量覆盖）。
- `--universe U`：覆盖 spec 的 universe（6 位代码或 universe 引用名/文件路径）；
  缺省时回落 `settings.default_universe`（`FACTORLAB_DEFAULT_UNIVERSE`），
  未配置则用 spec 内联 universe。
- `--max-memory M`：运行期 DuckDB `memory_limit`（默认 `4GB`）。
- `--output-dir DIR`：落盘目录，默认 `settings.results_dir / <spec.name>`
  （`results/`，`FACTORLAB_RESULTS_DIR` 可覆盖——`list`/`show` 扫描同一目录）。
- `--no-float32`：关闭 float32 内存护栏。
- `--backtest/--no-backtest`：默认产出分层回测并写入 evaluation；`--no-backtest`
  关闭（快速评估，weekly 落盘不受影响）。
- `--groups N`：分层档数（默认 10，`N >= 2`）。
- 落盘：`panel.parquet`（run_factor 日频面板）、`weekly.parquet`（周频对齐面板——
  评估/回测输入）、`summary.json`（run_factor 摘要 + `evaluation` 字段——quant_core
  周频评估 + `layered_backtest` 分层回测，CLI 层追加后重写）。
- 错误路径以非 0 退出并打印原因：spec 不存在、平台库缺失、universe 无有效股票、
  公式/process 校验失败等。

示例：

```bash
factorlab run factor/demo.yaml --universe 600519 --output-dir out/run1
factorlab run factor/demo.yaml --groups 5          # 5 档分层回测
factorlab run factor/demo.yaml --no-backtest       # 仅评估，不产分层回测
```

### `factorlab list` / `factorlab show <name>`

`run` 后的运维闭环（同 `results_dir` 锚定）：

- `factorlab list`：扫描 `results_dir/*/summary.json`（损坏/不可读的跳过），按运行
  时间倒序展示 `name | category | dir | ic_mean | spread | run_at`；无结果时提示
  「暂无因子结果（先运行 factorlab run）」。
- `factorlab show <name>`：读 `results_dir/<name>/summary.json`，展示 spec 原文、
  `evaluation.ic` 与 `layered_backtest.summary`（各档 + long-short 摘要指标）；
  因子不存在或读取失败以非 0 退出并打印原因。

示例：

```bash
factorlab list
factorlab show demo
```

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
- `adjustment`：复权视图口径 `raw | qfq | hfq | pit_qfq`，默认 `qfq`（`pit_qfq`
  研究日视角防未来：`run_factor` 装配传 `asof=spec.date.end`，date.end 缺省用面板
  数据末端日期——见 §4 `run_factor`）。
- `operators`：可选 DSL 宏映射。`name: {params: [p1, p2, ...], formula: "..."}`，
  `formula` 中按位置引用 `params`；公式内 `name(args)` 调用在计算前展开为
  `formula`（参数 AST 绑定替换，展开先于平台薄封装；公式内 `def` 同名函数优先）。
  宏公式须为单表达式（`mode="eval"`），可引用平台薄封装（`returns` 等）与 `ts_*` 算子；
  展开后数据列引用（如宏公式内的 `volume`）自动纳入加载。
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

装配完整链路：universe 解析 → `load_daily`（含 `adj_factor`）→ 停牌补全 →
前向收益（total_return 口径，raw close×adj）→ 复权视图（`adjustment` 口径，
因子计算使用）→ `compute_formula` → process 链 → 落盘 `panel.parquet` + `summary.json`。
周频对齐在评估阶段（`eval`）进行，run_factor 输出日频面板。

`RunContext` 字段：`db_path`（默认 `settings.platform_db` = `data/factorlab.duckdb`）、
`output_dir`、`universe_override`（6 位代码或引用名称/路径，优先级最高）、`float32`、
`adjustment`（复权视图口径兜底 `raw|qfq|hfq|pit_qfq`，默认 `qfq`；spec 声明
`adjustment` 时以 spec 为准——spec 字段默认 qfq，未声明时即用默认值）。

**pit_qfq 消费（M4b）**：spec `adjustment=pit_qfq` 时复权视图调用
`view_prices(panel, "pit_qfq", asof=spec.date.end)`——研究日视角（asof 之后无信息）；
`spec.date.end` 缺省时 `asof` 取面板数据末端日期。`spec.date.end` 为字符串，
装配内转 `datetime.date`（view_prices 的 asof 只接受 date 对象）。

`FactorResult`：`spec`、`panel`（列：`date, code, signal, forward_return_5d, forward_return_20d, close`，
其中 close 为复权视图价格）、
`summary`（含 spec 原文、codes、universe_count、panel_rows、signal_null_ratio、process、
adjustment、float32）。

补全面板按交易日历截断到今天（trade_cal 含未来公告日，不产生未来 null 行）。

`factors`/`combine` 多因子组合暂不支持（NotImplementedError，M4 实现）。

### `factorlab.eval.rust_ic.evaluate_factor_weekly(panel, factor_name, direction, target="forward_return_5d") -> dict`

日频面板 → 周频对齐（ISO 周最后交易日）→ Rust `quant_core.evaluate_factor`
评估。输入须含 `date/code/signal/target` 列，缺列抛 `ValueError`；`signal`/`target`
为 null 的行在桥接层过滤（停牌补全行、尾部无未来收益行不进入评估）。

返回 dict：`factor`、`target`、`n_weeks`、`ic`（mean/std/t_stat/ir 等）、
`decile_returns`（含 spread）、`turnover`、`coverage`（pct_valid/total_rows/valid_rows）。
空面板（列齐全）不崩溃，返回全 nan 结构（`n_weeks=0`）。`direction` 透传
`1/-1`（翻转信号方向）。

### `factorlab.data.universe.resolve_codes(spec, db, override=None, settings=settings) -> list[str]`

universe 解析优先级：`override` > spec 内联（`ref` 命名引用 / `codes` / `rules`）。
返回纯数字代码列表（`daily.code` 格式）。命名引用查 `~/.factorlab/universes/<name>.yaml`
（或直接给文件路径）。`default_universe`（`FACTORLAB_DEFAULT_UNIVERSE`）由
`factorlab run --universe` 缺省时消费（M4a 已接线）。

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

`neutralize` 的行业依赖平台库 `stock_basic` 静态行业（v1 近似）；`size` 按
`daily_basic.total_mv` 每日期内排名十分位分桶后组内 demean（无 daily_basic 匹配时报错）；
截面 N<10 时 size 中性化每桶 1 只股票，demean 恒 0（分组式中性化固有属性）。

零方差截面（standardize/robustzscore）输出 null（NaN 不是 null，fillna 无法处理）。

### `factorlab.engine.forward.compute_forward_returns / align_weekly`

前向收益 **total_return 口径** `close[t+h]×adj[t+h] / (close[t]×adj[t]) - 1`
（含分红再投资；输入须停牌补全且 close 为 raw 价格——先于复权视图计算，避免二次复权）；
签名 `compute_forward_returns(df, horizons=(5, 20), close_col="close", adj_col="adj_factor")`，
缺 adj 列时显式报错。
`align_weekly` 对齐到 **ISO 周**最后一个交易日（跨年日期同属 ISO 周时合并为该周
最后交易日，与 tushare weekly 语义一致；M4a 起由 `eval` 使用）。

### `factorlab.eval.rust_ic.evaluate_factor_weekly`

周频评估桥接：日频面板 → 周频对齐（`align_weekly`）→ Rust `quant_core.evaluate_factor`。
签名 `evaluate_factor_weekly(panel, factor_name, direction, target="forward_return_5d") -> dict`，
`panel` 需含 `date`（pl.Date）、`code`（str）、`signal`、`target` 四列，缺列抛
`ValueError`（中文消息，含缺失列名）。`direction` 约定 `1`（多）/`-1`（空）。
返回 quant_core 原始 dict（`factor`/`target`/`n_weeks`/`ic`/`pearson_ic`/
`decile_returns`/`turnover`/`coverage`），另附加 `factor_name` 字段；内部 `factor`
恒为 `"_factor"`（quant_core 内部列名约定）。

行为约定（实测）：
- `signal`/`target` 为 null 的行在桥接层**过滤**（quant_core 拒绝 Python `None`，
  实测 `TypeError: must be real number`）；停牌补全行与尾部无未来数据的 forward
  行均不进入评估。`NaN` 不属 null，quant_core 容忍（实测）。
- 空面板（列齐全）不报错，透传后返回全 `nan` 结构（`n_weeks == 0`）。
- 列检查先于周频对齐：缺列的裸 `date`/`code` 空表（Null dtype）也报 `ValueError`，
  而非 polars dtype 错误。
- `direction` 原样透传为 int（`0` 实测按 `-1` 处理，属 quant_core 内部语义，桥接层
  不校验）。

### `factorlab.eval.layered.layered_backtest(panel, direction, n_groups=10, cost=0.0) -> dict`

分层回测：每期按 signal 分档，各档 forward 等权平均累积净值；long-short = 最佳档 −
最差档净值差。输入**周频面板**（date/code/signal/forward_return_5d，即
`align_weekly` 输出）；`cost` 参数预留（当前不建模调仓成本）。

语义：

- **方向感知**：`direction=1` 时 D1 = signal 最高档，`direction=-1` 时 D1 = signal
  最低档（rank 降序/升序控制，两者都是"最佳档"）；分档边界 `(rank-1)*n_groups//n`
  自然处理（n 不整除时末档更小）。
- **期数口径**：signal/forward 为 null 的行不参与分档与收益（周内部分行 null 的周
  仍计入，组内等权平均忽略 null）；某周**全部**行无效（头部 ts 窗口未满/尾部无未来
  收益）则该周不计入 `periods`——与 `evaluate_factor_weekly` 的 `n_weeks` 口径一致
  （`bt["periods"] == evaluation["n_weeks"]`）。
- **档空期**：某期某档无股票 → 该档收益记 0（fill_null(0)，净值保持前值，不跳变）。
- 年化：周收益均值 × 52；年化波动：std × √52；夏普 = 年化收益/年化波动（vol=0 时
  记 0.0 退化）；最大回撤 = 净值峰值到谷值最大跌幅；胜率 = 周收益 > 0 比例。

返回结构：

```python
{
  "n_groups": 10,
  "periods": 98,                      # 回测期数 = 有效周数（= 评估 n_weeks）
  "net_values": {                     # 各档净值序列 + long_short（每期一点，长度 = periods）
    "D1": [1.0, 1.01, ...], ..., "D10": [...],
    "long_short": [1.0, 1.02, ...],   # D1 − D10 净值差（非组合净值）
  },
  "summary": {                        # 每档 + long_short 的摘要指标
    "D1": {"annual_return": ..., "annual_vol": ..., "sharpe": ...,
           "max_drawdown": ..., "win_rate": ...},
    "long_short": {...},
  },
  "dates": ["2024-01-05", ...],       # 净值序列对应日期
}
```

边界：空面板或过滤后无有效行（signal 全 null）→ `periods=0`、`net_values={}`、
`summary={}`（不崩溃、不产出平值假净值）；单期面板正常返回（各序列长度 1）。

CLI 消费：`factorlab run` 默认调用并把结果写入
`summary.json.evaluation.layered_backtest`（`--no-backtest` 关闭、`--groups` 调档数）。

### `factorlab.data.adjust.view_prices / total_return`

价格视图（输入 raw 价格面板，含 `adj_factor` 列；输出含 scaled 价格列）：
`view_prices(df, view="qfq", asof=None)`，`view ∈ raw|qfq|hfq|pit_qfq`：
- RAW 原样；QFQ `×adj/adj[latest]`（最新因子基准）；HFQ `×adj`（连续价格）；
  PIT_QFQ `×adj/adj[asof]`（研究日视角防未来，必须给 `asof`）。
- QFQ/PIT_QFQ 按 code+date 排序后计算，latest 语义基于日期而非行序；跨 code 独立。
- 停牌补全行的 adj 为 null：QFQ 的 latest 与 PIT_QFQ 的 asof 基准跳过 null
  （窗口末行/截止日补全行不污染整组），补全行价格保持 null。

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
  **表已存在时 INSERT 前过滤 df 中表不存在的列**：`build_final_db` 稀疏剔除后
  refresh 用全字段 df 写最终库不再 Binder 报错（此前被 except 吞掉 → 数据永不
  更新），仅插入存在的列；表不存在时按 df 全字段建表（首插路径不变）。
- `upsert(table, df, keys)`：公共 API，每次自开连接，`dedup=True` 保持去重语义。
- `query(sql, params=None) -> pl.DataFrame` / `list_tables()` / `describe(table)` /
  `integrity_check() -> dict`。

### `factorlab.data.rebuild` 全量重建编排

- `load_manifest(path) -> dict` / `save_manifest(path, manifest)`：断点续传
  manifest 读写（每批落盘）。结构：`{table: {completed: [dates], failed: [dates]}, last_updated: "YYYYMMDD"}`。
- `RebuildScope(start="20000104", end=None)`：重建日期范围（end 缺省 20261231）。
- `rebuild_all(db, client, scope=RebuildScope(), resume=True, manifest_path=None) -> dict`
  编排时序：trade_cal（is_open=1 过滤，无交易日报错；**未来公告日截断到 today**——
  真实 API 返回未来日，避免为未来日白拉请求）→ stock_basic（L/D 分页）→
  行情 7 表按日（DAILY_TABLES，单连接复用，completed 跳过、failed 记录）→
  index_daily（4 指数全历史，ts_code 参数）+ index_weight（每月最后一个交易日，
  **index_code 参数**——真实 API 必填 index_code 而非 ts_code；upsert 键
  `["index_code", "trade_date"]`）。**M3b v1 不含财报三表**（真实 API 强制 ts_code，
  全市场按报告期不可行；`FINANCIAL_TABLES` 常量保留，M3b+ 按 ts_code 分批拉取）。
  manifest_path 缺省 `settings.data_dir / "manifest.json"`。
  resume=True 跳过 completed、重试 failed（成功后移除）；resume=False 忽略既有
  manifest 全量重拉。缺 token 抛 `ValueError`。返回
  `{"tables": {table: {"dates_fetched"/"month_dates", "rows", "failed"}}}`。
  `last_updated` = 截断后的最近交易日（< today，refresh 增量窗口起点）。
- `assess_sparsity(db) -> {table: {col: {null_ratio, stock_coverage, first_date}}}`
  每表每字段稀疏度评估。键列（trade_date/cal_date/ts_code/exchange/index_code）与
  trade_cal 不参与；无日期列的表 first_date 为 None；空表字段 null_ratio 记 1.0。
- `build_final_db(staging, final_path, null_threshold=0.2, coverage_threshold=0.8) -> dict`
  按稀疏度重建最终库（物理剔除超限字段）：任一超限（null_ratio > 阈值 或
  stock_coverage < 阈值）即剔除；无保留列的表跳过建表；最终库已存在时整体替换
  （CREATE OR REPLACE）。返回
  `{"excluded_fields": {table: [cols]}, "tables": [最终库表]}`。staging 库不存在抛
  `ValueError`。

常量：`DAILY_TABLES`（7 行情表）、`FINANCIAL_TABLES`（3 财报表，M3b v1 不拉取，
M3b+ 按 ts_code 分批）、`INDEX_CODES`（4 指数）。

### `factorlab.data.refresh` 增量续拉

- `refresh(db, client, manifest_path=None) -> dict`
  增量续拉行情 7 表（DAILY_TABLES）：重试 manifest 中 failed 日期，并从
  last_updated 续拉到最新交易日（`datetime.date.today()`）。manifest_path 缺省
  `settings.data_dir / "manifest.json"`。返回
  `{"new_dates": [处理日期], "tables": {table: {"rows": 新拉行数, "failed": [失败日期]}}}`。
  行为：起始日期取最早 failed 日（若有，覆盖 ≤ last_updated 的重试窗口），
  trade_cal 按 is_open=1 过滤，取 `> last_updated` 或 failed 的日期；无新日期直接
  返回空报告（不改写 manifest）。逐表逐日拉取，`upsert` 默认 `dedup=True`——崩溃
  窗口重拉已存在日期按 (trade_date, ts_code) 去重替换（与 rebuild 的 dedup=False
  不同）；成功日期加入 completed 并从 failed 移除，失败日期记入 failed（下次
  refresh 重试，与 rebuild 同语义），单日失败不阻塞其他日期/表。处理后
  `last_updated` 推进到处理范围末端（failed 日也算已处理，避免重复拉）并落盘。
  **死锁修复语义**：rebuild 已将 `last_updated` 截断为最近交易日（< today），
  trade_cal 请求 `start_date=last / end_date=today`，`d > last` 即增量窗口——不会
  出现 last_updated 为未来日导致永久无新日。
  错误语义：manifest 缺失或 `last_updated` 不存在抛
  `ValueError("manifest 无 last_updated，请先 rebuild")`；trade_cal 缺 `is_open`
  列或返回异常时异常向上传播（fail-loud，不静默）。

### `factorlab.data.verify` 数据验证与抽样对拍

- `verify_all(db, ref_db=None, n_stocks=30, seed=42) -> dict`
  完整性自检 + 稀疏摘要 + 可选抽样对拍。返回
  `{"integrity": {table: {rule: ...}}, "sparse_summary": {table: {col: ...}}, "compare": dict | None}`。
  ref_db（PlatformDB 或路径）给定且文件存在时执行对拍（参考库仅作参考，差异不
  阻塞，旧参考库清理流程以 verify 报告 + 用户显式确认为准）；参考库缺失时
  `compare` 为 None。空库不抛错：完整性规则逐条 skipped，稀疏摘要为空。
- `compare_sample(primary, ref_path, n_stocks=30, segments=None, tol=1e-4, seed=42) -> dict`
  随机抽样 n_stocks 只股票 × 日期段，对比 primary 与参考库 daily.close（相对误差
  ≤ tol 视为一致）。segments 缺省三段：2020/2023/2026 各 1 月（`SEGMENTS`）。
  种子确定性：同 seed 抽样结果一致；n_stocks 超过库内股票数时抽样全部。
  单侧 close 为 null 记 mismatch，双侧 null（停牌/无数据）不算差异。差异逐条进
  `details`（最多 50 条）。返回
  `{"compared_rows", "mismatches", "details", "sampled_stocks"}`。
  **参考库列结构自动检测映射**（`_ref_query_sql(ref_cols)`）：`DESCRIBE daily` 后
  有 `trade_date/ts_code` 用原列；date/code 风格（`date/code`，日期 `2024-01-02`
  VARCHAR 或 DATE、代码纯数字，旧只读库布局）映射为 `strftime(CAST(date AS DATE), '%Y%m%d')
  AS trade_date`（对齐 primary 的 YYYYMMDD）、`code = substr(?, 1, 6)`（ts_code
  前 6 位）、日期 `CAST(date AS DATE) BETWEEN CAST(strptime(?, '%Y%m%d') AS DATE) ...`
  （显式 CAST：DuckDB 禁止 VARCHAR 与 TIMESTAMP 混用 BETWEEN）。join 只取
  trade_date/close（映射后列名），date/code 之外的参考列不影响。
  错误语义：参考库文件不存在抛 `ValueError("参考库不存在...")`；primary 无 daily
  表返回零报告（含 `note`）；参考库无 daily 表或结构不兼容时返回零报告（含
  `note`）或对应段跳过（duckdb 错误捕获，不阻塞）。primary 为 `PlatformDB`，
  ref_path 接受 `PlatformDB | Path`。

## 5. 测试

运行：

```powershell
python -m pytest
```

当前覆盖 Spec 校验、AST 白名单、算子插件生命周期、最小计算路径、polars_ta 算子族、
平台薄封装、分区校验与防未来函数、CLI smoke、数据平台单元
（fetcher/platform_db/rebuild/sparsity/verify/refresh/adjust/audit）与 CLI data
命令、分层回测（`tests/test_layered.py`：分档/方向翻转/净值数学/long-short/摘要/
无效周排除/全 null 空回测）、run 参数与 list/show（`tests/test_cli_run.py`、
`tests/test_cli_list_show.py`）、真实平台库集成（`tests/test_e2e_m4.py`：
run → 周频评估 + 分层回测，回测期数 = 评估周数），以及 teajoin 集成测试
（token 配置时真实拉取，`tests/test_e2e_data.py`）。

## 6. 数据平台（M3b）

数据平台层以 teajoin（Tushare 兼容代理）为数据源，落地本地 DuckDB 库供因子计算
与回测只读使用。全链路：拉取（TeaJoinClient）→ 落库（PlatformDB）→ 全量重建/增量
（rebuild/refresh）→ 校验（verify）→ 复权视图（adjust）。本节为总览 + CLI 用法；
各模块详细 API 见 `4.x` 对应小节。

### `factorlab.data.fetcher.TeaJoinClient`

teajoin Tushare 兼容代理客户端（全局限流 0.2s、指数退避重试 3 次、4xx 抛
`TeaJoinError`）：

- `fetch(api_name, params, fields=None) -> pl.DataFrame`：单次拉取。`fields` 为
  逗号分隔白名单；空串列自动转 null、纯数值列转 Float64；空数据返回空表。
- `fetch_paged(api_name, params, page_size=5000, max_pages=50, fields=None)`：
  通用分页（limit/offset 注入，空页停止）；超过 `page_size*max_pages` 行抛
  `TeaJoinError`。

token 来自 `FACTORLAB_TEAJOIN_TOKEN`；端点 `FACTORLAB_TEAJOIN_BASE_URL`
（默认 `https://teajoin.com`，根路径）。构造 `TeaJoinClient(token="")` 不报错，
缺 token 由调用方（`rebuild_all` 抛 `ValueError`、CLI 打印错误并退出）处理。

### CLI：`factorlab data rebuild|update|refresh|verify`

`data update`：一键更新链路（手动触发）——行情 7 表增量 + 指数增量
（`refresh_indexes`：index_daily 到最新交易日、index_weight 补新月份）+ 自动 verify
+ 失败报告。操作经验与故障排查见 `docs/data-ops-playbook.md`。

| 命令 | 说明 |
|------|------|
| `factorlab data rebuild [--start 20000104] [--end 20261231] [--resume/--no-resume]` | teajoin 全量重建。先写**暂存库** `data/rebuild_staging.duckdb`（`rebuild_all`，manifest 断点续传），再 `build_final_db` 稀疏剔除重建**最终库** `data/factorlab.duckdb`。缺 token 打印错误并以非 0 退出 |
| `factorlab data refresh` | 增量续拉：读 manifest 的 `last_updated` 与 failed 日期，`upsert(dedup=True)` 更新**最终库** `data/factorlab.duckdb`。缺 token 同 rebuild；manifest 缺失（未 rebuild 过）抛 `ValueError` |
| `factorlab data verify [--compare PATH]` | 完整性自检 + 稀疏摘要（读**最终库**）+ 可选抽样对拍（参考库仅参考，差异不阻塞）。无需 token；最终库不存在时完整性规则逐条 skipped，正常退出 |

路径语义：`rebuild` 写暂存库并重建最终库（两库都在 `settings.data_dir`）；
`refresh`/`verify` 直接操作最终库。`start/end` 为 `YYYYMMDD`（缺省 end 为
20261231）。

### 汇总速查（详细 API 见 `4.x` 对应小节）

- `factorlab.data.platform_db.PlatformDB`：duckdb 写库，自动建表、按 keys upsert
  去重（`dedup=False` 纯 INSERT 批量语义）、`integrity_check()` 六规则自检
  （日历缺日/重复行/pct_chg 自洽/adj_factor 有效/stk_limit 边界/市值有效）。
- `factorlab.data.rebuild`：`rebuild_all`（manifest 断点续传编排：交易日历（未来
  公告日截断）→ 静态 → 行情 7 表按日 → 指数（index_weight 用 index_code 参数）；
  **无财报三表**）；`assess_sparsity`（每表每字段 null_ratio/stock_coverage/
  first_date）；`build_final_db`（null_ratio > 20% 或 stock_coverage < 80% 的字段
  物理剔除后重建最终库）。
- `factorlab.data.refresh.refresh`：从 manifest `last_updated`（rebuild 截断后的
  最近交易日）增量续拉行情 7 表，重试 failed 日期，`upsert` 默认 `dedup=True`
  去重替换。
- `factorlab.data.verify`：`verify_all` 完整性 + 稀疏摘要 + 抽样对拍（30 只 ×
  三段 × 相对误差容差 1e-4）；`compare_sample` 自动映射参考库列结构
  （trade_date/ts_code 或 date/code 风格），对拍细节与错误语义见 `4.x`。
- `factorlab.data.adjust`：`view_prices`（raw/qfq/hfq/pit_qfq 价格视图）、
  `total_return`（HFQ 含分红再投资收益）、审计三查（`lookahead_check` /
  `scale_invariance_check` / `adjustment_sensitivity_check`）。
