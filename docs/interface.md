# FactorLab 接口文档（M1–M5）

本文件描述 M1–M5 已交付的 CLI、Spec、因子脚本和 Python API。实现与设计文档
冲突时以 `docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md` 为准。

## 0. M5 汇总：Web 可视化

M5 在 M4b 结果落盘（summary.json/weekly.parquet）之上补齐浏览器可视化闭环：

- **`factorlab serve`**（`--port`/`--host`，默认 `127.0.0.1:8000`）：只读启动
  Web 服务，可视化 `settings.results_dir`（`FACTORLAB_RESULTS_DIR` 可覆盖）下
  已保存因子（见 §1 与 §4 `factorlab.web`）。
- **web 包**（`factorlab.web`）：`app.create_app(results_dir)` 构建 FastAPI 只读
  应用——列表 `/` + 详情 `/factor/<name>`，Jinja2 模板 + Plotly 图表内嵌；
  `charts` 构造 IC 曲线/十分位柱状/分层净值 figure JSON；缺失/损坏 summary 与
  缺 evaluation 字段的因子降级展示不崩溃（见 §4）。
- **`factorlab.eval.ic_series.weekly_ic`**：周度 RankIC 序列（Spearman 秩相关，
  与 quant_core 同源定义；signal/target null 过滤、有效股票 < 3 的周 ic = null），
  详情页 IC 曲线数据源（见 §4）。
- 集成测试 `tests/test_e2e_web.py`：真实 results 目录（main 工作树，3 个因子）
  冒烟——列表含因子名、详情含图表数据、旧因子降级、缺失 404（见 §5）。

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
| `factorlab run <spec.yaml> [--universe U] [--max-memory M] [--output-dir DIR] [--no-float32] [--backtest/--no-backtest] [--groups N] [--set k=v ...] [--chunk-days N] [--warmup-days N]` | 计算因子并周频评估 + 分层回测（默认），落盘 `results/<name>/`（`--set` 生成 `results/<name>_<k><v>.../` 参数变体；`--chunk-days` 日期分块，见 §运行-分块计算） |
| `factorlab list` | 列出已保存因子与最近运行摘要（扫描 `results_dir/*/summary.json`，按运行时间倒序） |
| `factorlab show <name>` | 查看单因子完整摘要（spec 原文/评估/分层回测） |
| `factorlab corr <name1> <name2> ...` | 因子两两相关性（≥2 个）：周度横截面秩相关均值 + 全局 Pearson；任一因子无 results 报错（数据源 `results/<name>/panel.parquet` 的 signal，按 date+code inner join；join 后超 2000 万行每周降采样 5000 只） |
| `factorlab svd [name1 ...] [--weeks 15]` | 因子库 SVD 分解：奇异值谱 + 主成分载荷（因子结构/有效维度分析）；缺省 names = 全部有 panel 因子（排除验证目录）；抽样 weeks 个交易周（concat+pivot 单次操作，规避多 join 段错误） |
| `factorlab op list` | 列出已注册算子 |
| `factorlab op doc <name>` | 查看算子名称、类别、版本与 docstring |
| `factorlab op add <plugin.py> [--force]` | 校验并注册用户插件；同名冲突需 `--force` |
| `factorlab op remove <name>` | 禁用用户插件，保留已计算历史结果 |
| `factorlab serve [--port 8000] [--host 127.0.0.1]` | 启动只读 Web 可视化（浏览器查看已保存因子列表与图表，扫描 `results_dir`） |

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
- `--set k=v`（可多次）：覆盖 spec 的 `params`（见 §2），生成**参数变体**——
  变体名 `<spec.name>_<k><v>...`（如 `vol_run_energy_win100_gain1.5`），results
  独立目录，与默认变体（`results/<name>/`）并存不覆盖。值类型解析
  int → float → bool（`true/false`）→ str；格式错误（缺 `=` 或空值）以非 0
  退出提示。`--output-dir` 显式给出时优先于变体目录。
- `--chunk-days N`：日期分块（交易日/块，`N >= 1`；缺省单块整段跑）。长样本
  （2015+ 全市场）超过 16GB 内存护栏时使用，语义保证与整段跑逐 cell 一致
  （见下方"分块计算"）。
- `--warmup-days N`：TS 窗口预热天数（`N >= 0`；缺省按公式自动提取窗口最大值
  + 20 安全垫）。
- 落盘：`panel.parquet`（run_factor 日频面板）、`weekly.parquet`（周频对齐面板——
  评估/回测输入）、`summary.json`（run_factor 摘要 + `evaluation` 字段——quant_core
  周频评估 + `layered_backtest` 分层回测，CLI 层追加后重写）。
- 错误路径以非 0 退出并打印原因：spec 不存在、平台库缺失、universe 无有效股票、
  `--set` 格式错误、公式/process 校验失败等。

示例：

```bash
factorlab run factor/demo.yaml --universe 600519 --output-dir out/run1
factorlab run factor/demo.yaml --groups 5          # 5 档分层回测
factorlab run factor/demo.yaml --no-backtest       # 仅评估，不产分层回测
factorlab run factor/demo.yaml --set win=100       # 参数变体（results/demo_win100/）
factorlab run factor/demo.yaml --set win=100 --set gain=1.5   # 多变体参数
factorlab run factor/crash_bottom_leader_timed.yaml --chunk-days 500   # 2015-2026 分块计算
```

