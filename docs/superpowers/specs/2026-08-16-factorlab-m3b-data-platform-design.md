# FactorLab M3b 数据平台设计文档

日期：2026-08-16
状态：待评审
依赖主设计：`docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md`

## 1. 背景与目标

`quant-data` 的原始数据与因子混杂、难以维护，用户决定废弃。M3b 在 `quant-platform` 建立**干净的平台自有数据层**：

1. **teajoin 全量重建**（零继承 quant-data）：从 teajoin Tushare 兼容代理按交易日/报告期全量拉取，历史深度 2000-01-04 至今（约 6400 交易日）。
2. **复权能力层**：多复权视图（RAW/QFQ/HFQ/PIT_QFQ）+ AdjustmentService + AdjustmentAudit，支撑因子挖掘平台。
3. **字段稀疏度治理**：稀疏字段（null_ratio > 20% 或 stock_coverage < 80%）物理剔除，保证因子可挖性。
4. **验证**：拉取自检 + 完整性自检 + 抽样对拍；平台库验证通过、用户确认后清理 quant-data。
5. **增量更新**：`data refresh` 从 manifest 续拉，维持数据新鲜度。

平台存储原则：**存 API 原始数据（raw + adj_factor），视图层负责复权**，任何口径可随时重算。

## 2. 数据范围

| 表 | 用途 | 拉取方式 | 估算请求量 |
|----|------|---------|-----------|
| `trade_cal` | 交易日历（重建骨架） | 全量 1 次 | 1 |
| `stock_basic` | 股票静态信息（industry/list_date/exchange） | 全量 1 次（list_status 分页） | 2 |
| `daily` | OHLCV 日线（raw，不复权） | 按 trade_date × 全市场 | ~6400 |
| `daily_basic` | 每日指标（total_mv/circ_mv/pe/pb/turnover_rate/股本） | 按 trade_date | ~6400 |
| `adj_factor` | 复权因子 | 按 trade_date | ~6400 |
| `stock_st` | ST 状态 | 按 trade_date | ~6400 |
| `stk_limit` | 涨跌停价格（Raw Execution/审计支撑） | 按 trade_date | ~6400 |
| `suspend_d` | 停牌记录 | 按 trade_date | ~6400 |
| `moneyflow` | 个股资金流向 | 按 trade_date | ~6400 |
| `income` / `balancesheet` / `cashflow` | 财报三表 | 按 report_date × 全市场 | ~600 |
| `index_daily` | 指数日线（回测基准） | 按 index_code 全历史 | ~8 |
| `index_weight` | 指数成分（按历史期） | 按 index_code × 期 | ~800 |

默认指数集：`000300.SH`（沪深300）、`000905.SH`（中证500）、`000852.SH`（中证1000）、`000016.SH`（上证50）。

总估算 **~47,000 请求**，0.2s 间隔 + 重试 → **约 2.5-3 小时**。

### 2.1 字段稀疏度治理

**目标**：稀疏字段无法支撑截面因子挖掘（覆盖率不足 → 因子计算 bias）。

**流程**：拉取全字段 → rebuild 后评估每表每字段覆盖率 → 稀疏字段物理剔除（不写入最终平台库）→ manifest 记录剔除清单与原因。

**评估指标**（每字段）：
- `null_ratio`：非 null 行数 / 总行数
- `stock_coverage`：有数据的股票数 / 总股票数
- `first_date`：首个有数据日期

**阈值**（任一超限即剔除）：`null_ratio > 20%` 或 `stock_coverage < 80%`。
配置项 `sparse_null_ratio` / `sparse_coverage` 可调。

**注意**：剔除针对"该字段整体稀疏"；历史早期缺失（如新股上市前）不触发剔除（评估在全时间范围）。剔除清单落 `data/manifest.json`，后续 refresh 增量沿用。

## 3. 架构与模块

```
src/factorlab/data/
├── fetcher.py      # TeaJoinClient：限流/重试/分页/fields 裁剪
├── platform_db.py  # PlatformDB：duckdb schema、upsert、integrity_check
├── rebuild.py      # rebuild_all(db, client, resume=True)：编排 + manifest
├── refresh.py      # refresh(db, client)：增量续拉
├── adjust.py       # 复权能力层：PriceView/AdjustmentService/AdjustmentAudit
└── verify.py       # verify_all(db, ref_db=None)：自检 + 稀疏评估 + 抽样对拍
```

存储：
- `data/factorlab.duckdb`（gitignored）：最终平台库（含剔除后 schema）
- `data/rebuild_staging.duckdb`：重建暂存库（拉取全字段，评估后剔除）
- `data/manifest.json`：拉取进度 + 剔除清单 + 最后更新

