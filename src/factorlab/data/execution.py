"""M8-02：canonical execution-market data layer。

与 M6 compute internal（load_daily 的 ts_code→symbol 转换）分离——本模块
**始终使用 canonical ts_code**（M8 已进入 canonical namespace）。只读取
raw 市场证据（daily.open/pre_close、stk_limit.up/down_limit、suspend_d
events），不做复权、不做 fill 判定、不生成订单。

M8-02B：suspend_d 读取**事件行**（ts_code/suspend_type/suspend_timing）——
时间 grammar 唯一 authority 是 factorlab.execution.suspension（不在 SQL
里重写 temporal semantics）。runtime 重新 enforce production source
contract（suspend_type ∈ {S,R}；R+non-null timing 未证明→fail；exact
duplicate collapse、dedup 后 >1 distinct event→fail——production max=1，
未知结构 fail fast 不发明 precedence）；缺失 suspend_type/suspend_timing
列 → ValueError（M8-02B0 数据契约 runtime enforcement，禁止退回
presence-only DISTINCT）。
"""

from __future__ import annotations

import datetime
from pathlib import Path

import duckdb
import polars as pl

from factorlab.domain.codes import is_canonical_stock_code

_SNAPSHOT_COLUMNS = ["code", "open", "pre_close", "up_limit", "down_limit",
                     "has_daily", "has_limit", "has_suspend_record",
                     "is_suspended_at_open"]


def _require_tables(con: duckdb.DuckDBPyConnection) -> None:
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    for t in ("daily", "stk_limit", "suspend_d", "trade_cal"):
        if t not in tables:
            raise ValueError(
                f"execution market loader 需要 {t} 表（平台库由 data rebuild "
                f"生成）——缺失即 fail，不静默降级 execution safety")


def _require_columns(con: duckdb.DuckDBPyConnection, table: str,
                     columns: list[str]) -> None:
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = '{table}'").fetchall()}
    missing = [c for c in columns if c not in cols]
    if missing:
        raise ValueError(
            f"{table} 缺少执行所需字段 {missing}——fail fast（不裸 binder error）")


def _check_codes(codes: list[str]) -> None:
    if not isinstance(codes, list):
        raise ValueError(f"codes 必须为 list[str]（收到 {type(codes).__name__}）")
    if any(not isinstance(c, str) for c in codes):
        raise ValueError("codes 元素必须为 str")
    if len(set(codes)) != len(codes):
        raise ValueError(f"codes 重复 {len(codes) - len(set(codes))} 个——不 dedup")
    bad = [c for c in codes if not is_canonical_stock_code(c)]
    if bad:
        raise ValueError(f"codes 必须全部 canonical ts_code（收到 {bad}）")


def _derive_suspend_evidence(
    events: list[tuple[str, str | None]],
) -> tuple[bool, bool]:
    """单个 code 的 raw suspend events → (has_suspend_record, is_suspended_at_open)。

    - suspend_type 只接受 'S'/'R'（不 strip/不 upper/不 normalize）
    - suspend_timing None = absent；non-null 必须 parse 成功（parser
      ValueError 向上穿透——不 catch → false、不降级 presence-only）
    - R + non-null timing = production source contract 未证明的组合 → fail
    - exact duplicate（suspend_type, suspend_timing）collapse；dedup 后
      >1 distinct event → fail（production max distinct=1——未知多事件结构
      fail fast，不发明 precedence）
    - S/NULL → (True, True)；R/NULL → (True, False)；S/timing →
      (True, timing_covers_open(...))
    """
    # 函数内 lazy import：避免 module 级循环（data.execution → execution.suspension
    # → execution.__init__ → market → data.execution 部分初始化）
    from factorlab.execution.suspension import (parse_suspend_timing,
                                                timing_covers_open)
    if not events:
        return False, False
    distinct = set(events)
    if len(distinct) > 1:
        raise ValueError(
            f"同一 execution date/code 存在 {len(distinct)} 个 distinct "
            f"suspend events {sorted(distinct)}——production source max=1；"
            f"未知多事件结构 fail fast（不按 row order/type 建立 precedence）")
    typ, timing = next(iter(distinct))
    if typ not in ("S", "R"):
        raise ValueError(
            f"suspend_type 必须为 'S'/'R'（收到 {typ!r}——不 strip/不 upper）")
    if timing is None:
        return True, typ == "S"
    if typ != "S":
        raise ValueError(
            f"R + non-null suspend_timing（{timing!r}）未被 production source "
            f"contract 证明（frozen 实测 R+timing=0）——fail fast，不解释为 "
            f"intraday resumption interval")
    intervals = parse_suspend_timing(timing)
    return True, timing_covers_open(intervals)