### 分块计算（`--chunk-days`）

长样本（2015+）全市场面板的 date×code 全网格超过 16GB 无页面文件内存护栏时
（实测 ~850 交易日可跑、再长段错误），按交易日分块计算：日历切成
`--chunk-days` 交易日/块，每块独立跑完整流水线（加载→停牌补全→前向收益→
复权视图→因子→process），块间无数据依赖，最后拼接。

**语义保证**（与单块整段跑逐 cell 一致，回归测试验证）：

- TS 窗口（`ts_*`/`ta_*`）：每块带 warmup 重叠段（自动提取公式窗口最大值
  + 20 天安全垫，覆盖 `ts_delay` 等偏移；纯横截面公式 warmup=0），窗口历史完整；
- CS 算子（`cs_rank`/process 链的 winsorize/standardize 等 per-date 横截面）：
  块内每日期全市场股票完整，结果与整段跑一致；
- qfq 复权：块内 `adj_factor` 按全局基准（样本末每代码最新 adj）归一，绝对水平
  类因子（直接用 close 值的公式）跨块一致；hfq/pit_qfq 无需处理（hfq 无基准；
  pit_qfq 的 asof 全局固定）。

**已知限制**：

- 每块块尾的 `forward_return_h` 为 null（块尾无未来数据；单块跑只有样本末如此），
  周频评估时该周跳过，块大小 500 天时损失 <1%；
- process 链的 `fillna(method="forward")` 在块首重新填充，块边界前几行与单块跑
  略异（低频使用）；
- 块大小 + warmup 应控制在约 850 交易日以内（单块内存 ≈ 已验证可跑的
  3.5 年量级）。

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

### `factorlab serve`

run 后运维闭环的可视化环节（同 `results_dir` 锚定，只读）：

- 启动只读 Web 服务，浏览器打开 `http://127.0.0.1:8000/` 查看因子列表与单因子
  图表（周度 RankIC 曲线/十分位收益/分层回测净值，Plotly 内嵌）。
- `--port 8000` / `--host 127.0.0.1`：监听地址（默认仅本机回环）。
- 只读：不写 `results_dir`，不依赖平台库（图表数据来自落盘的 `summary.json`
  与 `weekly.parquet`）；损坏 summary 列表页跳过、详情页 404（与 `list`/`show`
  缺失兼容一致）。

示例：

