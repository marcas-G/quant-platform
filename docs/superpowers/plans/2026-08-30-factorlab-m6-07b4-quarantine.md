# M6-07B4：Legacy Vendor Aliases 隔离实施计划

日期：2026-08-30｜Base: `2c7e8df29bc271ad6feb5679f7e41e0ec89a5248`（main）

## 目标

修复 M6-07B-PROD 的 source validation 阻塞：vendor `stock_basic` 的 legacy
aliases（`T600018.SH`/`TS0018.SH`）显式 quarantine，canonical research
universe 与 rules 候选集永不包含它们。**不做** alias→canonical 映射、不删除
冻结库行、不改 migrate 架构、不动 Gate。

## 步骤

1. **domain/codes.py（新）**：`is_canonical_stock_code` / `is_canonical_stock_row` /
   `CANONICAL_TS_CODE_PATTERN`（Python/DuckDB 共用单一权威）
2. **rebuild.py**：
   - `StockBasicSourcePartition`（frozen dataclass：canonical/quarantined）
   - `_classify_identifiers()`（canonical mask + quarantine 四条件 + 细分 fail fast）
   - `partition_stock_basic_source(l_df, d_df)`（endpoint 分区/非空/缺列前置检查
     与 validator 同契约；canonical 走完整 validator；quarantine 允许 D+null delist）
   - `fetch_stock_basic_source()` / `fetch_stock_basic_all()`（canonical-only 兼容）
   - `validate_stock_basic_source` 的 ts_code 检查改用权威 helper
   - `_concat_partitions()`（Null dtype vs String 的 Polars concat 陷阱修复）
3. **universe.py**：`_codes_from_rules()` 与 `resolve_candidate_codes()` rules SQL
   加 `regexp_matches(ts_code, CANONICAL_TS_CODE_PATTERN)`
4. **测试（TDD，先红后绿）**：
   - test_stock_basic_migration.py：partition 12 例（A-G + strict D + no-merge + fetch）
   - test_universe.py：rules 排除 alias 3 例（默认/SSE+SZSE/SSE-only）
   - test_pit_universe.py：UniverseFrame 排除 1 例（§13 invariant）
5. **文档**：docs/interface.md（canonical 契约 + partition API + universe 过滤 +
   M6-07B4 历史条目）；本 spec/plan
6. **验证**：四组测试 + 全量 pytest
7. **提交**：`fix(data): quarantine legacy stock aliases from research universe`
   → push origin/main → 报告 40 位 SHA

## 验收（AC-01~23）

- 单一权威谓词存在（AC-01）；canonical 校验不弱化（AC-02/10）；quarantine 契约
  （AC-03/04）；fail fast 保持（AC-05/06/07）；无硬编码白名单（AC-08）；
  无映射（AC-09）；quarantine 审计可见（AC-11）；兼容 API canonical-only
  （AC-12）；future rebuild canonical-only（AC-13）；rules 双路径排除
  （AC-14/15）；SSE/SZSE 正常行为不变（AC-16）；UniverseFrame 无 alias
  （AC-17）；synthetic 测试无回归（AC-18）；migrate 不变（AC-19）；无网络
  （AC-20）；无真实 DB 改动（AC-21）；Gate 不变（AC-22）；全量 pytest 通过（AC-23）

## 后续（不在本任务）

- M6-07B-PROD 重跑：canonical 交集迁移（frozen_source = validated canonical
  ∩ canonical final/staging codes）+ 每 alias 的 daily/adj_factor==0 验证
  + delist/dup-ST/ST-aware smokes + Gate 升级（届时）
