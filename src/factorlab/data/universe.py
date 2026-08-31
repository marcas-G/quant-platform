from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import yaml

from factorlab.config import settings
from factorlab.domain.codes import (CANONICAL_TS_CODE_PATTERN,
                                    is_canonical_stock_code,
                                    is_canonical_stock_row)
from factorlab.spec import FactorSpec

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

VALID_EXCHANGES = ("SSE", "SZSE")
_ALLOWED_RULES = {"exclude_st", "min_list_days", "exchanges"}
# 平台库 stock_basic 无 exchange 列：交易所从 ts_code 后缀推断（.SH→SSE、.SZ→SZSE、.BJ→BSE）
_EXCHANGE_BY_SUFFIX = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}


def normalize_code(code: str) -> str:
    """'000001.SZ' -> '000001'；纯数字直通；非法格式报错。"""
    parts = code.split(".")
    if len(parts) > 2:
        raise ValueError(f"非法股票代码: {code}（期望 6 位数字或 ts_code 格式）")
    base = parts[0].strip()
    if len(base) != 6 or not base.isdigit() or base != parts[0]:
        raise ValueError(f"非法股票代码: {code}（期望 6 位数字或 ts_code 格式）")
    return base


def resolve_canonical_code_map(
    db: duckdb.DuckDBPyConnection,
    symbols: list[str],
) -> pl.DataFrame:
    """symbol → canonical ts_code 映射（M7-05 artifact handoff reference data）。

    - **唯一数据来源**：stock_basic.symbol ↔ stock_basic.ts_code（禁止
      prefix/exchange 启发式推断——canonical identity 是 reference data）
    - 输入：list[str] 非空且 unique（duplicate → ValueError，不 dedup）
    - 完整性：N 输入 → N 映射（缺失 symbol → fail fast，不 drop）
    - 唯一性：每 symbol 恰一行（reference 重复 → fail，不 first/last）
    - 输出每个 ts_code 经 is_canonical_stock_code + is_canonical_stock_row
      （symbol == ts_code[:6]）验证——legacy vendor alias（T600018.SH 等）
      / symbol mismatch → fail fast（不映射/不合并/不 drop）
    - 返回严格 schema：(symbol pl.String, code pl.String)
    """
    if not isinstance(symbols, list) or not symbols:
        raise ValueError(f"symbols 必须为非空 list[str]（收到 {type(symbols).__name__}）")
    if any(not isinstance(s, str) for s in symbols):
        raise ValueError("symbols 元素必须为 str")
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"symbols 重复 {len(symbols) - len(set(symbols))} 个——不 dedup")
    rows = db.execute(
        "SELECT symbol, ts_code FROM stock_basic "
        "WHERE symbol IN (SELECT unnest(?)) ORDER BY symbol",
        [symbols]).fetchall()
    found = {r[0] for r in rows}
    missing = [s for s in symbols if s not in found]
    if missing:
        raise ValueError(
            f"symbol→ts_code 映射缺失 {len(missing)} 个 symbol: {missing[:5]}"
            f"——fail fast（不 drop）")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r[0]] = counts.get(r[0], 0) + 1
    dup_ref = [s for s, c in counts.items() if c > 1]
    if dup_ref:
        raise ValueError(
            f"stock_basic 中 symbol 重复映射 {dup_ref}（同 symbol 多 ts_code）"
            f"——fail fast（不 first/last 选择）")
    # canonical 验证（ts_code 形态 + symbol↔ts_code row 一致性；alias 拒绝）
    out = pl.DataFrame(rows, schema=["symbol", "code"], orient="row")
    bad = out.filter(~pl.col("code").map_elements(
        is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False))
    if bad.height:
        raise ValueError(
            f"symbol→ts_code 含非 canonical ts_code: "
            f"{bad['code'].unique().to_list()}（legacy vendor alias 不映射/不合并）")
    # is_canonical_stock_row 逐行（symbol == ts_code[:6]）
    bad_row = out.filter(
        pl.col("symbol") != pl.col("code").str.slice(0, 6))
    if bad_row.height:
        raise ValueError(
            f"symbol↔ts_code row 不一致（symbol 必须 == ts_code 前六位）: "
            f"{bad_row.to_dicts()}")
    return out.select(["symbol", "code"])


def load_universe_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"universe 文件不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"universe 文件必须是映射: {path}")
    return data