```bash
factorlab serve                       # http://127.0.0.1:8000/
factorlab serve --port 9000 --host 0.0.0.0
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
- **daily_basic 扩展字段**：公式可引用 `turnover/total_mv/circ_mv/pe_ttm/pb/dv_ratio/
  volume_ratio`（daily_basic left join 自动加载，历史早期覆盖不足 → 缺失传播，
  以 `signal_null_ratio` 呈现）。经典价值/技术因子（`value_bp`、`turnover_level` 等）
  依赖这些字段。
- `params`：可选顶层参数映射 `dict[str, number|str|bool]`（缺省空）。formula（含
  operators 宏体、def 体）内 `${name}` 文本引用在编译期替换为字面量；引用未声明
  的参数名报错。`factorlab run --set k=v` 覆盖（合并进 spec.params）并生成变体
  （见 §1 run）。例：
  ```yaml
  params: {win: 200, gain: 2.0}
  formula: |
    signal = ts_rank(volume, ${win}) * ${gain}
  ```
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
- **`def` 内窗口/截面算子合法**（free-form）：计算前 `def` 经**内联展开**（参数
  绑定、中间变量提升到顶层、唯一命名防冲突）——窗口算子成为顶层 `ts_*` 调用，
  按 asset 分区正确，无跨资产泄漏。支持多语句函数体、def 调 def（不依赖定义
  顺序）；边界：递归 def（含间接）拒绝、函数体仅支持赋值与单个带返回值
  `return`、`_` 前缀不能作 def 名（中间变量约定）。
- **元素级方法链**：`ts_delta(x, 1).abs()` 语法合法——AST 门放行白名单
  （`abs/log/log1p/sqrt/exp/sign/floor`，与元素级函数名单同源）方法在表达式结果
  上的调用，计算前改写为函数调用 `abs(ts_delta(x, 1))`（expr_codegen 的 AST
  处理不支持属性调用）。模块/对象属性调用（`np.abs`、`pl.read_csv`）与窗口方法
  （`x.rolling_mean`）仍被拒——窗口语义必须走 `ts_*` 算子。
- **参数引用**：formula 内 `${name}` 文本引用 spec.params（见 §2 `params`）——
  宏体/def 体内同样可见，编译期替换为字面量。
- 平台薄封装算子（`returns/vwap/adv20`）在解析期**展开为 `ts_` 表达式**再交给
  `expr_codegen`，保证按 asset 分区；`group_rank/group_mean` 自带 `.over(key)`
  分组语义，不展开。import 别名（`returns as ret`）同样生效。
- 元素级纯函数白名单（与 codegen 作用域核对，**实测**）：`abs/exp/floor/log/log1p/sign/sqrt`——
  **注意**：白名单不含 `if_else`（用 `(x+abs(x))/2` 表达 `max(x,0)`）；方法链 `.abs()` 等
  的基表达式不可为裸 Name（如 `_d.abs()` 被拒，需用 `abs(_d)` 函数形式）。

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

### `factorlab.ops.platform_ops.inline_defs(source) -> str` / `rewrite_expr_methods(source) -> str`

free-form 源码变换（`compute_formula` 与 `run_factor` 展开链内自动调用，用户一般
无需手动使用）：

- `inline_defs(source)`：公式内 `def` 内联展开——窗口算子合法化为顶层 `ts_*`
  调用（分区正确），多语句提升、def 调 def 递归展开、多次调用独立实例化
  （唯一命名防变量串扰）。无 def 原样返回（幂等）。递归 def（含间接）抛
  `FactorDSLError`。
- `rewrite_expr_methods(source)`：元素级方法链改写为函数调用（`X.method(...)` →
  `method(X, ...)`，白名单与 ast_gate 的 `ALLOWED_EXPR_METHODS` 同源）。
  无方法链原样返回。

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

**free-form 展开链**（spec.formula 处理顺序）：`${param}` 文本替换（spec.params；
operators 宏体经副本一并替换，def 体在 formula 文本内命中；未知参数名抛
`ValueError`）→ 用户宏展开（spec.operators，宏体可引用 `${}`）→ AST 校验 →
def 内联（窗口算子合法化）→ 元素级方法链改写 → 平台薄封装展开。
`factorlab run --set k=v` 在 CLI 层合并进 spec.params 并生成变体名
`<name>_<k><v>...`（见 §1 run；summary 的 `spec_yaml` 保留合并后的 params）。

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

`factors`/`combine` 多因子组合不在平台范围（平台定位单因子计算与评估；语法保留校验但执行时明确拒绝）。

### `factorlab.eval.rust_ic.evaluate_factor_weekly(panel, factor_name, direction, target="forward_return_5d") -> dict`

日频面板 → 周频对齐（ISO 周最后交易日）→ Rust `quant_core.evaluate_factor`
评估。输入须含 `date/code/signal/target` 列，缺列抛 `ValueError`；`signal`/`target`
为 null 的行在桥接层过滤（停牌补全行、尾部无未来收益行不进入评估）。

返回 dict：`factor`、`target`、`n_weeks`、`ic`（mean/std/t_stat/ir 等）、
`decile_returns`（含 spread）、`turnover`、`coverage`（pct_valid/total_rows/valid_rows）。
空面板（列齐全）不崩溃，返回全 nan 结构（`n_weeks=0`）。`direction` 透传
`1/-1`（翻转信号方向）。

### `factorlab.eval.ic_series.weekly_ic(panel, target="forward_return_5d") -> pl.DataFrame`

周度 RankIC 序列：每期（周）signal 与 target 的 Spearman 秩相关——与
`quant_core` 的 RankIC 同源定义（秩相关即秩的 Pearson，polars 1.38
`pl.corr(method="spearman")` 直接支持）。输入须含 `date/code/signal/target`
四列，缺列抛 `ValueError`（不依赖 polars 内部异常）；`signal`/`target` null
行排除（复用 rust_ic 的过滤语义）。面板中每个日期都保留一行：有效股票 < 3
（`MIN_STOCKS`）的周 ic = null（秩相关不稳健，含有效股票为 0 的周）。
返回 `(date, ic)` 按日期排序——`factorlab.web` 详情页 IC 曲线数据源。

### `factorlab.web`：Web 可视化（M5）

只读 FastAPI 应用，可视化 `results_dir` 下已保存因子（M4b 落盘产物）：
`factorlab.web.app.create_app(results_dir: Path) -> FastAPI`，results_dir
显式传入（可测性）。

路由：

- `GET /`：因子列表页——扫描 `results_dir/*/summary.json`（损坏/不可读跳过，
  不中断列表），展示 name/category/direction/ic_mean/spread/run_at。
- `GET /factor/{name}`：单因子详情页——读 `summary.json`（缺失/损坏 → 404，
  与 spec §3.2 缺失兼容一致），渲染指标表 + 图表：周度 RankIC 曲线
  （`weekly.parquet` + `weekly_ic`）、十分位收益柱状（`decile_returns.groups`）、
  分层回测净值（`layered_backtest.net_values`）；缺 weekly.parquet 或
  evaluation 字段时对应图表/指标降级（空串/空图），页面不崩溃。
- `GET /static/*`：静态资源（plotly.min.js 等）。

图表构造（`factorlab.web.charts`，返回 plotly figure JSON 字符串内嵌模板）：
`ic_curve_figure(ic_series)`（周度 RankIC 折线，含 0 参考线）/
`decile_bar_figure(groups)`（十分位平均收益柱状）/
`layered_net_value_figure(net_values, dates)`（分层净值曲线，dates 空时 x 缺省）。

模板与静态文件在 `src/factorlab/web/{templates,static}/`；CLI 入口
`factorlab serve`（见 §1）。

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

### Canonical research identifier 与 source partition（M6-07B4）

**背景**：vendor（TeaJoin/Tushare）`stock_basic` 可能含历史遗留别名/实体标识，
超出 canonical 六位 A 股证券代码域（实测：`T600018.SH`/`TS0018.SH`——上港集箱
退市残留；平台冻结库亦含此两行，均无 `daily` 行情）。这些行**不映射、不合并、
不删除、不猜测关系**——M6 无 verified corporate-action/entity-lineage 模型。

**Canonical research universe v1**（唯一权威：`factorlab.domain.codes`）：

```
ts_code 匹配 ^\d{6}\.(SH|SZ|BJ)$  且  symbol == ts_code 前六位
```

- `is_canonical_stock_code(ts_code) -> bool`：ts_code 形态判断（None/非 str → False）。
- `CANONICAL_TS_CODE_PATTERN`：Python re 与 DuckDB `regexp_matches()` 共用同一
  pattern 常量——rebuild/universe 代码不得独立重写该正则。

**Source partition**（`factorlab.data.rebuild`）：

- `StockBasicSourcePartition(canonical, quarantined)`（frozen dataclass）：
  - `canonical`：标准证券，完整走 `validate_stock_basic_source()`——endpoint
    L/D 正确性、日期、temporal、uniqueness、symbol 全部保持 fail fast（canonical
    D 行缺 delist_date 依然 BLOCK）。
  - `quarantined`：非 canonical 的**退市** vendor alias，保留自身标识，仅供
    audit/migration report——不参与 PIT universe、不进 future rebuild 的
    research `stock_basic`。**隔离 ≠ 合并**。
- `partition_stock_basic_source(l_df, d_df) -> StockBasicSourcePartition`：
  分类前置 fail fast 与 validator 同契约（L/D 非空、必需列、endpoint status
  分区含 null 显式拒绝）。quarantine 候选四条件全 true 才进入：
  `list_status==D` + ts_code 非 null + symbol 非 null + ts_code 以
  `.SH/.SZ/.BJ` 结尾 + `symbol == ts_code 去后缀`。quarantined D 允许
  delist_date=null。其余任何形态（非 canonical 且 L、unsupported suffix、
  null、symbol/base mismatch）→ fail fast。**禁止硬编码别名清单**——规则来自
  标识类别与 source 语义。
- `fetch_stock_basic_source(client) -> StockBasicSourcePartition`：L/D 分页
  fetch → partition（quarantine 审计可见，不静默丢弃）。
- `fetch_stock_basic_all(client) -> pl.DataFrame`：兼容 API，**canonical-only**
  （future rebuild 的 research stock_basic 只收 canonical 行）。

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

## 4.1 Domain contracts（M6-01）

统一研究语义层（`factorlab.domain`）——Signal / Label 领域契约与信号时间语义。
**本层为新增能力，尚未接线到现有因子计算链路**（factorlab run/list/corr/svd/serve
行为不变）。

### 时间语义（`factorlab.domain.timing`）

```python
SignalTiming(information_cutoff, available_at, default_earliest_execution)
DEFAULT_EOD_SIGNAL_TIMING   # CLOSE / AFTER_CLOSE / NEXT_OPEN
```

含义：**使用 t 日完整 OHLCV 的日频 EOD 信号，在 t 日收盘后才可获得
（AFTER_CLOSE），因此默认最早只能在 t+1 open 执行（NEXT_OPEN）**。
对象 frozen 不可变；本阶段不实现 calendar/execution timestamp 计算。

### 领域对象（`factorlab.domain.frames`）

| 对象 | 契约 |
|---|---|
| `SignalMeta` | name / frequency（当前仅 `1d`）/ timing / adjustment——frozen |
| `SignalArtifact` | frame + meta；必需 `date`(pl.Date) / `code`(pl.String) / `signal`(numeric)；`(date, code)` 唯一；允许额外非未来列 |
| `LabelArtifact` | frame；必需 `date` / `code` + 至少一个 `forward_return_<N>d`（任意 horizon） |

**SignalArtifact 显式禁止 future-return / label 字段**：`forward_*` / `future_*`
前缀与 `target` / `label` 精确字段一律拒绝（`ValueError`），重复 `(date, code)`
直接失败（不静默去重），dtype 错误直接失败（不自动 cast）。

LabelArtifact 供因子研究评估使用（可合法包含未来信息），**不得进入未来
Strategy Runtime**。Signal / Label 边界是 M6 最重要的 domain invariant。

## 4.2 PIT Universe（M6-02）

两阶段 Universe 模型：**Candidate Universe（数据加载候选集）→ PIT Eligibility（逐日 membership）**。
Universe membership ≠ tradability（M6-02 不实现 can_buy/can_sell——M8 Execution 职责）。

| API | 语义 |
|---|---|
| `resolve_codes()` | **legacy/static**：全期共用一组静态代码（含最新 ST 快照过滤与 date.start 一次性 min_list_days）——候选语义，不用于历史 PIT |
| `resolve_candidate_codes(spec, db, override=None)` | 候选代码集：复用 override/ref/codes/rules 解析；rules 模式**只应用 exchange 与证券标识合法性**——exclude_st/min_list_days 属动态 PIT 条件，禁止提前应用。**M6-07B4**：rules 候选额外要求 canonical research identifier（`regexp_matches(ts_code, '^\d{6}\.(SH\|SZ\|BJ)$')`，pattern 单一权威来自 `domain.codes`）——legacy vendor aliases（如 `T600018.SH`）即使后缀匹配 .SH 也绝不进入候选 |
| `resolve_universe_frame(spec, db, dates, *, override=None, candidate_codes=None)` | date×code PIT membership——接受显式日期集（chunk 友好，不要求全历史生成） |
| `align_to_universe(raw, universe)` | **Universe 驱动**的 active LEFT JOIN raw：raw 不能决定日期是否存在（某日 raw 完全无行 → active date/code 仍输出、行情 null）；universe 外排除。raw 至少 date/code；universe 至少 date/code/in_universe(Boolean)；code 严格 pl.String（前导零证券代码，整数无法无损表示）；duplicate/dtype/缺列 fail fast |

UniverseFrame schema：`date(pl.Date) / code(pl.String) / in_universe / is_listed / list_days / is_st / exchange`，
`(date, code)` 唯一，按 date/code 稳定排序。

PIT 语义：
- **listing**：`is_listed = list_date <= t AND (delist_date IS NULL OR t < delist_date)`（`t < delist_date` 平台语义）
- **list_days**：`date − list_date`（**自然日**年龄，非交易日数）；**pre-list（date < list_date）→ list_days = null**
- **ST coverage**：以 `min/max(stock_st.trade_date)` 为 coverage（v1 contract，内部 gap 的精确 provenance 留给 Data Coverage Registry）——coverage 内：当日快照出现 → true、缺席 → false；**coverage 外：is_st = null（unknown ≠ false）**；`exclude_st=true` 且请求日期落在 coverage 外 → **ValueError（fail fast，错误含 requested date 与 coverage 区间）**；缺 stock_st 表：exclude_st=true → ValueError、false → is_st=null
- **exchange**：ts_code 后缀（.SH→SSE / .SZ→SZSE / .BJ→BSE）；默认池 SSE+SZSE，不意外纳入 BSE
- 显式 codes 同样尊重上市/退市 PIT 状态（不自动增加 exclude_st/min_list_days 规则）
- 输入校验：dates 仅接受 datetime.date / ISO `YYYY-MM-DD`（非法格式、重复日期 fail fast）；candidate_codes 重复 fail fast；输出前主动验证 (date, code) 唯一
- **delist_date 保护**：`stock_basic.delist_date` 是语义关键稀疏字段——`build_final_db` 的 sparsity pruning 不得物理删除（PROTECTED_SPARSE_FIELDS，仅保护显式字段，不关闭整体 pruning）；旧 DB 无 delist_date 列时仍可运行，但 **delisting PIT is incomplete**（不伪造退市日期）

**PIT invariant**：membership at t 不能依赖 t 之后的数据（ST/listing/delisting 均 PIT；
平台库 stock_basic 当前无 delist_date 列时退市信息不可用，is_listed 只基于 list_date）。

## 4.3 Universe-Aware Signal/Label Runtime（M6-03）

`run_factor()` 拆成两条独立 runtime（M6-01 domain contract 正式接线）：

```
Listed Market History → Signal Runtime → SignalArtifact
Listed Market History → Label Runtime  → LabelArtifact
        （PIT UniverseFrame 在两条路径入口：listed skeleton + active mask/keys）
```

- **Signal Runtime**（`engine.compute._compute_signal`）：candidate codes →
  PIT UniverseFrame → load listed market → `align_to_listing`（is_listed skeleton，
  停牌日保留 null）→ fill → 复权视图 → **universe-aware formula** →
  filter(in_universe=true) → process chain → SignalArtifact。**绝不计算 forward returns**。
- **Label Runtime**（`engine.compute._compute_labels`）：listed market →
  `compute_forward_returns` → active-at-t keys → LabelArtifact。t 的 label 只取决于
  t 是否 active——**t+h 的未来 universe membership 不参与 censoring**。
- **legacy panel** = signal LEFT JOIN labels + close（CLI/eval 兼容视图，行为不变）。

### Cross-sectional universe masking（`ops.universe_masking`）

CS/GP 算子的**数据参数**在 AST 层包 `if_else(__universe_active, arg, None)`：
TS/TA 仍见完整 listed history，CS/GP 只见当日 active 横截面。数据参数位置由
`_CS_GP_MASK_ARGS` 显式声明（cs_rank 等单参数；cs_resid(y,x) 双参数全 mask；
group_rank/group_mean 的 group key 不 mask）；**无法确认 mask 语义的 CS/GP
算子 fail fast（ValueError 含 operator name）**。mask 列 `__universe_active`
为内部保留列（来源 = PIT in_universe，用户不得定义），最终 SignalArtifact 不含。

### formula future guard

公式显式引用 `forward_*` / `future_*` / `target` / `label` → ValueError
（"future/label inputs are forbidden in factor formula"）——不等到 load_daily
unknown column。

### FactorResult

```python
@dataclass
class FactorResult:
    spec: FactorSpec
    signal_artifact: SignalArtifact
    label_artifact: LabelArtifact
    panel: pl.DataFrame        # legacy compatibility view
    summary: dict
```
summary 新增 `candidate_count / signal_rows / label_rows / runtime_semantics`；
`universe_count` 保留兼容。M6-03 不落盘 signal.parquet/labels.parquet
（M6-05）；chunk label 尾部缺失保持现状（M6-04）。

### M6-03A hardening（masking boundary）

- **import alias**：masker 与 `validate_partition_calls` 一致解析 alias
  （`from polars_ta.prefix.wq import cs_rank as cs_r` → canonical `cs_rank` 查
  metadata）；**不改写用户 callable**（`cs_r(if_else(...))` 保持）。注：无分区
  前缀的 alias（`as r`）是 expr_codegen 按名前缀分区的平台限制（非 masking 语义）。
- **registry alias**：metadata 一律经 canonical `OperatorDef.name` 查询——
  `factor_op(aliases=...)` 的 alias 不会绕过或误判 mask metadata。
- **keyword arguments**：CS/GP 的 keyword invocation（`cs_rank(x=close)`、
  `group_rank(key=industry, x=close)`）→ fail fast（M6 v1 positional-only，
  masking 无歧义）；TS/TA/elementwise keyword 不受影响。
- **保留名空间**：`__factorlab_*` 为平台内部保留前缀——用户 Assign/AnnAssign
  target、FunctionDef 名、函数参数、import alias 以该前缀开头 → fail fast
  （在 universe masking 变换前校验，覆盖 macro/def 展开路径）。内部 mask 列
  更名为 `__factorlab_universe_active`。

## 4.4 Exact Chunked Labels（M6-04）

chunked run 与 non-chunked run 的 forward labels 在研究样本内部**逐 cell 完全一致**
（right lookahead 只进 Label Runtime）。

每块双窗口：

```
Signal: [ left warmup | output chunk ]         ← 结束于 chunk_end（禁止传 label_end）
Label:                [ output chunk | right lookahead ]  ← 结束于 label_end
         chunk_start     chunk_end       label_end
```

- `label_lookahead_end(cal, chunk_end, horizon)`：chunk_end 向后 horizon 个交易日
  （截断到研究 calendar 最后一天）；chunk_end 不在 calendar / horizon<0 /
  calendar 为空 → fail fast
- **lookahead 可跨内部 chunk boundary，不可跨研究 sample boundary**——最后一块
  label_end = sample 最后一天（5d/20d 尾部 null 保持合法）
- Label Runtime：date_start=chunk_start（无左侧 warmup——forward 只需 t 与 t+h）、
  date_end=label_end；**Signal Runtime 仍只看 <= chunk_end**
- 每块输出双边裁剪 [chunk_start, chunk_end]——lookahead rows 不进任何输出
- 未来 membership 不 censor label（t+h ST/inactive 不影响 t 的 label——listed
  skeleton 承载未来市场历史）
- `DEFAULT_FORWARD_HORIZONS = (5, 20)` 为 horizon 唯一来源（forward.py）

## 4.5 Versioned Result Artifacts（M6-05）

结果目录正式契约（`src/factorlab/artifacts.py` 统一 I/O）：

```
results/<factor>/
├── signal.parquet   ← 未来 Strategy Runtime 唯一允许消费的正式 signal artifact
├── labels.parquet   ← FactorEvaluator 使用的未来标签 artifact（evaluation-only）
├── panel.parquet    ← legacy compatibility view（CLI/eval/Web 兼容，非正式输出）
└── summary.json     ← manifest（最后写入 = core artifacts 完成标记）
```

主从关系：`SignalArtifact → signal.parquet`；`LabelArtifact → labels.parquet`；
`SignalArtifact + LabelArtifact + 兼容字段 → panel.parquet`（signal 绝不从 panel 派生）。

- **版本**：`ARTIFACT_FORMAT_VERSION = 1`（结果目录 layout）；Signal/Labels/Panel
  `schema_version = 1`（单 artifact 契约）——整数可比较
- **文件名常量**：SIGNAL_FILE/LABELS_FILE/LEGACY_PANEL_FILE/SUMMARY_FILE（单一来源）
- **signal manifest** 含 SignalMeta（timing 以 Enum.value JSON 化：information_cutoff
  = close / available_at = after_close / default_earliest_execution = next_open——
  来自 SignalArtifact.meta.timing，非硬编码）；labels manifest 的 horizons 来自
  DEFAULT_FORWARD_HORIZONS；panel manifest 标记 `role: legacy_compatibility_view`
- **loaders**：`load_signal_artifact(result_dir)` / `load_label_artifact(result_dir)`——
  验证 format/schema version、manifest 文件名 == 平台固定名、M6-01 validator 复验
  磁盘内容。**绝不 fallback 到 panel.parquet**；旧结果目录（无 versioned manifest）
  明确报错（legacy result directory does not contain versioned Signal/Label artifacts）
- 单文件 atomic（temp + os.replace）；目录级事务不实现（见风险）

## 4.6 Semantic Guards（M6-06）

M6 边界 fail-fast invariants（不再新增计算能力）：

- **SignalArtifact**：future data forbidden（forward_*/future_*/target/label）——保持；
  合法扩展列（raw_signal/coverage/quality_flag）允许
