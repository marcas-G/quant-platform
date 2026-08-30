# M6-07B4：Legacy Vendor Aliases 隔离设计（Quarantine）

日期：2026-08-30

## 1. 背景与动机

M6-07B-PROD 生产 fetch 实测（2026-08-30）：TeaJoin `stock_basic` L=5551 / D=340 行，
其中 2 行非 canonical 历史残留别名：

| ts_code | symbol | status | list_date | delist_date |
|---|---|---|---|---|
| `T600018.SH` | T600018 | D | 20000719 | 20061020 |
| `TS0018.SH` | TS0018 | D | 20000719 | null |

两行均为"上港集箱(退)"（600018 前身）vendor 残留；冻结平台库 stock_basic
（5883 行）也含这两行；`daily` 中两行均无行情（`600018.SH` 有 6187 天）。
M6-07B2 validator 按 `^\d{6}\.(SH|SZ|BJ)$` 正确 fail fast → PROD migration BLOCKED。

**问题**：规则（rules-based）universe 目前只按 `substr(ts_code, -2)` 后缀匹配
SSE/SZSE——`T600018.SH` 后缀是 `.SH`，会作为 symbol `T600018` 进入候选集与
UniverseFrame，即使无行情也污染 universe 语义（stale-membership）。

## 2. 方案：canonical 域 + 显式 quarantine

### 2.1 单一权威 canonical 谓词（`factorlab.domain.codes`）

```
canonical v1:  ts_code 匹配 ^\d{6}\.(SH|SZ|BJ)$  且  symbol == ts_code 前六位
```

- `is_canonical_stock_code(ts_code) -> bool`（ts_code 形态；None/非 str → False）
- `CANONICAL_TS_CODE_PATTERN` 常量：Python `re` 与 DuckDB `regexp_matches()`
  共用同一 pattern——**禁止**在 rebuild/universe 独立重写正则。
- `is_canonical_stock_row(ts_code, symbol) -> bool`（完整行契约，validator 语义化）

### 2.2 Source partition（`factorlab.data.rebuild`）

```
vendor stock_basic
   ├── canonical（^\d{6}\.(SH|SZ|BJ)$）→ validate_stock_basic_source（完整 fail fast 契约不变）
   └── quarantined（legacy alias candidate）→ 保留自身标识，仅供审计/report
```

quarantine 候选四条件（**全部** true）：

1. `list_status == D`（§5：非 canonical 且 L → fail fast——活跃非标准标识可能
   代表平台不认识的证券类别，不得静默隔离）
2. `ts_code` 非 null、`symbol` 非 null
3. `ts_code` 以 `.SH/.SZ/.BJ` 结尾（unsupported suffix → fail fast）
4. `symbol == ts_code 去后缀`（base mismatch → fail fast）

quarantined D 允许 `delist_date = null`（§6——这正是 TS0018.SH 必须放行的原因）；
**canonical D + delist=null 继续 BLOCK**（不弱化 PIT 契约）。

**禁止**（§7/17）：alias→canonical 映射（T600018.SH→600018.SH）、基于同名/
同日期的合并、静默丢弃、硬编码别名白名单（规则来自标识类别与 source 语义）。

### 2.3 Universe rules 过滤

`_codes_from_rules()` 与 `resolve_candidate_codes()` rules 模式 SQL 增加
`regexp_matches(ts_code, '<CANONICAL_TS_CODE_PATTERN>')`——legacy aliases 即使
后缀匹配 `.SH` 也绝不进入 candidate_codes / UniverseFrame.code（§13 invariant）。
explicit codes 模式不动（§12：synthetic/unit-test 语义保留）。

### 2.4 fetch API（§8）

- `fetch_stock_basic_source(client) -> StockBasicSourcePartition`：quarantine
  随分区返回（audit 可见，不静默丢弃）
- `fetch_stock_basic_all(client) -> pl.DataFrame`：canonical-only 兼容 API
  （future rebuild 的 research stock_basic 只收 canonical 行——§9）

### 2.5 冻结库策略（§10/14-16）

- 不删除冻结库中 `T600018.SH`/`TS0018.SH` 行（inert legacy rows）
- PROD 阶段用 canonical 谓词定义 `canonical_final_codes`/`canonical_staging_codes`：
  legacy 行不参与 DB-only check / migration coverage / PIT reconciliation
- PROD 阶段必须对每个 quarantined alias 重算 `daily`/`adj_factor` row count==0，
  否则 BLOCKED（有真实行情不可安全排除，需进一步调查）

### 2.6 非目标

- 不建永久 quarantine DB 表（本任务 quarantine 只出现在 fetch/audit 输出与
  migration report）
- 不改 `migrate_stock_basic_pit_fields()` two-phase 架构（§23）
- Gate 状态不动（§24）：MARKET_DATA_COVERAGE_GATE=READY、
  FULL_HISTORY_PIT_GATE=BLOCKED_BY_DELIST_DATE、ST_AWARE_GATE=NOT_READY

## 3. 测试策略（TDD）

| 文件 | 覆盖 |
|---|---|
| tests/test_stock_basic_migration.py | partition A-G（canonical L/D、T/TS alias→quarantine、alias D+null delist 放行、非 canonical L fail、suffix fail、symbol mismatch fail）、canonical D 缺 delist 仍 fail、no-alias-merge、fetch quarantine 可见性 |
| tests/test_universe.py | rules resolve_codes/resolve_candidate_codes 排除 T600018/TS0018（含 SSE-only） |
| tests/test_pit_universe.py | UniverseFrame rules 路径无 alias 行（老 list_date + 无 delist_date 也进不来） |

## 4. 验证

- 四组测试套件 + 全量 `python -m pytest -q`
- 无网络调用、无真实 DB 修改
- commit `fix(data): quarantine legacy stock aliases from research universe`
  push origin/main（含 40 位 SHA 报告）