def _resolve_source(name: str, universes_dir: Path) -> dict[str, Any]:
    path = Path(name)
    if path.is_file():
        return load_universe_file(path)
    if name.endswith(".yaml"):
        name = name[: -len(".yaml")]
    candidate = universes_dir / f"{name}.yaml"
    return load_universe_file(candidate)


def _codes_from_rules(rules: dict[str, Any], db: duckdb.DuckDBPyConnection, date_start: str | None) -> list[str]:
    unknown = set(rules) - _ALLOWED_RULES
    if unknown:
        raise ValueError(f"未知 universe 规则: {sorted(unknown)}（支持: {sorted(_ALLOWED_RULES)}）")
    # 平台库默认宇宙 = SSE+SZSE（无 exchange 列，按 ts_code 后缀推断；BSE 不进默认宇宙）。
    # M6-07B4：rules 候选必须额外满足 canonical research identifier
    # （^\d{6}\.(SH|SZ|BJ)$——legacy vendor aliases 如 T600018.SH 被排除）。
    sql = ("SELECT symbol FROM stock_basic"
           f" WHERE regexp_matches(ts_code, '{CANONICAL_TS_CODE_PATTERN}')"
           " AND substr(ts_code, -2) IN (SELECT unnest(?))")
    params: list[Any] = [[s for s, ex in _EXCHANGE_BY_SUFFIX.items() if ex in VALID_EXCHANGES]]
    if rules.get("exclude_st"):
        tables = {r[0] for r in db.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        if "stock_st" not in tables:
            raise ValueError("exclude_st 需要 stock_st 表（平台库由 data rebuild 生成）")
        # stock_st 无 is_st 列：最新 trade_date 快照中的 ts_code 集合即 ST 集合（type='ST' 语义）
        sql += (
            " AND symbol NOT IN (SELECT substr(ts_code, 1, 6) FROM stock_st"
            " WHERE trade_date = (SELECT max(trade_date) FROM stock_st))"
        )
    exchanges = rules.get("exchanges")
    if exchanges:
        bad = [e for e in exchanges if e not in VALID_EXCHANGES]
        if bad:
            raise ValueError(f"不支持的交易所: {bad}（v1 仅支持 {VALID_EXCHANGES}，不含 BSE）")
        suffixes = [s for s, ex in _EXCHANGE_BY_SUFFIX.items() if ex in exchanges]
        sql += " AND substr(ts_code, -2) IN (SELECT unnest(?))"
        params.append(suffixes)
    min_days = rules.get("min_list_days")
    if min_days is not None:
        min_days = int(min_days)
        if min_days < 0:
            raise ValueError(f"min_list_days 不能为负: {min_days}")
        if date_start is None:
            date_start = db.execute("SELECT min(trade_date) FROM daily").fetchone()[0]
            if date_start is None:
                raise ValueError("min_list_days 需要基准日期：daily 无数据且 spec 未设置 date.start")
        # 双格式（'YYYY-MM-DD'/'YYYYMMDD'）统一转 YYYYMMDD；平台库 list_date 为 'YYYYMMDD'（strptime 比较）
        sql += " AND strptime(list_date, '%Y%m%d') <= strptime(?, '%Y%m%d') - INTERVAL (?) DAY"
        params.extend([date_start.replace("-", ""), min_days])
    rows = db.execute(sql, params).fetchall()
    return sorted(r[0] for r in rows)


def _resolve_universe_data(spec: FactorSpec, override: str | None, settings) -> dict[str, Any]:
    """解析 universe 数据源：override > spec 内联（ref/codes/rules）。返回 {"codes": [...]} 或
    {"rules": {...}}。M6-02 起供 resolve_codes / resolve_candidate_codes / resolve_universe_frame 共用。"""
    if override is not None:
        try:
            normalize_code(override)
        except ValueError:
            data = _resolve_source(override, settings.universes_dir)
        else:
            data = {"codes": [override]}
    elif spec.universe.ref is not None:
        data = _resolve_source(spec.universe.ref, settings.universes_dir)
    elif spec.universe.codes is not None:
        data = {"codes": spec.universe.codes}
    elif spec.universe.rules is not None:
        data = {"rules": spec.universe.rules}
    else:
        raise ValueError("universe 解析失败：spec 缺少 ref/codes/rules")
    return data


def resolve_codes(
    spec: FactorSpec,
    db: duckdb.DuckDBPyConnection,
    override: str | None = None,
    settings=settings,
) -> list[str]:
    """universe 解析：override > spec 内联（ref/codes/rules）。返回纯数字代码列表（daily.code 格式）。
    全局默认层（config.default_universe）未接线，保留给 M4 CLI（--universe 默认值）。
    **legacy/static candidate semantics**：全期共用一组静态代码（含最新 ST 快照过滤与
    date.start 一次性 min_list_days）。历史 PIT membership 请用 resolve_universe_frame。"""
    data = _resolve_universe_data(spec, override, settings)

    if "codes" in data:
        # 先按 6 位数字/ts_code 标准化；非标准格式（如 1 字符 symbol 测试数据）原样保留，
        # 统一与平台库 stock_basic 的 symbol 或 ts_code 列匹配，返回 symbol（daily.code 格式）
        candidates: list[str] = []
        for c in data["codes"]:
            try:
                candidates.append(normalize_code(c))
            except ValueError:
                candidates.append(c)
        rows = db.execute(
            "SELECT symbol, ts_code FROM stock_basic"
            " WHERE symbol IN (SELECT unnest(?)) OR ts_code IN (SELECT unnest(?))",
            [candidates, candidates],
        ).fetchall()
        known_symbols = {r[0] for r in rows}
        ts_to_symbol = {r[1]: r[0] for r in rows if r[1] is not None}
        codes = sorted({ts_to_symbol.get(c, c) for c in candidates} & known_symbols)
    elif "rules" in data:
        codes = _codes_from_rules(data["rules"], db, spec.date.start)
    else:
        raise ValueError(f"universe 数据必须包含 codes 或 rules: {data}")

    if not codes:
        raise ValueError("universe 无有效股票，请检查 codes/rules/引用文件")
    return codes


# --------------------------------------------------------------------------
# M6-02: PIT Universe（两阶段模型：Candidate → PIT Eligibility）
# --------------------------------------------------------------------------

def resolve_candidate_codes(
    spec: FactorSpec,
    db: duckdb.DuckDBPyConnection,
    override: str | None = None,
    settings=settings,
) -> list[str]:
    """候选代码集：整个日期段内"可能参与研究"的证券（数据加载集）。

    复用 override/ref/codes/rules 解析体系；rules 模式**只应用 exchange 与
    证券标识合法性**——exclude_st / min_list_days 属动态 PIT 条件，禁止提前应用。
    语义：candidate = 可能出现的股票；membership[t] 由 resolve_universe_frame 决定。
    """
    data = _resolve_universe_data(spec, override, settings)
    if "codes" in data:
        candidates: list[str] = []
        for c in data["codes"]:
            try:
                candidates.append(normalize_code(c))
            except ValueError:
                candidates.append(c)
        rows = db.execute(
            "SELECT symbol, ts_code FROM stock_basic"
            " WHERE symbol IN (SELECT unnest(?)) OR ts_code IN (SELECT unnest(?))",
            [candidates, candidates],
        ).fetchall()
        known_symbols = {r[0] for r in rows}
        ts_to_symbol = {r[1]: r[0] for r in rows if r[1] is not None}
        codes = sorted({ts_to_symbol.get(c, c) for c in candidates} & known_symbols)
    elif "rules" in data:
        rules = data["rules"]
        unknown = set(rules) - _ALLOWED_RULES
        if unknown:
            raise ValueError(f"未知 universe 规则: {sorted(unknown)}（支持: {sorted(_ALLOWED_RULES)}）")
        exchanges = rules.get("exchanges")
        if exchanges:
            bad = [e for e in exchanges if e not in VALID_EXCHANGES]
            if bad:
                raise ValueError(f"不支持的交易所: {bad}（v1 仅支持 {VALID_EXCHANGES}，不含 BSE）")
            suffixes = [s for s, ex in _EXCHANGE_BY_SUFFIX.items() if ex in exchanges]
        else:
            suffixes = [s for s, ex in _EXCHANGE_BY_SUFFIX.items() if ex in VALID_EXCHANGES]
        # M6-07B4：rules 候选必须满足 canonical research identifier——legacy
        # vendor aliases（T600018.SH 等）即使后缀匹配 .SH 也绝不进入 candidate
        codes = sorted(
            r[0] for r in db.execute(
                "SELECT symbol FROM stock_basic"
                f" WHERE regexp_matches(ts_code, '{CANONICAL_TS_CODE_PATTERN}')"
                " AND substr(ts_code, -2) IN (SELECT unnest(?))",
                [suffixes],
            ).fetchall())
    else:
        raise ValueError(f"universe 数据必须包含 codes 或 rules: {data}")
    if not codes:
        raise ValueError("universe 无有效股票，请检查 codes/rules/引用文件")
    return codes


def _norm_dates(dates) -> list[str]:
    """日期集严格校验：只接受 datetime.date 或 ISO 'YYYY-MM-DD' 字符串。
    '2024-01-01 garbage' / '20240101' / 'abc' 等一律 ValueError（不截断接受）。"""
    out = []
    for d in dates:
        if isinstance(d, str):
            if not _ISO_DATE_RE.match(d):
                raise ValueError(f"非法日期格式: {d!r}（仅接受 ISO YYYY-MM-DD 字符串或 datetime.date）")
            out.append(d)
        elif isinstance(d, datetime.date):
            out.append(d.isoformat()[:10])
        else:
            raise ValueError(f"非法日期类型: {type(d).__name__}（仅接受 datetime.date 或 ISO 字符串）")
    return out


def resolve_universe_frame(
    spec: FactorSpec,
    db: duckdb.DuckDBPyConnection,
    dates: list,
    *,
    override: str | None = None,
    candidate_codes: list[str] | None = None,
    settings=settings,
) -> pl.DataFrame:
    """date×code PIT membership（接受显式日期集——chunk 友好，不要求全历史生成）。

    UniverseFrame schema: date/code/in_universe/is_listed/list_days/is_st/exchange。
    PIT 语义：is_listed = list_date<=t AND (delist_date IS NULL OR t<delist_date)；
    list_days = t − list_date（自然日）；is_st = 当日 stock_st 快照出现；
    exchange = ts_code 后缀（.SH→SSE/.SZ→SZSE/.BJ→BSE）。
    exclude_st=true 且 stock_st 缺表 → ValueError（fail fast）；false 且缺表 → is_st=null。
    """
    data = _resolve_universe_data(spec, override, settings)
    rules = data.get("rules", {}) if "rules" in data else {}
    codes = candidate_codes if candidate_codes is not None else resolve_candidate_codes(
        spec, db, override=override, settings=settings)
    if not codes:
        raise ValueError("候选代码集为空")
    if len(set(codes)) != len(codes):
        raise ValueError("candidate_codes 重复——fail fast，不静默去重")
    date_strs = _norm_dates(dates)
    if not date_strs:
        raise ValueError("dates 不能为空")
    if len(set(date_strs)) != len(date_strs):
        raise ValueError("dates 重复——fail fast，不静默去重")

    tables = {r[0] for r in db.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "stock_basic" not in tables:
        raise ValueError("需要 stock_basic 表（平台库由 data rebuild 生成）")
    has_st = "stock_st" in tables
    exclude_st = bool(rules.get("exclude_st"))
    if exclude_st and not has_st:
        raise ValueError("exclude_st 需要 stock_st 表（平台库由 data rebuild 生成）——不能默认所有股票非 ST")
    # ST coverage（v1 contract：min/max trade_date；内部 gap 的精确 provenance 留给 Data Coverage Registry）
    st_cov: tuple[str, str] | None = None
    if has_st:
        lo, hi = db.execute("SELECT min(trade_date), max(trade_date) FROM stock_st").fetchone()
        if lo is not None and hi is not None:
            st_cov = (str(lo), str(hi))
        if exclude_st and st_cov is None:
            raise ValueError("exclude_st=true 但 stock_st 为空表——ST coverage 未知，禁止当非 ST")
        if exclude_st:
            outside = [d for d in date_strs
                       if not (st_cov and st_cov[0] <= d.replace("-", "") <= st_cov[1])]
            if outside:
                raise ValueError(
                    f"exclude_st=true 但请求日期 {outside[0]} 在 ST coverage "
                    f"[{st_cov[0] if st_cov else '?'}, {st_cov[1] if st_cov else '?'}] 之外——"
                    f"ST 状态未知，禁止把 unknown 当非 ST")
    # delist_date 列探测（旧库可能无此列——退市信息不可用则视为 NULL）
    sb_cols = {r[0] for r in db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='stock_basic'").fetchall()}
    delist_col = "delist_date" if "delist_date" in sb_cols else "NULL"

    select_cols = f"d.date, c.code, b.ts_code, b.list_date, {delist_col} AS delist_date"
    sql = f"""
        WITH d AS (SELECT CAST(unnest(?) AS DATE) AS date),
             c AS (SELECT unnest(?) AS code)
        SELECT {select_cols}
        FROM d CROSS JOIN c
        LEFT JOIN stock_basic b ON b.symbol = c.code
    """
    params: list = [date_strs, codes]
    if has_st:
        # M6-07B：ST presence 由唯一 (trade_date, ts_code) projection 决定——
        # raw stock_st 可能含同 key 多行（同日多 type/name 状态），LEFT JOIN 直接
        # 引用会膨胀 UniverseFrame cardinality。不物理删 raw 行（保留 name/type
        # 等 payload），只投影 DISTINCT 键。
        sql = sql.replace("SELECT " + select_cols, "SELECT " + select_cols + ", s.trade_date IS NOT NULL AS is_st")
        sql += (" LEFT JOIN (SELECT DISTINCT trade_date, ts_code FROM stock_st) s"
                " ON s.ts_code = b.ts_code AND s.trade_date = strftime(d.date, '%Y%m%d')")
    rows = db.execute(sql, params).fetchall()
    # M6-07C1：构造边界必须显式 dtype——DuckDB row tuples 对稀疏字段（真实数据
    # delist_date 94% null）可能以任意长度的 null run 开头，Polars 默认 100 行
    # 推断窗口全 null → 推断 Null dtype → 后续非 null 值 append 失败
    # （构造后 cast 为时已晚——推断失败发生在 DataFrame 构建期）。
    schema: dict[str, pl.DataType] = {
        "date": pl.Date,
        "code": pl.String,
        "ts_code": pl.String,
        "list_date": pl.String,
        "delist_date": pl.String,
    }
    if has_st:
        schema["is_st"] = pl.Boolean
    uf = pl.DataFrame(rows, schema=schema, orient="row")
    # 幂等 cast 保留（构造边界已显式，不依赖这些 cast 修正 dtype）
    uf = uf.with_columns(pl.col("date").cast(pl.Date), pl.col("code").cast(pl.String))
    uf = uf.with_columns(pl.col("delist_date").cast(pl.String))
    if not has_st:
        uf = uf.with_columns(pl.lit(None, dtype=pl.Boolean).alias("is_st"))
    # 上市/退市 PIT
    uf = uf.with_columns(
        pl.when(pl.col("list_date").is_null()).then(None)
        .otherwise(pl.col("list_date").str.strptime(pl.Date, "%Y%m%d")).alias("list_d"),
        pl.when(pl.col("delist_date").is_null()).then(None)
        .otherwise(pl.col("delist_date").str.strptime(pl.Date, "%Y%m%d")).alias("delist_d"),
        pl.col("ts_code").str.slice(-2)
        .replace_strict({"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}, default="?").alias("exchange"))
    uf = uf.with_columns(
        ((pl.col("date") >= pl.col("list_d"))
         & pl.when(pl.col("delist_d").is_null()).then(pl.lit(True))
           .otherwise(pl.col("date") < pl.col("delist_d")))
        .fill_null(False).alias("is_listed"),
        # list_days：仅上市后（date >= list_date）有定义；pre-list 为 null
        pl.when(pl.col("date") >= pl.col("list_d"))
        .then((pl.col("date") - pl.col("list_d")).dt.total_days())
        .otherwise(None).alias("list_days"))
    # ST coverage 外 → is_st = null（unknown ≠ false）
    if has_st and st_cov is not None:
        uf = uf.with_columns(
            pl.when(pl.col("date").dt.strftime("%Y%m%d")
                    .is_between(pl.lit(st_cov[0]), pl.lit(st_cov[1])))
            .then(pl.col("is_st")).otherwise(None).alias("is_st"))
    # 最终输出 invariant：内部逻辑不得产生重复 (date, code)
    dup = uf.group_by(["date", "code"]).len().filter(pl.col("len") > 1)
    if dup.height:
        raise ValueError(f"resolve_universe_frame 内部逻辑产生重复 (date, code)——{dup.height} 组")
    # in_universe
    cond = pl.col("is_listed")
    if "codes" not in data:
        min_days = rules.get("min_list_days")
        if min_days is not None:
            min_days = int(min_days)
            if min_days < 0:
                raise ValueError(f"min_list_days 不能为负: {min_days}")
            cond = cond & (pl.col("list_days") >= min_days)
        exchanges = rules.get("exchanges") or list(VALID_EXCHANGES)
        bad = [e for e in exchanges if e not in VALID_EXCHANGES]
        if bad:
            raise ValueError(f"不支持的交易所: {bad}（v1 仅支持 {VALID_EXCHANGES}，不含 BSE）")
        cond = cond & pl.col("exchange").is_in(exchanges)
        if exclude_st:
            cond = cond & pl.col("is_st").fill_null(False).not_()
    uf = uf.with_columns(cond.fill_null(False).alias("in_universe"))
    return uf.select(["date", "code", "in_universe", "is_listed", "list_days",
                      "is_st", "exchange"]).sort(["date", "code"])


def _validate_align_inputs(raw: pl.DataFrame, universe: pl.DataFrame,
                           universe_cols: tuple[str, ...]) -> None:
    """align_* 共享 fail-fast：date/code 契约 + universe 必填列 + duplicate。"""
    for df, name, required in ((raw, "raw", ("date", "code")),
                               (universe, "universe", universe_cols)):
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"{name} 缺列: {missing}")
        if df.schema["date"] != pl.Date:
            raise ValueError(f"{name} date 列 dtype 必须为 pl.Date，实际 {df.schema['date']}")
        if df.schema["code"] != pl.String:
            raise ValueError(f"{name} code 列 dtype 必须为 pl.String，实际 {df.schema['code']}")
    if "in_universe" in universe_cols and universe.schema["in_universe"] != pl.Boolean:
        raise ValueError(f"universe in_universe 列 dtype 必须为 pl.Boolean，"
                         f"实际 {universe.schema['in_universe']}")
    if "is_listed" in universe_cols and universe.schema["is_listed"] != pl.Boolean:
        raise ValueError(f"universe is_listed 列 dtype 必须为 pl.Boolean，"
                         f"实际 {universe.schema['is_listed']}")
    for df, name in ((raw, "raw"), (universe, "universe")):
        dup = df.group_by(["date", "code"]).len().filter(pl.col("len") > 1)
        if dup.height:
            raise ValueError(f"{name} (date, code) duplicate rows——(date, code) must be unique，fail fast")


def align_to_universe(raw: pl.DataFrame, universe: pl.DataFrame) -> pl.DataFrame:
    """**Universe 驱动**的 active LEFT JOIN：raw 不能决定日期是否存在。

    - UniverseFrame filter(in_universe=true) LEFT JOIN raw（on date/code）
    - universe 内正常保留行情；universe 内无行情（含某日 raw 完全无行）→
      date/code 保留、行情 null；universe 外 → 排除
    - raw 至少 date/code；universe 至少 date/code/in_universe（Boolean）
    - code 严格 pl.String（证券代码有前导零——整数无法无损表示）
    - duplicate/dtype/缺列 fail fast——不静默去重/cast
    """
    _validate_align_inputs(raw, universe, ("date", "code", "in_universe"))
    uni = universe.filter(pl.col("in_universe")).select(["date", "code"])
    out = uni.join(raw, on=["date", "code"], how="left")
    return out.sort(["date", "code"])


def align_to_listing(raw: pl.DataFrame, universe: pl.DataFrame) -> pl.DataFrame:
    """**is_listed 驱动的 LEFT JOIN**（listed market skeleton，M6-03 Signal/Label runtime 用）。

    - listed + 正常行情 → 保留行情
    - listed + 无行情（停牌/数据缺失）→ date/code 保留、market fields null
    - pre-list / post-delist → 不存在（不产生上市前/退市后虚假行）
    - 纪律与 align_to_universe 一致（date/code String/duplicate/dtype fail fast）
    """
    _validate_align_inputs(raw, universe, ("date", "code", "is_listed"))
    uni = universe.filter(pl.col("is_listed")).select(["date", "code"])
    out = uni.join(raw, on=["date", "code"], how="left")
    return out.sort(["date", "code"])