- **LabelArtifact v1 contract**：只允许 `date / code / forward_return_<N>d`——
  signal/close/open/future_price/__factorlab_*/任意普通列 → ValueError；
  任意 horizon 仍合法（domain 不固定——schema v1 的 [5,20] 在 artifacts loader 层）
- **core persistence 拒绝内部列**：signal/labels/panel 含 `__factorlab_*` →
  write_factor_artifacts 写文件前 fail fast（零文件写入——暴露 runtime 泄漏）
- **manifest integrity**：loader 验证 manifest rows/columns（含顺序）/horizons 与
  磁盘 parquet 实际一致；meta structural validation（缺字段/非法 Enum → 清晰
  ValueError 非裸 KeyError）；manifest 类型（rows 非负 int、columns list[str]、
  horizons positive strictly-increasing）
- **Signal/Label key 对齐**：`validate_signal_label_alignment()`（行数 + date/code
  键 + 顺序——Polars-native equals）——persistence 写文件前执行；不自动 sort/inner join
- **bundle loader**：`load_factor_artifacts(result_dir) -> FactorArtifactBundle`
  （signal + labels + alignment）——integrity/evaluation API，**不是 strategy-safe**
  （含未来标签）；Strategy consumer 只用 `load_signal_artifact()`（只加载 signal，
  不加载 labels）；bundle 不加载 panel