CLI（M4 统一接入 `factorlab` CLI；M3b 先提供脚本入口或最小 typer 命令）：
```
factorlab data rebuild [--start YYYYMMDD] [--resume]
factorlab data refresh
factorlab data verify [--compare <ref.duckdb>] [--sparse-report]
```

### 3.1 TeaJoinClient（fetcher.py）

```python
class TeaJoinClient:
    def __init__(self, token: str, base_url: str = "https://teajoin.com",
                 interval: float = 0.2, max_retries: int = 3) -> None

    def fetch(self, api_name: str, params: dict, fields: list[str] | None = None) -> pl.DataFrame
    # 限流（全局 0.2s 间隔）、重试（指数退避 2/4/8s，上限 3 次）、
    # 分页（接口支持 limit/offset 时）、fields 裁剪
    # 返回 data.fields + data.items 转 polars DataFrame
```

- 认证：token 从 `config.settings.teajoin_token`（.env `FACTORLAB_TEAJOIN_TOKEN`）。
- 空数据（空 items）正常返回空 DataFrame，不视为错误。
- 重试仅针对网络错误/5xx/限流；4xx 业务错误立即抛出（带 api_name 与响应）。

### 3.2 PlatformDB（platform_db.py）

```python
class PlatformDB:
    def __init__(self, path: Path) -> None
    def create_schema(self, tables: dict[str, list[str]]) -> None   # 表 → 列清单
    def upsert(self, table: str, df: pl.DataFrame, keys: list[str]) -> None  # 按 keys 去重
    def integrity_check(self) -> dict[str, IntegrityReport]         # 缺日/重复/自洽
```

- 重建阶段使用 `rebuild_staging.duckdb`（全字段）；评估剔除后重建 `factorlab.duckdb` 最终 schema。
- 表 schema 记录 `source_api`（接口名）与拉取参数，支持可追溯。

### 3.3 rebuild.py 编排

```
rebuild_all(db, client, start="20000104", resume=True) -> RebuildReport
  1. 拉 trade_cal（SSE）→ 交易日列表（骨架）
  2. 拉 stock_basic（list_status=L/D 分页）
  3. 按交易日循环拉行情系 7 表（daily/daily_basic/adj_factor/stock_st/stk_limit/suspend_d/moneyflow）
     → 每日 7 次请求，实时 upsert + 实时自检（行数>0、列完整）
  4. 按报告期循环拉财报 3 表（income/balancesheet/cashflow）
  5. 按指数拉 index_daily（全历史）与 index_weight（按期）
  6. manifest 更新：completed/failed 日期列表
  7. 评估字段稀疏度 → 剔除清单 → 重建最终库 schema（物理剔除）
```

**断点续传**：manifest `{table: {completed: [dates], failed: [dates], last_updated}}`；
`--resume` 从 failed ∪ 未完成日期继续；failed 日期重试 3 次后记录并跳过（verify 阶段统一暴露）。

### 3.4 refresh.py 增量

```
refresh(db, client) -> RefreshReport
  从 manifest.last_updated 次日到最新交易日：
  按交易日拉 daily/daily_basic/adj_factor/stock_st/stk_limit/suspend_d/moneyflow；
  财报/指数成分按新报告期/新期增量。
```

### 3.5 复权能力层（adjust.py）

**PriceView**（视图函数，输入 raw 价格 + adj_factor，可选 asof 研究日）：

```python
PRICE_VIEWS = ("raw", "qfq", "hfq", "pit_qfq")

def view_prices(df: pl.DataFrame, view: str, asof: date | None = None) -> pl.DataFrame
# RAW:   原样
# QFQ:   raw × adj / adj[latest]            （最新因子基准，历史价与当前可比）
# HFQ:   raw × adj                          （连续价格，最早价不变）
# PIT_QFQ: raw × adj / adj[asof]            （研究日 T 的因子基准，防未来）
```

**AdjustmentService**：

```python
def total_return(close, adj) -> pl.Expr     # HFQ 收益：close[t]×adj[t] / (close[t-1]×adj[t-1]) - 1
                                            # = 含分红再投资的真实收益
# adj_factor 表（API 原始）；dividend 表（分红送配，corporate_action 原始来源）
```

**AdjustmentAudit**（安全审计，输入因子面板 + 价格 + adj）：

