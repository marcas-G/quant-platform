"""M8-06C：artifact persistence layer——BacktestResult ↔ 文件系统（parquet +
manifest.json）。

- 固定目录结构（§4 spec）：artifacts/（每 primitive 独立 parquet）+
  state/final_state.parquet + nav/nav_series.parquet + manifest.json
- save：只序列化已关闭 primitive 输出（不重算 NAV/accounting/fills——
  rebuild 只反序列化 + domain validator 检查）；deterministic（created_at
  可显式注入）
- load：fail fast（目录缺失 / manifest 缺失 / 未知 schema_version / 缺文件 /
  缺列 / dtype 不匹配——禁止 silent migration / 自动修复）
- 无 DB 写入、无 strategy/signal 集成；BacktestResult/primitive contract 零修改
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import polars as pl

from factorlab.domain.accounting import (ExecutionAccountingSummary,
                                         PortfolioValuation)
from factorlab.domain.backtest import (ArtifactManifest, BacktestResult,
                                       ExecutionArtifact, NavSeries)
from factorlab.domain.execution import (FillBatch, OpenFillAssessment,
                                        OrderBatch, PortfolioState,
                                        PortfolioStatePhase)
from factorlab.domain.timing import ExecutionTiming

SCHEMA_VERSION = "1"
RUNTIME_VERSION = "factorlab-m8-06c"
ARTIFACT_TYPE = "backtest_result"

# 每文件期望列契约（顺序即 schema；load 严格校验缺列/dtype）
_SCHEMAS: dict[str, dict[str, pl.DataType]] = {
    "artifacts/execution_artifact.parquet": {
        "event_index": pl.Int64, "decision_date": pl.Date,
        "execution_date": pl.Date, "pre_cash": pl.Float64,
        "post_cash": pl.Float64, "nav_market_value": pl.Float64,
        "nav_nav": pl.Float64,
        "disp_fillable": pl.Int64, "disp_blocked_suspension": pl.Int64,
        "disp_blocked_limit_up": pl.Int64, "disp_blocked_limit_down": pl.Int64},
    "artifacts/orders.parquet": {"event_index": pl.Int64, "code": pl.String,
                                 "side": pl.String, "quantity": pl.Int64},
    "artifacts/assessment.parquet": {"event_index": pl.Int64,
                                     "code": pl.String, "side": pl.String,
                                     "quantity": pl.Int64,
                                     "disposition": pl.String,
                                     "fillable_price": pl.Float64},
    "artifacts/fills.parquet": {"event_index": pl.Int64, "code": pl.String,
                                "side": pl.String, "order_quantity": pl.Int64,
                                "filled_quantity": pl.Int64,
                                "reference_price": pl.Float64,
                                "execution_price": pl.Float64,
                                "gross_notional": pl.Float64,
                                "commission": pl.Float64,
                                "stamp_tax": pl.Float64,
                                "transfer_fee": pl.Float64,
                                "total_fees": pl.Float64,
                                "effective_cash_delta": pl.Float64},
    "artifacts/accounting.parquet": {"event_index": pl.Int64,
                                     "cash_before": pl.Float64,
                                     "buy_gross_notional": pl.Float64,
                                     "sell_gross_notional": pl.Float64,
                                     "commission": pl.Float64,
                                     "stamp_tax": pl.Float64,
                                     "transfer_fee": pl.Float64,
                                     "total_fees": pl.Float64,
                                     "net_cash_delta": pl.Float64,
                                     "cash_after": pl.Float64},
    "artifacts/valuation.parquet": {"event_index": pl.Int64,
                                    "code": pl.String,
                                    "quantity": pl.Int64,
                                    "mark_price": pl.Float64,
                                    "market_value": pl.Float64},
    "artifacts/state.parquet": {"event_index": pl.Int64, "stage": pl.String,
                                "cash": pl.Float64},
    "artifacts/positions.parquet": {"event_index": pl.Int64,
                                    "stage": pl.String, "code": pl.String,
                                    "quantity": pl.Int64,
                                    "sellable_quantity": pl.Int64},
    "state/final_state.parquet": {"as_of_date": pl.Date, "phase": pl.String,
                                  "cash": pl.Float64, "code": pl.String,
                                  "quantity": pl.Int64,
                                  "sellable_quantity": pl.Int64},
    "nav/nav_series.parquet": {"execution_date": pl.Date, "cash": pl.Float64,
                               "market_value": pl.Float64, "nav": pl.Float64},
}

_EMPTY_STATE = (pl.Series([], dtype=pl.String),
                pl.Series([], dtype=pl.Int64),
                pl.Series([], dtype=pl.Int64))


def _cast(frame: pl.DataFrame, cols: dict) -> pl.DataFrame:
    return frame.with_columns([pl.col(c).cast(d) for c, d in cols.items()])


def _typed_empty(cols: dict) -> pl.DataFrame:
    return pl.DataFrame({c: pl.Series([], dtype=d) for c, d in cols.items()})


# ================================================================
# save
# ================================================================

def save_backtest_result(
    result: BacktestResult,
    output_dir: Path,
    *,
    created_at: str | None = None,
) -> ArtifactManifest:
    """把 BacktestResult 序列化到 output_dir（parquet + manifest）。

    目录由调用方显式提供；save 创建固定子结构并覆写文件。
    """
    if not isinstance(result, BacktestResult):
        raise TypeError(
            f"result 必须为 BacktestResult（收到 {type(result).__name__}）")
    if not isinstance(output_dir, Path):
        raise TypeError(
            f"output_dir 必须为 pathlib.Path（收到 {type(output_dir).__name__}）")
    created = created_at if created_at is not None else \
        datetime.datetime.now(datetime.timezone.utc).isoformat()
    out = Path(output_dir)
    (out / "artifacts").mkdir(parents=True, exist_ok=True)
    (out / "state").mkdir(parents=True, exist_ok=True)
    (out / "nav").mkdir(parents=True, exist_ok=True)

    ea_rows, od_rows, as_rows, fl_rows = [], [], [], []
    ac_rows, va_rows, st_rows, po_rows = [], [], [], []
    for i, a in enumerate(result.artifacts):
        ea_rows.append((i, a.decision_date, a.execution_date,
                        a.pre_state.cash, a.post_state.cash,
                        a.nav.market_value, a.nav.nav,
                        *a.disposition_counts))
        for code, side, qty in a.orders.orders.iter_rows():
            od_rows.append((i, code, side, qty))
        for code, side, qty, disp, price in a.assessment.frame.iter_rows():
            as_rows.append((i, code, side, qty, disp, price))
        for row in a.fills.frame.iter_rows():
            fl_rows.append((i,) + row)
        s = a.accounting
        ac_rows.append((i, s.cash_before, s.buy_gross_notional,
                        s.sell_gross_notional, s.commission, s.stamp_tax,
                        s.transfer_fee, s.total_fees, s.net_cash_delta,
                        s.cash_after))
        for code, qty, mark, mv in a.nav.frame.iter_rows():
            va_rows.append((i, code, qty, mark, mv))
        for stage, st in (("pre", a.pre_state), ("post", a.post_state)):
            st_rows.append((i, stage, st.cash))
            for code, qty, sell in st.positions.iter_rows():
                po_rows.append((i, stage, code, qty, sell))

    def _write(rel: str, rows: list, cols: dict) -> None:
        frame = pl.DataFrame(rows, schema=list(cols), orient="row")
        frame = _cast(frame, cols) if rows else _typed_empty(cols)
        frame.write_parquet(out / rel)

    _write("artifacts/execution_artifact.parquet", ea_rows,
           _SCHEMAS["artifacts/execution_artifact.parquet"])
    _write("artifacts/orders.parquet", od_rows, _SCHEMAS["artifacts/orders.parquet"])
    _write("artifacts/assessment.parquet", as_rows,
           _SCHEMAS["artifacts/assessment.parquet"])
    _write("artifacts/fills.parquet", fl_rows, _SCHEMAS["artifacts/fills.parquet"])
    _write("artifacts/accounting.parquet", ac_rows,
           _SCHEMAS["artifacts/accounting.parquet"])
    _write("artifacts/valuation.parquet", va_rows,
           _SCHEMAS["artifacts/valuation.parquet"])
    _write("artifacts/state.parquet", st_rows, _SCHEMAS["artifacts/state.parquet"])
    _write("artifacts/positions.parquet", po_rows,
           _SCHEMAS["artifacts/positions.parquet"])
    # final_state：header 行恒存在（positions 空时 code/quantity 为 null）
    f = result.final_state
    fs_rows = [(f.as_of_date, f.phase.value, f.cash, None, None, None)]
    for code, qty, sell in f.positions.iter_rows():
        fs_rows.append((f.as_of_date, f.phase.value, f.cash, code, qty, sell))
    fs_frame = pl.DataFrame(fs_rows,
                            schema=list(_SCHEMAS["state/final_state.parquet"]),
                            orient="row")
    fs_frame = fs_frame.with_columns(
        pl.col("as_of_date").cast(pl.Date), pl.col("phase").cast(pl.String),
        pl.col("cash").cast(pl.Float64), pl.col("code").cast(pl.String),
        pl.col("quantity").cast(pl.Int64),
        pl.col("sellable_quantity").cast(pl.Int64))
    fs_frame.write_parquet(out / "state/final_state.parquet")
    ns = result.nav_series.frame
    _write("nav/nav_series.parquet", list(ns.iter_rows()),
           _SCHEMAS["nav/nav_series.parquet"])

    manifest = ArtifactManifest(
        schema_version=SCHEMA_VERSION, artifact_type=ARTIFACT_TYPE,
        created_at=created, runtime_version=RUNTIME_VERSION,
        artifact_count=len(result.artifacts),
        execution_date_start=(result.artifacts[0].execution_date
                              if result.artifacts else None),
        execution_date_end=(result.artifacts[-1].execution_date
                            if result.artifacts else None),
        columns={rel: list(cols) for rel, cols in _SCHEMAS.items()})
    doc = {
        "schema_version": manifest.schema_version,
        "artifact_type": manifest.artifact_type,
        "created_at": manifest.created_at,
        "runtime_version": manifest.runtime_version,
        "artifact_count": manifest.artifact_count,
        "execution_date_start": (manifest.execution_date_start.isoformat()
                                 if manifest.execution_date_start else None),
        "execution_date_end": (manifest.execution_date_end.isoformat()
                               if manifest.execution_date_end else None),
        "columns": manifest.columns,
    }
    (out / "manifest.json").write_text(
        json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return manifest


# ================================================================
# load
# ================================================================

def load_backtest_result(artifact_dir: Path) -> BacktestResult:
    """从 artifact_dir 重建 BacktestResult（fail fast——无 silent migration）。"""
    if not isinstance(artifact_dir, Path):
        raise TypeError(
            f"artifact_dir 必须为 pathlib.Path（收到 {type(artifact_dir).__name__}）")
    d = Path(artifact_dir)
    if not d.exists():
        raise ValueError(f"artifact 目录不存在: {d}")
    mpath = d / "manifest.json"
    if not mpath.exists():
        raise ValueError(f"manifest 缺失: {mpath}")
    doc = json.loads(mpath.read_text(encoding="utf-8"))
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"不支持 schema_version {doc.get('schema_version')!r}"
            f"（当前仅 {SCHEMA_VERSION}——无 silent migration）")
    if doc.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError(f"artifact_type 不匹配: {doc.get('artifact_type')!r}")

    frames = {}
    for rel, cols in _SCHEMAS.items():
        p = d / rel
        if not p.exists():
            raise ValueError(f"artifact 文件缺失: {rel}")
        frame = pl.read_parquet(p)
        if list(frame.columns) != list(cols):
            raise ValueError(
                f"{rel} 缺列/列序不匹配：期望 {list(cols)}，收到 {list(frame.columns)}")
        for c, exp in cols.items():
            if frame.schema[c] != exp:
                raise ValueError(
                    f"{rel}.{c} dtype 不匹配：期望 {exp}，收到 {frame.schema[c]}")
        frames[rel] = frame

    n = doc.get("artifact_count", 0)
    ea = frames["artifacts/execution_artifact.parquet"]
    if ea.height != n:
        raise ValueError(
            f"manifest artifact_count={n} 与 execution_artifact rows={ea.height} 不一致")

    artifacts = []
    for i in range(n):
        def _rows(rel, ev=i):
            return frames[rel].filter(pl.col("event_index") == ev)

        er = _rows("artifacts/execution_artifact.parquet").row(0)
        decision, exec_date = er[1], er[2]
        st = _rows("artifacts/state.parquet")

        def _state(stage: str) -> PortfolioState:
            row = st.filter(pl.col("stage") == stage).row(0)
            phase = (PortfolioStatePhase.PRE_EXECUTION if stage == "pre"
                     else PortfolioStatePhase.POST_EXECUTION)
            pos = _rows("artifacts/positions.parquet").filter(
                pl.col("stage") == stage).select(
                ["code", "quantity", "sellable_quantity"])
            return PortfolioState(as_of_date=exec_date, phase=phase,
                                  cash=row[2], positions=pos)

        pre, post = _state("pre"), _state("post")
        od = _rows("artifacts/orders.parquet").select(
            ["code", "side", "quantity"])
        orders = OrderBatch(decision_date=decision, execution_date=exec_date,
                            execution_timing=ExecutionTiming.NEXT_OPEN,
                            orders=od)
        ad = _rows("artifacts/assessment.parquet").select(
            ["code", "side", "quantity", "disposition", "fillable_price"])
        assessment = OpenFillAssessment(decision_date=decision,
                                        execution_date=exec_date,
                                        execution_timing=ExecutionTiming.NEXT_OPEN,
                                        frame=ad)
        fl = _rows("artifacts/fills.parquet").drop("event_index")
        fills = FillBatch(decision_date=decision, execution_date=exec_date,
                          execution_timing=ExecutionTiming.NEXT_OPEN, frame=fl)
        ar = _rows("artifacts/accounting.parquet").row(0)
        accounting = ExecutionAccountingSummary(
            execution_date=exec_date, cash_before=ar[1],
            buy_gross_notional=ar[2], sell_gross_notional=ar[3],
            commission=ar[4], stamp_tax=ar[5], transfer_fee=ar[6],
            total_fees=ar[7], net_cash_delta=ar[8], cash_after=ar[9])
        va = _rows("artifacts/valuation.parquet").select(
            ["code", "quantity", "mark_price", "market_value"])
        nav = PortfolioValuation(as_of_date=exec_date,
                                 phase=PortfolioStatePhase.POST_EXECUTION,
                                 cash=post.cash, market_value=er[5],
                                 nav=er[6], frame=va)
        counts = tuple(int(er[k]) for k in (7, 8, 9, 10))
        artifacts.append(ExecutionArtifact(
            decision_date=decision, execution_date=exec_date, pre_state=pre,
            orders=orders, assessment=assessment, fills=fills,
            post_state=post, accounting=accounting, nav=nav,
            disposition_counts=counts))

    nav_frame = frames["nav/nav_series.parquet"]
    nav_series = NavSeries(frame=nav_frame)

    fs = frames["state/final_state.parquet"]
    hdr = fs.row(0)
    pos = fs.filter(pl.col("code").is_not_null()).select(
        ["code", "quantity", "sellable_quantity"])
    if pos.height == 0:
        pos = _typed_empty({"code": pl.String, "quantity": pl.Int64,
                            "sellable_quantity": pl.Int64})
    final = PortfolioState(as_of_date=hdr[0],
                           phase=PortfolioStatePhase(hdr[1]), cash=hdr[2],
                           positions=pos)
    return BacktestResult(artifacts=tuple(artifacts), nav_series=nav_series,
                          final_state=final)