- **`load_signal_artifact()` 不加载 labels**（性能/职责隔离）

注意：M6-06 验证 manifest/parquet **semantic consistency**，不提供 cryptographic
integrity 或 immutable run identity（hash/data snapshot 属后续 reproducibility
里程碑——同改 parquet+manifest 的攻击无法检测，这是正常边界）。

## 4.7 Production Data PIT（M6-07）

**M6-07A 审计**：MARKET_DATA_COVERAGE_GATE=READY（2015-01-05→2026-08-14，daily/adj_factor 内部无缺日）；SAFE_EXCLUDE_ST_START=20160809（manifest completed 6450 天无 gap）；delist_date CASE C（final/staging 均缺失——TARGETED STOCK_BASIC REFRESH REQUIRED）；stock_st raw 10000 组重复（M6-07B 修复）。

**Gate 状态（M6-07B1 修正——行情覆盖完整 ≠ 完整 PIT universe 可运行）**：
- `MARKET_DATA_COVERAGE_GATE` = **READY**（2015-01-05→2026-08-14——纯行情覆盖）
- `FULL_HISTORY_PIT_GATE` = **BLOCKED_BY_DELIST_DATE**——缺 delist_date 时退市股
  `is_listed` 仍为 true → align_to_listing 保留 stale 行 → fill_suspension_values
  前值填充 → **stale price 派生的 signal 仍 active**——PIT universe 语义缺失，
  正式 full-A-share Gate 必须等待 delist_date 迁移
