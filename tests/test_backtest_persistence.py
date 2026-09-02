"""M8-06C：backtest artifact persistence layer——save/load BacktestResult
（parquet + manifest；round-trip stable；fail-fast error contract）。"""

import datetime
import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

from factorlab.domain import (BacktestResult, NavSeries, PortfolioState,
                              PortfolioStatePhase, TargetPortfolio,
                              TargetPortfolioMeta)
from factorlab.domain.timing import DEFAULT_EOD_SIGNAL_TIMING
from factorlab.execution import (ExecutionSpec, load_backtest_result,
                                 run_backtest, save_backtest_result)

D1 = datetime.date(2024, 1, 2)
D2 = datetime.date(2024, 1, 3)
D3 = datetime.date(2024, 1, 4)
D8 = datetime.date(2024, 1, 8)


def _db(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect(tmp_path / "b.duckdb")
    db.execute("CREATE TABLE trade_cal (cal_date VARCHAR, is_open INT)")
    for d, o in [(D1, 1), (D2, 1), (D3, 1), (datetime.date(2024, 1, 5), 1),
                 (D8, 1), (datetime.date(2024, 1, 9), 1)]:
        db.execute("INSERT INTO trade_cal VALUES (?,?)", (d.strftime("%Y%m%d"), o))
    db.execute("""CREATE TABLE stock_basic (ts_code VARCHAR, symbol VARCHAR,
        market VARCHAR)""")
    for c in ("000001.SZ", "600000.SH"):
        db.execute("INSERT INTO stock_basic VALUES (?,?,?)", (c, c[:6], "主板"))
    db.execute("CREATE TABLE daily (trade_date VARCHAR, ts_code VARCHAR, "
               "open DOUBLE, pre_close DOUBLE)")
    db.execute("CREATE TABLE stk_limit (trade_date VARCHAR, ts_code VARCHAR, "
               "up_limit DOUBLE, down_limit DOUBLE)")
    db.execute("CREATE TABLE suspend_d (trade_date VARCHAR, ts_code VARCHAR, "
               "suspend_type VARCHAR, suspend_timing VARCHAR)")
    for date, code, o in [(D2, "000001.SZ", 10.0), (D2, "600000.SH", 20.0),
                          (D3, "000001.SZ", 11.0), (D3, "600000.SH", 21.0)]:
        db.execute("INSERT INTO daily VALUES (?,?,?,?)",
                   (date.strftime("%Y%m%d"), code, o, o))
        db.execute("INSERT INTO stk_limit VALUES (?,?,?,?)",
                   (date.strftime("%Y%m%d"), code, round(o * 1.1, 4),
                    round(o * 0.9, 4)))
    db.close()
    return tmp_path / "b.duckdb"


def _target():
    rows = [(D1, "000001.SZ", 0.5), (D1, "600000.SH", 0.5),
            (D2, "000001.SZ", 1.0)]
    frame = pl.DataFrame(rows, schema=["decision_date", "code",
                                       "target_weight"], orient="row")
    frame = frame.with_columns(pl.col("decision_date").cast(pl.Date),
                               pl.col("code").cast(pl.String),
                               pl.col("target_weight").cast(pl.Float64))
    return TargetPortfolio(frame=frame, decision_dates=(D1, D2),
                           meta=TargetPortfolioMeta(
                               strategy_name="strat_x",
                               source_signal_name="alpha_x",
                               source_timing=DEFAULT_EOD_SIGNAL_TIMING,
                               gross_exposure=1.0))


def _run(tmp_path):
    return run_backtest(_target(),
                        ExecutionSpec.model_validate(
                            {"initial_cash": 1_000_000.0}), _db(tmp_path))


# ---------------- API / structure / manifest ----------------

def test_api_exists():
    assert callable(save_backtest_result) and callable(load_backtest_result)


def test_save_creates_fixed_structure(tmp_path):
    m = save_backtest_result(_run(tmp_path), tmp_path / "out")
    for rel in ("manifest.json", "artifacts/execution_artifact.parquet",
                "artifacts/orders.parquet", "artifacts/assessment.parquet",
                "artifacts/fills.parquet", "artifacts/accounting.parquet",
                "artifacts/valuation.parquet", "state/final_state.parquet",
                "nav/nav_series.parquet"):
        assert (tmp_path / "out" / rel).exists(), rel
    assert m.schema_version == "1" and m.artifact_count == 2


def test_manifest_content(tmp_path):
    m = save_backtest_result(_run(tmp_path), tmp_path / "out",
                             created_at="2026-09-02T00:00:00Z")
    doc = json.loads((tmp_path / "out" / "manifest.json").read_text(
        encoding="utf-8"))
    assert doc["schema_version"] == "1"
    assert doc["artifact_type"] == "backtest_result"
    assert doc["created_at"] == "2026-09-02T00:00:00Z"
    assert "runtime_version" in doc and "columns" in doc


def test_save_guards(tmp_path):
    with pytest.raises(TypeError, match="result"):
        save_backtest_result({"x": 1}, tmp_path / "o")
    with pytest.raises(TypeError, match="output_dir"):
        save_backtest_result(_run(tmp_path), "str-path")


# ---------------- round-trip ----------------

def test_normal_roundtrip(tmp_path):
    r = _run(tmp_path)
    save_backtest_result(r, tmp_path / "out")
    r2 = load_backtest_result(tmp_path / "out")
    assert len(r2.artifacts) == 2
    for a, b in zip(r.artifacts, r2.artifacts):
        assert a.decision_date == b.decision_date
        assert a.pre_state.cash == b.pre_state.cash
        assert a.pre_state.positions.equals(b.pre_state.positions)
        assert a.post_state.positions.equals(b.post_state.positions)
        assert a.orders.orders.equals(b.orders.orders)
        assert a.assessment.frame.equals(b.assessment.frame)
        assert a.fills.frame.equals(b.fills.frame)
        assert a.accounting == b.accounting
        assert a.nav.frame.equals(b.nav.frame) and a.nav.nav == b.nav.nav
        assert a.disposition_counts == b.disposition_counts
    assert r2.nav_series.frame.equals(r.nav_series.frame)
    assert r2.final_state.cash == r.final_state.cash
    assert r2.final_state.as_of_date == r.final_state.as_of_date
    assert r2.final_state.positions.equals(r.final_state.positions)


def test_empty_result_roundtrip(tmp_path):
    final = PortfolioState(as_of_date=D8,
                           phase=PortfolioStatePhase.PRE_EXECUTION,
                           cash=1_000_000.0,
                           positions=pl.DataFrame(
                               {"code": pl.Series([], dtype=pl.String),
                                "quantity": pl.Series([], dtype=pl.Int64),
                                "sellable_quantity": pl.Series([],
                                                               dtype=pl.Int64)}))
    r = BacktestResult(artifacts=(), nav_series=NavSeries(frame=pl.DataFrame(
        {"execution_date": pl.Series([], dtype=pl.Date),
         "cash": pl.Series([], dtype=pl.Float64),
         "market_value": pl.Series([], dtype=pl.Float64),
         "nav": pl.Series([], dtype=pl.Float64)})), final_state=final)
    save_backtest_result(r, tmp_path / "out")
    r2 = load_backtest_result(tmp_path / "out")
    assert len(r2.artifacts) == 0
    assert r2.nav_series.frame.height == 0
    assert r2.final_state.cash == 1_000_000.0
    assert r2.final_state.as_of_date == D8
    assert r2.final_state.positions.height == 0
    assert r2.final_state.positions.schema["code"] == pl.String


def test_deterministic_output(tmp_path):
    r = _run(tmp_path)
    save_backtest_result(r, tmp_path / "o1", created_at="T")
    save_backtest_result(r, tmp_path / "o2", created_at="T")
    for rel in ("artifacts/fills.parquet", "nav/nav_series.parquet",
                "state/final_state.parquet"):
        assert pl.read_parquet(tmp_path / "o1" / rel).equals(
            pl.read_parquet(tmp_path / "o2" / rel))
    assert (tmp_path / "o1" / "manifest.json").read_bytes() == \
        (tmp_path / "o2" / "manifest.json").read_bytes()


def test_no_db_writes(tmp_path):
    dbp = _db(tmp_path)
    r = run_backtest(_target(), ExecutionSpec.model_validate(
        {"initial_cash": 1_000_000.0}), dbp)
    n0 = duckdb.connect(dbp).execute("SELECT count(*) FROM daily").fetchone()[0]
    save_backtest_result(r, tmp_path / "out")
    load_backtest_result(tmp_path / "out")
    n1 = duckdb.connect(dbp).execute("SELECT count(*) FROM daily").fetchone()[0]
    assert n0 == n1


# ---------------- error contract ----------------

def test_load_missing_dir_fails(tmp_path):
    with pytest.raises(ValueError, match="目录|不存在"):
        load_backtest_result(tmp_path / "nope")


def test_load_missing_manifest_fails(tmp_path):
    out = tmp_path / "out"
    save_backtest_result(_run(tmp_path), out)
    (out / "manifest.json").unlink()
    with pytest.raises(ValueError, match="manifest"):
        load_backtest_result(out)


def test_load_unknown_version_fails(tmp_path):
    out = tmp_path / "out"
    save_backtest_result(_run(tmp_path), out)
    doc = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    doc["schema_version"] = "999"
    (out / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version|version"):
        load_backtest_result(out)


def test_load_missing_file_fails(tmp_path):
    out = tmp_path / "out"
    save_backtest_result(_run(tmp_path), out)
    (out / "nav" / "nav_series.parquet").unlink()
    with pytest.raises(ValueError, match="nav_series"):
        load_backtest_result(out)


def test_load_missing_column_fails(tmp_path):
    out = tmp_path / "out"
    save_backtest_result(_run(tmp_path), out)
    f = pl.read_parquet(out / "artifacts" / "fills.parquet").drop("commission")
    f.write_parquet(out / "artifacts" / "fills.parquet")
    with pytest.raises(ValueError, match="commission|缺列|columns"):
        load_backtest_result(out)


def test_load_wrong_dtype_fails(tmp_path):
    out = tmp_path / "out"
    save_backtest_result(_run(tmp_path), out)
    f = pl.read_parquet(out / "artifacts" / "orders.parquet").with_columns(
        pl.col("quantity").cast(pl.Float64))
    f.write_parquet(out / "artifacts" / "orders.parquet")
    with pytest.raises(ValueError, match="dtype|quantity"):
        load_backtest_result(out)
