from __future__ import annotations

import datetime
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl

from factorlab.config import settings
from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.domain.codes import (CANONICAL_TS_CODE_PATTERN,
                                    is_canonical_stock_code)

DAILY_TABLES = ("daily", "daily_basic", "adj_factor", "stock_st", "stk_limit", "suspend_d", "moneyflow")
# 服务端对 suspend_d 的连续访问敏感（并发拉取批量失败、串行正常）：该表强制串行
SERIAL_TABLES = ("suspend_d",)
# M3b+ 按 ts_code 分批拉取（真实 API 强制 ts_code，全市场按报告期不可行）
FINANCIAL_TABLES = ("income", "balancesheet", "cashflow")
INDEX_CODES = ("000300.SH", "000905.SH", "000852.SH", "000016.SH")
DEFAULT_END = "20261231"


def load_manifest(path: Path) -> dict:
    """读取断点续传 manifest；文件不存在时返回空 dict。"""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, manifest: dict) -> None:
    """落盘 manifest（每批调用，供中断后断点续传）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class RebuildScope:
    start: str = "20000104"
    end: str | None = None


def _month_last_trading_days(dates: list[str]) -> list[str]:
    """每月最后一个交易日（dates 为升序交易日列表，按 YYYYMM 分组取末位）。"""
    result: list[str] = []
    for d in dates:
        if result and d[:6] == result[-1][:6]:
            result[-1] = d
        else:
            result.append(d)
    return result


def _table_rows(db: PlatformDB, table: str) -> int:
    if table not in db.list_tables():
        return 0
    return db.query(f'SELECT count(*) AS n FROM "{table}"')["n"][0]


def _fetch_one_date(client: TeaJoinClient, table: str, d: str) -> tuple[str, pl.DataFrame]:
    """单日期拉取（并发 worker 只做网络 IO；写入由主线程串行，duckdb 单写者）。"""
    df = client.fetch(table, {"trade_date": d})
    return d, df


# M6-07B：stock_basic 显式字段（必须含 delist_date/list_status——否则未来 rebuild
# 的 staging 会再次丢失 PIT 字段）。可按真实 TeaJoin 支持字段最小调整。
STOCK_BASIC_FIELDS = (
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "cnspell",
    "market",
    "list_status",
    "list_date",
    "delist_date",
    "act_name",
    "act_ent_type",
)

# M6-07B：stock_st 体量小且 retry 窗口可能重复 INSERT——唯一键 upsert（dedup=True）；
# 其他大日频表保持 dedup=False（纯 INSERT 性能）。ST presence 由唯一键投影决定，
# raw payload（name/type/type_name）保留多行不物理删除。
ST_DEDUP_TABLE = "stock_st"

# M6-07B1：targeted migration 准备/更新的 PIT 列（旧库缺 list_status 与 delist_date；
# 与 future full rebuild 的 explicit-fields schema 保持一致）
STOCK_BASIC_PIT_FIELDS: dict[str, str] = {
    "list_status": "VARCHAR",
    "delist_date": "VARCHAR",
}


def validate_stock_basic_source(l_df: pl.DataFrame, d_df: pl.DataFrame) -> pl.DataFrame:
    """纯 source validator（不依赖网络可完整测试；M6-07B2 唯一正式入口）。

    schema / endpoint status 分区 / identifier / date / temporal consistency /
    uniqueness 全部 fail fast，返回规范化（String cast + ts_code 排序）merged。
    **禁止自动修复**（不 drop/fill/去重/改 status/换日期）——生产数据宁可 BLOCKED。
    """

    def _cal(col_expr) -> pl.Expr:
        return col_expr.str.strptime(pl.Date, "%Y%m%d", strict=False).is_not_null()

    # ---- schema + 非空（先非空——空 DataFrame 无列，避免误报缺字段） ----
    for df, name in ((l_df, "L"), (d_df, "D")):
        if df.height == 0:
            raise ValueError(f"stock_basic {name} 返回空——source 无效"
                             f"（真实 A 股必有退市股，空返回更可能代表权限/API/schema/网络问题）")
        for col in ("ts_code", "symbol", "list_date", "list_status", "delist_date"):
            if col not in df.columns:
                raise ValueError(f"stock_basic {name} 缺少字段: {col}")
    # ---- endpoint status 分区（请求 L 必须全 L，请求 D 必须全 D） ----
    # **显式处理 null**（Polars 三值逻辑：null != "L" → null，filter 不保留——
    # 不能依赖 null-unsafe comparison；list_status 是强制字段）
    bad_l = l_df.filter(pl.col("list_status").is_null()
                        | (pl.col("list_status") != "L"))
    if bad_l.height:
        raise ValueError(f"stock_basic L endpoint 返回非 L row: {bad_l.height} 行"
                         f"（含 null/空串/其他值）")
    bad_d = d_df.filter(pl.col("list_status").is_null()
                        | (pl.col("list_status") != "D"))
    if bad_d.height:
        raise ValueError(f"stock_basic D endpoint 返回非 D row: {bad_d.height} 行"
                         f"（含 null/空串/其他值）")
    l_df = l_df.with_columns(pl.col("delist_date").cast(pl.String),
                             pl.col("list_date").cast(pl.String),
                             pl.col("symbol").cast(pl.String),
                             pl.col("list_status").cast(pl.String))
    d_df = d_df.with_columns(pl.col("delist_date").cast(pl.String),
                             pl.col("list_date").cast(pl.String),
                             pl.col("symbol").cast(pl.String),
                             pl.col("list_status").cast(pl.String))
    merged = pl.concat([l_df, d_df])
    # ---- status domain（防御：merged 只允许非空 L/D——显式 null guard） ----
    bad_status = merged.filter(pl.col("list_status").is_null()
                               | ~pl.col("list_status").is_in(["L", "D"]))
    if bad_status.height:
        raise ValueError(f"stock_basic list_status 仅允许非空 L/D，实际含 "
                         f"{bad_status['list_status'].unique().to_list()}"
                         f"（含 null——null 不能穿透）")
    # ---- identifier（M6-07B4：canonical 谓词唯一权威来源 domain.codes） ----
    bad_code = merged.filter(~pl.col("ts_code").map_elements(
        is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False))
    if bad_code.height:
        raise ValueError(f"stock_basic ts_code 必须匹配 {CANONICAL_TS_CODE_PATTERN}: "
                         f"{bad_code.height} 行")
    if merged["ts_code"].null_count() or merged["ts_code"].is_duplicated().any():
        raise ValueError("stock_basic 合并后 ts_code 缺失或重复——fail fast")
    if merged["symbol"].null_count():
        raise ValueError("stock_basic 存在空 symbol——fail fast")
    bad_sym = merged.filter(pl.col("symbol") != pl.col("ts_code").str.slice(0, 6))
    if bad_sym.height:
        raise ValueError(f"stock_basic symbol 必须匹配 ts_code 前六位: {bad_sym.height} 行")
    # ---- dates ----
    if merged["list_date"].is_null().any():
        raise ValueError(f"stock_basic 存在空 list_date: "
                         f"{merged['list_date'].null_count()} 行（PIT listing 强制字段）")
    bad_list = merged.filter(~_cal(pl.col("list_date")))
    if bad_list.height:
        raise ValueError(f"stock_basic list_date 非合法日历日期: {bad_list.height} 行")
    bad_delist = merged.filter(pl.col("delist_date").is_not_null()
                               & ~_cal(pl.col("delist_date")))
    if bad_delist.height:
        raise ValueError(f"stock_basic delist_date 非合法日历日期: {bad_delist.height} 行")
    d_missing = merged.filter((pl.col("list_status") == "D")
                              & pl.col("delist_date").is_null())
    if d_missing.height:
        raise ValueError(f"stock_basic 存在退市股票（list_status=D）但 delist_date 为空"
                         f"——{d_missing.height} 行，BLOCKED 不写数据库")
    # ---- temporal consistency（非空 delist_date >= list_date） ----
    bad_temporal = merged.filter(pl.col("delist_date").is_not_null()
                                 & (pl.col("delist_date") < pl.col("list_date")))
    if bad_temporal.height:
        raise ValueError(f"stock_basic delist_date < list_date（PIT interval 失效）: "
                         f"{bad_temporal.height} 行")
    return merged.sort("ts_code")


# ---------------------------------------------------------------------------
# M6-07B4：source partition（canonical research securities / quarantined aliases）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StockBasicSourcePartition:
    """stock_basic source 分区。

    canonical：research 可用标准证券——is_canonical_stock_code 通过且完整走
    validate_stock_basic_source（全部 fail fast 契约不弱化）。
    quarantined：非 canonical 的退市 vendor alias（保留自身标识，仅供审计/
    migration report；不参与 PIT universe、不进 future rebuild 的 research
    stock_basic）。**隔离 ≠ 合并/映射/静默丢弃。**
    """

    canonical: pl.DataFrame
    quarantined: pl.DataFrame


def _classify_identifiers(df: pl.DataFrame, name: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """按 canonical / quarantine 分类 df 行；其余形态 fail fast（细分错误消息）。

    quarantine 候选四条件（M6-07B4 §4，全部 true）：list_status==D、
    ts_code 非 null、symbol 非 null、ts_code 以 .SH/.SZ/.BJ 结尾、
    symbol == ts_code 去后缀。不要求 canonical 六位数字 symbol。
    fail fast 顺序（§5）：active L → null ts_code → null symbol →
    unsupported suffix → symbol/base mismatch。
    """
    can_mask = pl.col("ts_code").map_elements(
        is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False)
    canonical = df.filter(can_mask)
    rest = df.filter(~can_mask)
    if rest.is_empty():
        return canonical, rest
    rest = rest.with_columns(
        _q_null_ts=pl.col("ts_code").is_null(),
        _q_null_sym=pl.col("symbol").is_null(),
        _q_suffix=(pl.col("ts_code").str.ends_with(".SH")
                   | pl.col("ts_code").str.ends_with(".SZ")
                   | pl.col("ts_code").str.ends_with(".BJ")),
        _q_base=pl.col("symbol") == pl.col("ts_code").str.replace(r"\.(SH|SZ|BJ)$", ""),
    )
    active = rest.filter(pl.col("list_status") == "L")
    if active.height:
        raise ValueError(
            f"stock_basic {name} 存在非 canonical 且 list_status=L 的行: "
            f"{active['ts_code'].head(5).to_list()}——活跃非标准标识不可 quarantine"
            f"（可能代表平台不认识的证券类别）")
    if rest["_q_null_ts"].any():
        raise ValueError(f"stock_basic {name} 存在 null ts_code——fail fast")
    if rest["_q_null_sym"].any():
        raise ValueError(f"stock_basic {name} 存在 null symbol——fail fast")
    bad_suffix = rest.filter(~pl.col("_q_suffix"))
    if bad_suffix.height:
        raise ValueError(
            f"stock_basic {name} 存在非 canonical 且后缀不支持的 ts_code: "
            f"{bad_suffix['ts_code'].head(5).to_list()}——仅 .SH/.SZ/.BJ")
    bad_base = rest.filter(~pl.col("_q_base"))
    if bad_base.height:
        raise ValueError(
            f"stock_basic {name} 存在非 canonical 且 symbol/ts_code 不匹配的行: "
            f"{bad_base['ts_code'].head(5).to_list()}——symbol 必须等于 ts_code 去后缀")
    quarantined = rest.filter((pl.col("list_status") == "D")
                              & pl.col("_q_suffix") & pl.col("_q_base"))
    return canonical, quarantined.drop(["_q_null_ts", "_q_null_sym",
                                        "_q_suffix", "_q_base"])


def partition_stock_basic_source(l_df: pl.DataFrame, d_df: pl.DataFrame) -> StockBasicSourcePartition:
    """显式 source 分区（M6-07B4）：canonical 完整验证 + quarantine legacy aliases。

    - L/D 非空 + 分类必需列（ts_code/symbol/list_status）→ fail fast
    - endpoint status 分区（null 显式拒绝）——canonical 与 quarantine 一视同仁
    - canonical 行走 validate_stock_basic_source（endpoint/dates/temporal/
      uniqueness/symbol 全部保持——canonical D + delist=null 依然 BLOCK）
    - quarantined 允许 D + delist_date=null（§6：alias 无完整 PIT 契约）
    **禁止**：alias→canonical 映射、静默丢弃、硬编码别名清单（规则来自
    标识类别与 source 语义，非具体代码）。
    """
    for df, name in ((l_df, "L"), (d_df, "D")):
        if df.height == 0:
            raise ValueError(f"stock_basic {name} 返回空——source 无效"
                             f"（真实 A 股必有退市股，空返回更可能代表权限/API/schema/网络问题）")
        for col in ("ts_code", "symbol", "list_status"):
            if col not in df.columns:
                raise ValueError(f"stock_basic {name} 缺少字段: {col}")
    # endpoint status 分区（与 validate_stock_basic_source 相同契约；null 显式拒绝）
    bad_l = l_df.filter(pl.col("list_status").is_null()
                        | (pl.col("list_status") != "L"))
    if bad_l.height:
        raise ValueError(f"stock_basic L endpoint 返回非 L row: {bad_l.height} 行"
                         f"（含 null/空串/其他值）")
    bad_d = d_df.filter(pl.col("list_status").is_null()
                        | (pl.col("list_status") != "D"))
    if bad_d.height:
        raise ValueError(f"stock_basic D endpoint 返回非 D row: {bad_d.height} 行"
                         f"（含 null/空串/其他值）")
    l_can, l_q = _classify_identifiers(l_df, "L")
    d_can, d_q = _classify_identifiers(d_df, "D")
    quarantined = _concat_partitions(l_q, d_q)
    if l_can.height or d_can.height:
        canonical = validate_stock_basic_source(l_can, d_can)
    else:
        canonical = pl.DataFrame(schema=l_df.schema)
    return StockBasicSourcePartition(canonical=canonical, quarantined=quarantined)


def _concat_partitions(*parts: pl.DataFrame) -> pl.DataFrame:
    """concat 前统一 Null dtype 列 → String（全 null 分区推断 Null，与有值
    String 分区冲突——Polars 三值 dtype 陷阱）。"""
    non_empty = [p for p in parts if p.height]
    if not non_empty:
        return pl.DataFrame(schema=parts[0].schema)
    unified = []
    for p in non_empty:
        null_cols = [c for c, t in p.schema.items() if t == pl.Null]
        unified.append(p.with_columns(pl.col(c).cast(pl.String) for c in null_cols)
                       if null_cols else p)
    return pl.concat(unified)


def fetch_stock_basic_source(client: TeaJoinClient) -> StockBasicSourcePartition:
    """获取完整 stock_basic（list_status=L + D 分页合并）→ partition。

    显式字段（含 delist_date/list_status）；L/D 必须非空；唯一正式 source 入口
    （partition_stock_basic_source：canonical 完整验证 fail fast 不自动修复；
    legacy aliases quarantine 随分区返回——审计可见，绝不静默丢弃）。
    """
    l_df = client.fetch_paged("stock_basic", {"list_status": "L"},
                              fields=list(STOCK_BASIC_FIELDS))
    d_df = client.fetch_paged("stock_basic", {"list_status": "D"},
                              fields=list(STOCK_BASIC_FIELDS))
    return partition_stock_basic_source(l_df, d_df)


def fetch_stock_basic_all(client: TeaJoinClient) -> pl.DataFrame:
    """兼容 API：canonical-only（M6-07B4 起 legacy aliases 被 quarantine）。

    未来 rebuild 的 research stock_basic 只收 canonical 行；quarantine 行由
    fetch_stock_basic_source() 提供审计可见性（不静默丢弃）。
    """
    return fetch_stock_basic_source(client).canonical
def migrate_stock_basic_pit_fields(db: PlatformDB, stock_basic: pl.DataFrame) -> dict:
    """Two-phase targeted migration（M6-07B1）。

    Phase 1 — schema preparation（事务外、幂等）：补 list_status/delist_date 列
             （nullable；已存在则不修改）。**不在 Phase-2 DML 事务内**——duckdb
             同事务 ALTER+DML 冲突；如实记录：schema preparation 幂等但不是
             Phase-2 DML 事务的一部分。
    Phase 2 — **同一 connection** 事务：只更新 PIT fields（list_status/delist_date，
             不覆盖 name/industry 等已有值）、INSERT source 新 code（shared
             columns）、validation（uniqueness/before-preservation/source-
             completeness/D delist full-match/list_status full-match）、
             COMMIT/ROLLBACK。**不删除旧 code**（enrichment 非 destructive
             replace）；**不调用 db.upsert()**（禁止第二个写 connection）。
    """
    before = {"rows": db.query("SELECT COUNT(*) FROM stock_basic")[0, 0],
              "cols": db.describe("stock_basic")}
    with db.connect() as con:
        # Phase 1：schema（幂等）
        cols = {r[0] for r in con.execute("DESCRIBE stock_basic").fetchall()}
        for c, typ in STOCK_BASIC_PIT_FIELDS.items():
            if c not in cols:
                con.execute(f'ALTER TABLE stock_basic ADD COLUMN "{c}" {typ}')
        # Phase 2：同一 con 事务（全部 DML 显式 con——不开第二个写连接）
        try:
            con.execute("BEGIN")
            con.register("_incoming_stock_basic", stock_basic.to_arrow())
            con.execute("CREATE TEMP TABLE _before_codes AS SELECT ts_code FROM stock_basic")
            # UPDATE 已有行 PIT fields（不覆盖非 PIT 列）
            con.execute("""
                UPDATE stock_basic AS dst
                SET list_status = src.list_status,
                    delist_date = src.delist_date
                FROM _incoming_stock_basic AS src
                WHERE dst.ts_code = src.ts_code
            """)
            # INSERT source 新 code（目标表列 ∩ source 列；目标表存在但 source 缺的列 → NULL）
            table_cols = {r[0] for r in con.execute("DESCRIBE stock_basic").fetchall()}
            shared = [c for c in stock_basic.columns if c in table_cols]
            cols_sql = ", ".join(f'"{c}"' for c in shared)
            con.execute(f"""
                INSERT INTO stock_basic ({cols_sql})
                SELECT {cols_sql} FROM _incoming_stock_basic AS src
                WHERE NOT EXISTS (SELECT 1 FROM stock_basic dst WHERE dst.ts_code = src.ts_code)
            """)
            # ---- transaction 内 validation ----
            rows = con.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
            distinct = con.execute("SELECT COUNT(DISTINCT ts_code) FROM stock_basic").fetchone()[0]
            if rows != distinct:
                raise ValueError(f"迁移后 ts_code 不唯一: rows {rows} != distinct {distinct}")
            before_missing = con.execute("""
                SELECT COUNT(*) FROM _before_codes bc
                WHERE NOT EXISTS (SELECT 1 FROM stock_basic dst WHERE dst.ts_code = bc.ts_code)
            """).fetchone()[0]
            source_missing = con.execute("""
                SELECT COUNT(*) FROM _incoming_stock_basic src
                WHERE NOT EXISTS (SELECT 1 FROM stock_basic dst WHERE dst.ts_code = src.ts_code)
            """).fetchone()[0]
            d_delist_mismatch = con.execute("""
                SELECT COUNT(*) FROM _incoming_stock_basic src
                JOIN stock_basic dst ON dst.ts_code = src.ts_code
                WHERE src.list_status = 'D'
                  AND src.delist_date IS DISTINCT FROM dst.delist_date
            """).fetchone()[0]
            status_mismatch = con.execute("""
                SELECT COUNT(*) FROM _incoming_stock_basic src
                JOIN stock_basic dst ON dst.ts_code = src.ts_code
                WHERE src.list_status IS DISTINCT FROM dst.list_status
            """).fetchone()[0]
            if before_missing or source_missing or d_delist_mismatch or status_mismatch:
                raise ValueError(
                    f"migration validation failed: before_missing={before_missing} "
                    f"source_missing={source_missing} d_delist_mismatch={d_delist_mismatch} "
                    f"list_status_mismatch={status_mismatch}")
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            try:
                con.execute("DROP TABLE IF EXISTS _before_codes")
            except Exception:
                pass
    after = {"rows": db.query("SELECT COUNT(*) FROM stock_basic")[0][0],
             "cols": db.describe("stock_basic")}
    return {"before": before, "after": after}


def _rebuild_daily_table(
    db: PlatformDB,
    con: duckdb.DuckDBPyConnection,
    client: TeaJoinClient,
    table: str,
    dates: list[str],
    manifest: dict,
    manifest_path: Path,
    max_workers: int = 5,
) -> dict:
    """按交易日并发拉取单张行情表：worker 并行 fetch（网络瓶颈），主线程串行写入。

    并发 5 路（~250 req/min < teajoin 450/min 上限）；duckdb 单写者——worker 只
    fetch，主线程用复用连接串行 upsert（dedup=False 纯 INSERT）+ manifest 更新；
    每 20 个结果落盘一次（崩溃窗口 20 日重拉可接受，integrity 可查）。
    """
    completed = set(manifest.get(table, {}).get("completed", []))
    failed = set(manifest.get(table, {}).get("failed", []))
    fetched: list[str] = []
    total_rows = 0
    todo = [d for d in dates if d not in completed]
    errors: dict[str, str] = {}
    done_count = 0
    workers = 1 if table in SERIAL_TABLES else max_workers
    dedup = table == ST_DEDUP_TABLE   # M6-07B：stock_st 唯一键 upsert（retry 幂等）
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one_date, client, table, d): d for d in todo}
        for fut in as_completed(futures):
            d = futures[fut]
            try:
                _, df = fut.result()
                db.upsert_on(con, table, df, keys=["trade_date", "ts_code"], dedup=dedup)
                completed.add(d)
                failed.discard(d)  # 重试成功后从 failed 移除
                errors.pop(d, None)
                fetched.append(d)
                total_rows += df.height
            except Exception as exc:
                failed.add(d)
                errors[d] = str(exc)[:120]  # 诊断：失败原因
            done_count += 1
            if done_count % 20 == 0:
                manifest[table] = {"completed": sorted(completed), "failed": sorted(failed),
                                   "failed_errors": errors}
                save_manifest(manifest_path, manifest)
    manifest[table] = {"completed": sorted(completed), "failed": sorted(failed), "failed_errors": errors}
    save_manifest(manifest_path, manifest)
    return {"dates_fetched": sorted(fetched), "rows": total_rows, "failed": sorted(failed),
            "failed_errors": errors}


def rebuild_all(
    db: PlatformDB,
    client: TeaJoinClient,
    scope: RebuildScope = RebuildScope(),
    resume: bool = True,
    manifest_path: Path | None = None,
    max_workers: int = 5,
) -> dict:
    """全量重建编排：交易日历 → 静态表 → 行情 7 表按日 → 指数。

    断点续传：manifest 记录每表 completed/failed 并每批落盘；resume=True 跳过
    completed、重试 failed（成功后移除）；resume=False 忽略既有 manifest 全量重拉。
    返回 report：{"tables": {table: {...}}}，每表含 fetched/failed 与行数。
    """
    if not client.token:
        raise ValueError("teajoin token 未配置（FACTORLAB_TEAJOIN_TOKEN）")
    manifest_path = manifest_path or (settings.data_dir / "manifest.json")
    manifest = load_manifest(manifest_path)
    if not resume:
        manifest = {}

    # 1. 交易日历（重建骨架）
    cal = client.fetch("trade_cal", {"exchange": "SSE", "start_date": scope.start,
                                     "end_date": scope.end or DEFAULT_END})
    if cal.height == 0 or "is_open" not in cal.columns:
        raise ValueError("trade_cal 无交易日，检查 token/日期范围")
    cal = cal.filter(pl.col("is_open").cast(pl.Int32) == 1)  # fetcher 统一 String 构造，需 cast
    dates = sorted(cal["cal_date"].to_list())
    if not dates:
        raise ValueError("trade_cal 无交易日，检查 token/日期范围")
    # trade_cal 会返回未来公告日（实测最大 20261231）：截断到 today，避免为未来日白拉请求
    today = datetime.date.today().strftime("%Y%m%d")
    dates = [d for d in dates if d <= today]
    if not dates:
        raise ValueError("trade_cal 无交易日（全部为未来公告日），检查 token/日期范围")
    db.upsert("trade_cal", cal, keys=["exchange", "cal_date"])

    # 2. 静态表（上市 L + 退市 D，分页；M6-07B：显式字段含 delist_date/list_status）
    sb = fetch_stock_basic_all(client)
    if sb.height:
        db.upsert("stock_basic", sb, keys=["ts_code"])

    report: dict = {"tables": {}}

    # 3. 行情 7 表按日（worker 并发 fetch，主线程串行写入复用连接）
    with db.connect() as con:
        for table in DAILY_TABLES:
            report["tables"][table] = _rebuild_daily_table(
                db, con, client, table, dates, manifest, manifest_path, max_workers=max_workers
            )

    # 4. 指数：index_daily 全历史 + index_weight 每月最后一个交易日
    #    （M3b v1 不含财报三表：真实 API 强制 ts_code，全市场按报告期拉取不可行）
    index_failed: list[str] = []
    for code in INDEX_CODES:
        try:
            idx = client.fetch("index_daily", {"ts_code": code, "start_date": scope.start,
                                               "end_date": scope.end or DEFAULT_END})
            if idx.height:
                db.upsert("index_daily", idx, keys=["trade_date", "ts_code"])
        except Exception:
            index_failed.append(f"index_daily:{code}")
    report["tables"]["index_daily"] = {"rows": _table_rows(db, "index_daily"), "failed": index_failed}

    month_dates = _month_last_trading_days(dates)
    iw_completed = set(manifest.get("index_weight", {}).get("completed", []))
    iw_failed = set(manifest.get("index_weight", {}).get("failed", []))
    iw_fetched: list[str] = []
    for d in month_dates:
        if d in iw_completed:
            continue
        try:
            for code in INDEX_CODES:
                w = client.fetch("index_weight", {"index_code": code, "trade_date": d})
                if w.height:
                    db.upsert("index_weight", w, keys=["index_code", "trade_date"])
            iw_completed.add(d)
            iw_failed.discard(d)
            iw_fetched.append(d)
        except Exception:
            iw_failed.add(d)
        manifest["index_weight"] = {"completed": sorted(iw_completed), "failed": sorted(iw_failed)}
        save_manifest(manifest_path, manifest)
    report["tables"]["index_weight"] = {"month_dates": iw_fetched, "failed": sorted(iw_failed)}

    manifest["last_updated"] = dates[-1]
    save_manifest(manifest_path, manifest)
    return report


def assess_sparsity(db: PlatformDB) -> dict[str, dict[str, dict]]:
    """每表每字段稀疏度：null_ratio / stock_coverage / first_date。

    trade_cal 与键列（trade_date/cal_date/ts_code/exchange/index_code）不参与评估；
    stock_basic 等无日期列的表 first_date 为 None；空表（total=0）字段 null_ratio 记 1.0。
    """
    report: dict[str, dict[str, dict]] = {}
    for table in db.list_tables():
        if table in {"trade_cal"}:
            continue
        cols = [c for c in db.describe(table)
                if c not in {"trade_date", "cal_date", "ts_code", "exchange", "index_code"}]
        code_col = "ts_code" if "ts_code" in db.describe(table) else None
        date_col = "trade_date" if "trade_date" in db.describe(table) else "cal_date"
        total = db.query(f'SELECT count(*) AS n FROM "{table}"')["n"][0]
        table_report: dict[str, dict] = {}
        for col in cols:
            non_null = db.query(f'SELECT count(*) AS n FROM "{table}" WHERE "{col}" IS NOT NULL')["n"][0]
            null_ratio = 1.0 - (non_null / total) if total else 1.0
            stock_coverage = 1.0
            if code_col and total:
                with_stock = db.query(
                    f'SELECT count(DISTINCT "{code_col}") AS n FROM "{table}" WHERE "{col}" IS NOT NULL'
                )["n"][0]
                all_stock = db.query(f'SELECT count(DISTINCT "{code_col}") AS n FROM "{table}"')["n"][0]
                stock_coverage = with_stock / all_stock if all_stock else 1.0
            first_date = None
            if date_col in db.describe(table):
                first = db.query(
                    f'SELECT min("{date_col}") AS d FROM "{table}" WHERE "{col}" IS NOT NULL'
                )["d"][0]
                first_date = str(first) if first is not None else None
            table_report[col] = {
                "null_ratio": round(null_ratio, 4),
                "stock_coverage": round(stock_coverage, 4),
                "first_date": first_date,
            }
        report[table] = table_report
    return report


# 语义关键稀疏字段：天然大量为 null 但对 PIT 语义关键——无论 sparsity 多高都不得
# 被 build_final_db 物理删除（仅保护显式字段，不关闭整体 sparsity pruning）
PROTECTED_SPARSE_FIELDS: dict[str, set[str]] = {
    "stock_basic": {"delist_date"},
}


def build_final_db(
    staging: PlatformDB,
    final_path: Path,
    null_threshold: float = 0.2,
    coverage_threshold: float = 0.8,
) -> dict:
    """评估稀疏度 → 剔除超限字段 → 重建最终库（物理排除）。

    任一超限（null_ratio > null_threshold 或 stock_coverage < coverage_threshold）即剔除；
    PROTECTED_SPARSE_FIELDS 中的语义关键字段豁免（如 stock_basic.delist_date——
    天然大量 null 但对 PIT Universe 关键，staging 存在该字段时不得删除）；
    无保留列的表跳过建表；最终库已存在时整体替换（CREATE OR REPLACE，schema 收缩生效）。
    返回 {"excluded_fields": {table: [cols]}, "tables": [最终库表]}。
    """
    if not staging.path.exists():
        raise ValueError(f"暂存库不存在: {staging.path}")
    sparsity = assess_sparsity(staging)
    excluded: dict[str, list[str]] = {}
    for table, fields in sparsity.items():
        protected = PROTECTED_SPARSE_FIELDS.get(table, set())
        excluded[table] = [
            col for col, m in fields.items()
            if (m["null_ratio"] > null_threshold or m["stock_coverage"] < coverage_threshold)
            and col not in protected
        ]
    staging_path = str(staging.path).replace("\\", "/")  # Windows 反斜杠在 ATTACH 字符串中需转义
    with duckdb.connect(str(final_path)) as con:
        con.execute(f"ATTACH '{staging_path}' AS staging (READ_ONLY)")
        for table in staging.list_tables():
            keep = [c for c in staging.describe(table) if c not in excluded.get(table, [])]
            if not keep:
                continue
            cols_sql = ", ".join(f'"{c}"' for c in keep)
            con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT {cols_sql} FROM staging."{table}"')
        con.execute("DETACH staging")
    return {"excluded_fields": excluded, "tables": PlatformDB(final_path).list_tables()}