```python
def lookahead_check(factor_df, prices, adj, asof) -> AuditReport
    # PIT_QFQ 视角重算因子 vs 输入因子：差异行即潜在未来信息泄漏

def scale_invariance_check(factor_df, prices, adj) -> AuditReport
    # RAW vs QFQ 计算因子对比：scale-invariant 因子（收益率类）应无差异；
    # 差异大的因子依赖价格尺度（需声明口径）

def adjustment_sensitivity_check(factor_df, prices, adj, views=("raw","qfq","hfq")) -> AuditReport
    # 口径切换敏感性：各视图下因子值变化幅度报告
```

**配套语义**：
- `FactorSpec.adjustment: raw|qfq|hfq|pit_qfq`（因子复权口径声明，默认 `qfq`；M4 引擎消费）
- **Raw Execution**：涨跌停/Gap 场景强制 RAW（stk_limit 支撑：close 触及涨跌停时不可成交，回测/评估用 RAW 判定）
- **历史复权漂移检测**：`pit_qfq`（asof=历史研究日）vs 最新 `qfq` 的差异报告（审计输出）
- **PIT 股本**：daily_basic 的 total_share/float_share 天然带日期维度（无需单独处理）

## 4. 验证与自检

### 4.1 拉取中实时自检（rebuild 循环内）

- 每批次行数 > 0（空交易日属正常，记录不告警）
- 返回列完整（与预期 fields 一致）
- 日期在预期范围

### 4.2 完整性自检（integrity_check，rebuild 后）

| 规则 | 说明 |
|------|------|
| 日历缺日 | daily 与 trade_cal 全对齐（无缺日、无多日） |
| 重复检测 | (date, code) 唯一 |
| pct_chg 自洽 | close 变化 vs pct_chg 误差 ±0.01% |
| adj_factor | > 0 且时间上单调不降（除权日除外） |
| stk_limit 边界 | close 不超当日涨跌停价（±0.01% 容差） |
| 市值有效 | total_mv > 0 |

### 4.3 字段稀疏度评估（rebuild 后）

每表每字段计算 `null_ratio` / `stock_coverage` / `first_date`；超阈（20%/80%）进剔除清单，最终库物理排除。

### 4.4 抽样对拍（verify）

随机 30 只股票 × 2020/2023/2026 三段各 20 交易日，与参考库（quant-data）对比 close（容差 0.01%）；除权/停牌日豁免；差异逐条审查输出报告。参考库仅作参考（API 为准），差异不阻塞。

### 4.5 quant-data 清理流程

平台库验证通过 + 输出对比报告 → **用户显式确认**后删除。流程文档化，不自动化。

## 5. 错误处理

- teajoin 网络/5xx/限流：指数退避重试 3 次，仍失败记录 failed 日期，续传时重试
- 业务 4xx（参数/权限）：立即抛出，明确 api_name 与响应内容
- 空数据：正常返回空 DataFrame（该日无数据），不告警
- 拉取中断：manifest 保证断点续传，`--resume` 恢复
- 稀疏评估失败（表不存在等）：报错并跳过该表
- 对拍差异：报告不阻塞（API 为准）

## 6. 测试策略

- **单测**（mock HTTP）：
  - fetcher：限流间隔、重试退避、分页、fields 裁剪、空数据、4xx 抛出
  - platform_db：schema 创建、upsert 去重、integrity_check 各规则
  - adjust：构造已知 adj 序列验证 QFQ/HFQ/PIT_QFQ 数学、total_return、三个审计函数
  - verify：自检规则、稀疏评估阈值边界
- **集成**（`@pytest.mark.integration`，token 存在才跑）：
  - 真实 API 小量拉取（3 个交易日 × daily/daily_basic/adj_factor）
  - 小范围 rebuild 端到端（3 天 × 2 股票 + 1 报告期）
- **防回归**：M1/M2/M3a 全部测试保持通过

## 7. 明确不做（M3b 边界）

- corporate_action 从 dividend 精确派生（存 dividend 原始表，派生留后续）
- 指数成分的历史精确回溯（index_weight 按月已够）
- quant-data 清理自动化（人工确认）
- PIT 复权全历史重建（PIT_QFQ 按需计算）
- 因子挖掘/评估接入（M4）
- Web 可视化（M5）
- 复权能力层接入 factorlab run 链路（M4：FactorSpec.adjustment 消费）

## 8. 时间与资源

- 全量重建估算 2.5-3 小时（47,000 请求 × 0.2s + 重试）
- token 到期 2026-08-22：重建须在到期前完成或分批（manifest 续传支持跨会话）
- 平台库体积估算：daily（6400×5400×10 列 float）≈ 1.4GB + daily_basic ≈ 1.4GB + 财报 ≈ 1GB，总量约 4-5GB（16GB 机器可承受；查询 SQL-first + 列裁剪沿用 M3a 纪律）