- `ST_AWARE_GATE` = **NOT_READY**（code-level duplicate-ST repair complete；
  production smoke pending stock_basic migration / token availability）

**M6-07B PIT 数据修复**：resolve_universe_frame 的 ST join 改为唯一 (trade_date,
ts_code) projection（raw stock_st 重复行不膨胀 UniverseFrame——is_st 由存在性决定，
不物理删 raw payload）；stock_st ingestion 用 dedup=True（retry 幂等，其他日频表
dedup=False 不变）；stock_basic fetch 显式字段（STOCK_BASIC_FIELDS 含
delist_date/list_status）+ fetch_stock_basic_all（L/D 合并、ts_code unique fail
fast、D 行缺 delist_date fail fast）+ migrate_stock_basic_pit_fields（定向迁移：
ALTER ADD COLUMN + upsert keys=ts_code，保留原字段）。真实迁移依赖
FACTORLAB_TEAJOIN_TOKEN——未设置时 M6-07B 数据部分 BLOCKED（代码与测试已就绪）。

**M6-07B2 source integrity**：validate_stock_basic_source（纯 validator，唯一正式
入口）——list_date 非空、endpoint status 分区（L endpoint 全 L / D endpoint 全 D）、
list_status 仅 L/D、日期真实日历有效（YYYYMMDD）、delist_date >= list_date、
ts_code 匹配 ^\d{6}\.(SH|SZ|BJ)$、symbol == ts_code 前六位、ts_code
unique——全部 fail fast 不自动修复。production stock_basic migration requires
validated L/D source: non-null valid list_date, D delist_date, correct status
partition, identifier/date temporal consistency.

