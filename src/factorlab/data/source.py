from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from factorlab.config import settings

# 平台库 daily 列映射：引擎列名 → tushare 原始列名（SQL 别名阶段完成）
_COL_MAP = {"volume": "vol"}
# 平台库 daily 默认加载列（cols=None 时；turnover/total_mv/circ_mv 在 daily_basic，按需请求）
_PLATFORM_COLS = ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "volume", "amount")
# cols 请求的平台语义列 → daily_basic 来源列（left join）
_DAILY_BASIC_MAP = {
    "turnover": "turnover_rate", "total_mv": "total_mv", "circ_mv": "circ_mv",
    "pe_ttm": "pe_ttm", "pb": "pb", "dv_ratio": "dv_ratio",
}
_KNOWN_COLS = {"date", "code", "adj_factor", *_PLATFORM_COLS, *_DAILY_BASIC_MAP}


def load_daily(
    db_path: Path,
    codes: list[str],
    date_start: str | None = None,
    date_end: str | None = None,
    cols: list[str] | None = None,
    float32: bool = settings.use_float32,
) -> pl.LazyFrame:
    """平台库加载 daily：SQL-first 过滤 + 列映射（trade_date→date、ts_code→code、vol→volume）
    + 恒 join adj_factor + daily_basic 按需 left join → float32 cast → LazyFrame。

    列映射：trade_date（'YYYYMMDD'）→ date（pl.Date）、ts_code（'000001.SZ'）→ code（去后缀）；
    close 恒加载（forward/评估依赖）；adj_factor 恒 inner join（复权消费需要，
    daily 行缺 adj_factor 时被排除）；cols 含 turnover/total_mv/circ_mv 时 left join
    daily_basic（turnover_rate → turnover）。date/code/adj_factor 为请求列白名单成员，
    date/code 恒输出；adj_factor 仅在 cols 请求时输出。"""
    if not codes:
        raise ValueError("universe 为空，无法加载数据")
    requested = cols if cols is not None else list(_PLATFORM_COLS)
    unknown = [c for c in requested if c not in _KNOWN_COLS]
    if unknown:
        msg = f"未知列名: {unknown}（平台库可用列: {sorted(_KNOWN_COLS)}）"
        if "vol" in unknown:
            msg += "；平台库 vol 列已映射为 volume"
        raise ValueError(msg)

    # close 恒选（forward/评估依赖）；out_cols 同时决定输出列顺序
    daily_cols = list(dict.fromkeys([*[c for c in requested if c in _PLATFORM_COLS], "close"]))
    basic_cols = [c for c in requested if c in _DAILY_BASIC_MAP]
    want_adj = "adj_factor" in requested
    out_cols = list(dict.fromkeys([*[c for c in requested if c not in {"date", "code"}], "close"]))

    # SQL-first + 参数化：codes 用 substr 前缀匹配 ts_code（IN (SELECT unnest(?)) 防注入）
    where = ["substr(d.ts_code, 1, 6) IN (SELECT unnest(?))"]
    params: list[object] = [[c.split(".")[0] for c in codes]]
    for bound, op in ((date_start, ">="), (date_end, "<=")):
        if bound is not None:
            where.append(f"d.trade_date {op} ?")
            params.append(bound.replace("-", ""))

    select_items = ["d.trade_date", "d.ts_code"]
    if want_adj:
        select_items.append("a.adj_factor")
    select_items += [f"d.{_COL_MAP.get(c, c)} AS {c}" for c in daily_cols]
    select_items += [f"b.{_DAILY_BASIC_MAP[c]} AS {c}" for c in basic_cols]
    sql = "SELECT " + ", ".join(select_items) + " FROM daily d"
    sql += " JOIN adj_factor a ON d.trade_date = a.trade_date AND d.ts_code = a.ts_code"
    if basic_cols:
        sql += " LEFT JOIN daily_basic b ON d.trade_date = b.trade_date AND d.ts_code = b.ts_code"
    sql += f" WHERE {' AND '.join(where)} ORDER BY d.ts_code, d.trade_date"

    with duckdb.connect(str(db_path), read_only=True) as con:
        con.execute(f"SET memory_limit='{settings.default_max_memory}'")
        con.execute("SET threads=2")
        df = con.execute(sql, params).pl()

    df = df.with_columns(
        pl.col("trade_date").str.strptime(pl.Date, "%Y%m%d").alias("date"),
        pl.col("ts_code").str.split(".").list.first().alias("code"),
    ).drop(["trade_date", "ts_code"])
    df = df.select(["date", "code", *out_cols])
    if float32:
        df = df.with_columns([pl.col(c).cast(pl.Float32) for c in out_cols])
    return df.lazy()