def load_market_open_frame(
    db_path: Path,
    *,
    execution_date: datetime.date,
    codes: list[str],
) -> pl.DataFrame:
    """加载 execution_date + canonical codes 的市场开盘证据（9 列原始 frame）。

    - skeleton 由 requested codes 驱动：输出 rows == len(codes)（无 daily/
      limit/suspend 的证券保留 has_*=False——禁止 inner join 丢证券）
    - SQL 全部精确 ts_code IN (...)（禁止 substr 六位启发式）
    - daily/stk_limit 的 (trade_date, ts_code) duplicate → fail
    - suspend_d 读取事件行（suspend_type/suspend_timing）→
      _derive_suspend_evidence（temporal authority =
      factorlab.execution.suspension；exact duplicate collapse、distinct
      多事件 fail、R+timing fail、parser ValueError 穿透）
    - coverage gates：daily/stk_limit 全市场在 execution_date 0 行 → fail
      （trade_cal 开市 ≠ 数据可用）；suspend_d 0 行合法（无停牌日）
    - 只读 raw daily.open/pre_close、stk_limit.up/down_limit（不复权）
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path 必须为 Path（收到 {type(db_path).__name__}）")
    if not isinstance(execution_date, datetime.date) \
            or isinstance(execution_date, datetime.datetime):
        raise ValueError(f"execution_date 必须为 datetime.date（收到 {execution_date!r}）")
    _check_codes(codes)
    if not codes:
        return pl.DataFrame(
            {"code": pl.Series([], dtype=pl.String),
             "open": pl.Series([], dtype=pl.Float64),
             "pre_close": pl.Series([], dtype=pl.Float64),
             "up_limit": pl.Series([], dtype=pl.Float64),
             "down_limit": pl.Series([], dtype=pl.Float64),
             "has_daily": pl.Series([], dtype=pl.Boolean),
             "has_limit": pl.Series([], dtype=pl.Boolean),
             "has_suspend_record": pl.Series([], dtype=pl.Boolean),
             "is_suspended_at_open": pl.Series([], dtype=pl.Boolean)})

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        _require_tables(con)
        _require_columns(con, "daily", ["trade_date", "ts_code", "open", "pre_close"])
        _require_columns(con, "stk_limit", ["trade_date", "ts_code", "up_limit", "down_limit"])
        _require_columns(con, "suspend_d",
                         ["trade_date", "ts_code", "suspend_type", "suspend_timing"])
        _require_columns(con, "trade_cal", ["cal_date", "is_open"])

        d = execution_date.strftime("%Y%m%d")
        # ---- coverage gates（calendar truth ≠ data availability）----
        global_daily = con.execute(
            "SELECT COUNT(*) FROM daily WHERE trade_date = ?", [d]).fetchone()[0]
        if global_daily == 0:
            raise ValueError(
                f"execution date {execution_date} outside available daily "
                f"market-data coverage（trade_cal 开市但 daily 全市场 0 行——"
                f"禁止构造全 has_daily=False 假装全市场停牌）")
        global_limit = con.execute(
            "SELECT COUNT(*) FROM stk_limit WHERE trade_date = ?", [d]).fetchone()[0]
        if global_limit == 0:
            raise ValueError(
                f"execution date {execution_date} stk_limit coverage 0 行"
                f"（limit evidence 无当天覆盖——fail）")

        # ---- daily（duplicate fail）----
        daily_rows = con.execute(
            "SELECT trade_date, ts_code, open, pre_close FROM daily "
            "WHERE trade_date = ? AND ts_code IN (SELECT unnest(?))",
            [d, codes]).fetchall()
        if len(daily_rows) != len({(r[0], r[1]) for r in daily_rows}):
            raise ValueError(
                f"daily 在 {execution_date} 存在 (trade_date, ts_code) 重复"
                f"——不取 first/last")
        daily_map = {r[1]: (r[2], r[3]) for r in daily_rows}

        # ---- stk_limit（duplicate fail）----
        limit_rows = con.execute(
            "SELECT trade_date, ts_code, up_limit, down_limit FROM stk_limit "
            "WHERE trade_date = ? AND ts_code IN (SELECT unnest(?))",
            [d, codes]).fetchall()
        if len(limit_rows) != len({(r[0], r[1]) for r in limit_rows}):
            raise ValueError(
                f"stk_limit 在 {execution_date} 存在 (trade_date, ts_code) 重复"
                f"——不取 first/last")
        limit_map = {r[1]: (r[2], r[3]) for r in limit_rows}

        # ---- suspend_d（事件行读取；temporal authority = suspension.py）----
        raw_events = con.execute(
            "SELECT ts_code, suspend_type, suspend_timing FROM suspend_d "
            "WHERE trade_date = ? AND ts_code IN (SELECT unnest(?))",
            [d, codes]).fetchall()
        suspend_map: dict[str, tuple[bool, bool]] = {}
        for code in sorted(codes):
            events = [(r[1], r[2]) for r in raw_events if r[0] == code]
            suspend_map[code] = _derive_suspend_evidence(events)

        rows = []
        for code in sorted(codes):
            o, pc = daily_map.get(code, (None, None))
            up, dn = limit_map.get(code, (None, None))
            has_record, open_suspended = suspend_map[code]
            rows.append((code, o, pc, up, dn,
                         code in daily_map, code in limit_map,
                         has_record, open_suspended))
        out = pl.DataFrame(rows, schema=_SNAPSHOT_COLUMNS, orient="row")
        # 全 null 数值列保 Float64（polars 行构造 Null dtype 陷阱）
        for col in ("open", "pre_close", "up_limit", "down_limit"):
            out = out.with_columns(pl.col(col).cast(pl.Float64))
        return out
    finally:
        con.close()