**M6-07B1 migration hardening**：two-phase（Phase-1 schema 事务外幂等补
list_status/delist_date；Phase-2 同一 connection 事务：UPDATE 已有行 PIT fields
（不覆盖 name/industry 等）、INSERT source 新 code、不删旧 code、validation
（uniqueness/before-preservation/source-completeness/D delist full-match/
list_status full-match）、COMMIT/ROLLBACK——不调用 db.upsert 不开第二写连接）；
fetch_stock_basic_all 收紧：L/D 必须非空（D 空更可能代表权限/API/schema 问题）、
list_date/delist_date YYYYMMDD 校验、symbol 非空。

**M6-07B4 quarantine legacy aliases**：vendor `stock_basic` 实测含历史别名
`T600018.SH`/`TS0018.SH`（上港集箱退市残留；冻结库同存、daily 均无行情）。
canonical research identifier 谓词收口到 `factorlab.domain.codes`
（`is_canonical_stock_code` / `CANONICAL_TS_CODE_PATTERN`——Python 与 DuckDB
SQL 共用）；`partition_stock_basic_source` 显式分区 canonical/quarantined：
canonical 走完整 validator（不弱化，canonical D 缺 delist 仍 BLOCK）；
非 canonical **退市** alias（suffix 合法 + symbol==ts_code 去后缀）进
quarantined（D 允许 delist=null）；其余形态 fail fast。**禁止** alias→canonical
映射/静默丢弃/硬编码白名单。`fetch_stock_basic_source` 暴露 quarantine（审计
可见），`fetch_stock_basic_all` = canonical-only 兼容 API；rules-based
resolve_codes/resolve_candidate_codes 加 canonical predicate——legacy aliases
绝不进 candidate_codes/UniverseFrame.code。冻结库中 T600018.SH/TS0018.SH
行保留为 inert（不删除；universe 不可选）。

