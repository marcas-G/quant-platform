import datetime

import duckdb
import polars as pl
import pytest

from factorlab.data.source import load_daily


def build_db(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE daily (date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, amount DOUBLE, turnover DOUBLE, pct_chg DOUBLE, code VARCHAR)")
    db.execute("""INSERT INTO daily VALUES
        ('2024-01-02', 10.0, 11.0, 9.5, 10.5, 1000.0, 1e6, 0.01, 0.5, '000001'),
        ('2024-01-03', 10.5, 11.5, 10.0, 11.0, 1100.0, 1.1e6, 0.02, 0.4, '000001'),
        ('2024-01-02', 20.0, 21.0, 19.0, 20.5, 2000.0, 2e6, 0.01, 0.3, '600519')""")
    db.close()


def test_load_daily_filters_codes_and_dates(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], date_start="2024-01-03").collect()
    assert df["code"].to_list() == ["000001"]
    assert df["date"].to_list() == [datetime.date(2024, 1, 3)]


def test_load_daily_float32_cast(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"]).collect()
    assert df.schema["close"] == pl.Float32


def test_load_daily_column_pruning(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["close"]).collect()
    assert df.columns == ["date", "code", "close"]


def test_load_daily_rejects_empty_codes(tmp_path):
    build_db(tmp_path)
    with pytest.raises(ValueError, match="universe"):
        load_daily(tmp_path / "t.duckdb", [])