## 4.8 Numeric Determinism（M6-07C2G/I）

**两层契约**：

1. **STRUCTURAL_EXACT**（严格位级相等）：schema/dtype/rows/(date,code) keys/key
   order/null mask/NaN/±Inf mask/labels/timing/PIT/canonical/ST filtering——
   以及非 reduction signal path（`signal = close`、QFQ 复权、labels）。
2. **FLOAT_REDUCTION_EQUIVALENT**（算子/负载特定数值等价）：连续 reduction
   的有限值对满足 `ULP_DISTANCE <= 4` **且** `abs(a-b) <= 8·EPS_FLOAT64·max(1,|a|,|b|)`
   （AND Gate）。当前绑定 M6 参考 `ts_mean(close, 20)`（全量 11.4M+ 行验证
   max ULP=4、scaled violations=0）。**bitwise mismatch count 本身不是
   reduction failure**（诊断指标）。

**Float64 ULP primitive**（单一权威，`factorlab.numerics`）：sign-aware 单调
IEEE bit 映射（**压缩零**：+0.0/-0.0 映射到同一序值——ULP=0 是映射本身性质；
零邻域 ULP(-min_subnormal, ±0.0)=1 且 ULP(±0.0, +min_subnormal)=1）；相邻
可表示 float64 → 1。QA comparator
（`factorlab.qa.numeric_determinism`）与 stable rank 共用，禁止两套 ULP 定义。

**cs_rank v2（stable dense rank，M6-07C2I/J）**：canonical operator 为
`cs_rank` v0.2.0，实现 = 平台 stable dense rank（`factorlab.ops.stable_rank`
的 `cs_stable_rank`——registry 中 `get_op("cs_rank")` 即该实现，vendor
polars_ta 的 0.1.0 cs_rank 不再占用 canonical 名；legacy exact tie 通过
`cs_rank(..., tie_ulps=0)` 显式获得）。Float64
近 tie（数值间隔 <= 4 ULP）按**组 anchor** 规则归为一个 dense level：
- anchor = 组内第一个（排序序）值；后续值 vs anchor ULP <= 4 才加入当前组
  （**anti-chaining**：A、A+4、A+8 → [A,A+4]、[A+8]，非传递合并）
- `cs_rank(x, True, 0)` 显式 legacy exact-bit tie 语义（迁移选项）
- 非 Float 输入 exact tie（不 fuzzy）；null → null；+0.0/-0.0 同组
- pct=True：level / max(K-1, 1)（0..1）；pct=False：1..K（UInt32）
- 动机（C2H）：数学真实 tie 被 rolling 路径 1 ULP 假拆分 → dense unique +1 →
  denominator 变化 → 全截面 normalized rank 平移（2022-12-06 单日 4,859 行）
- **4 ULP 不是全平台通用容差**——它绑定 M6 numerical contract + cs_rank v2；
  其他 discontinuous 算子（cs_quantile/cs_qcut/group_rank 等）未自动获得该
  contract（后续 discontinuous-operator audit）。

**执行模式角色**：CHUNK = production execution mode（全历史）；FULL =
bounded reference/debug mode（受限窗口独立实现对照）。full-history FULL
不要求在当前 16 GiB reference machine（8 GiB 固定 pagefile，CommitLimit
≈23.87 GiB）完成。

**M6 已验证结果**：F1 全历史 120/60 结构 exact + ≤4 ULP；F2/F3 全历史
120/60 strict exact（stable rank 下 F2 亦 exact）；bounded F2/F3
FULL/120/60 strict exact；labels strict exact；F2_ST violations=0。

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
run → 周频评估 + 分层回测，回测期数 = 评估周数；`tests/test_e2e_free_form.py`：
free-form 端到端——A 股日频版 RunLength 思路因子 vol_run_energy（def 内窗口算子 +
params 替换 + run --set 变体，n_weeks > 50）），真实 results 目录 Web 冒烟
（`tests/test_e2e_web.py`：列表含因子名/详情含图表数据/旧因子降级/缺失 404），
以及 teajoin 集成测试（token 配置时真实拉取，`tests/test_e2e_data.py`）。

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
