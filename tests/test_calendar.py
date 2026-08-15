import datetime

import duckdb
import polars as pl
import pytest
from polars.exceptions import ColumnNotFoundError

from factorlab.data.calendar import fill_suspensions, trading_calendar


# ---------- trading_calendar ----------


def test_trading_calendar_deduplicates(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE daily (date VARCHAR, code VARCHAR)")
    db.execute("INSERT INTO daily VALUES ('2024-01-02','A'), ('2024-01-03','A'), ('2024-01-03','B')")
    db.close()
    cal = trading_calendar(tmp_path / "t.duckdb")
    assert cal.to_list() == [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)]


def test_trading_calendar_ordered_even_with_reverse_insertion(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE daily (date VARCHAR, code VARCHAR)")
    db.execute("INSERT INTO daily VALUES ('2024-01-03','A'), ('2024-01-02','A')")
    db.close()
    cal = trading_calendar(tmp_path / "t.duckdb")
    assert cal.to_list() == [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)]


def test_trading_calendar_date_range_inclusive(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE daily (date VARCHAR, code VARCHAR)")
    db.execute(
        "INSERT INTO daily VALUES ('2024-01-02','A'), ('2024-01-03','A'), ('2024-01-04','A')"
    )
    db.close()
    cal = trading_calendar(tmp_path / "t.duckdb", date_start="2024-01-02", date_end="2024-01-03")
    assert cal.to_list() == [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)]


def test_trading_calendar_empty_table_returns_empty_date_series(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE daily (date VARCHAR, code VARCHAR)")
    db.close()
    cal = trading_calendar(tmp_path / "t.duckdb")
    assert cal.to_list() == []
    assert cal.dtype == pl.Date


def test_trading_calendar_missing_db_raises(tmp_path):
    with pytest.raises(duckdb.Error):
        trading_calendar(tmp_path / "missing.duckdb")


# ---------- fill_suspensions ----------


def test_fill_suspensions_adds_missing_rows():
    calendar = pl.Series("date", [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)], dtype=pl.Date)
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 3)],
        "code": ["A"],
        "close": [10.0],
    })
    out = fill_suspensions(df, calendar).sort(["code", "date"])
    assert out.height == 2
    assert out["close"].to_list() == [None, 10.0]   # 停牌日 close 为 null


def test_fill_suspensions_keeps_existing_data():
    calendar = pl.Series("date", [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)], dtype=pl.Date)
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)],
        "code": ["A", "A"],
        "close": [9.0, 10.0],
    })
    out = fill_suspensions(df, calendar).sort(["date"])
    assert out["close"].to_list() == [9.0, 10.0]


def test_fill_suspensions_multi_code_no_cross_asset_leak():
    # 回归：A 在 1-4 有数据，B 在 1-4 停牌——B 的 1-4 close 必须为 null，不得取到 A 的值
    calendar = pl.Series(
        "date",
        [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3), datetime.date(2024, 1, 4)],
        dtype=pl.Date,
    )
    df = pl.DataFrame({
        "date": [
            datetime.date(2024, 1, 2),
            datetime.date(2024, 1, 4),
            datetime.date(2024, 1, 2),
            datetime.date(2024, 1, 3),
        ],
        "code": ["A", "A", "B", "B"],
        "close": [9.0, 11.0, 20.0, 21.0],
    })
    out = fill_suspensions(df, calendar).sort(["code", "date"])
    assert out.height == 6
    assert out["close"].to_list() == [9.0, None, 11.0, 20.0, 21.0, None]  # A 停牌 1-3，B 停牌 1-4


def test_fill_suspensions_duplicate_code_rows_kept():
    # 同一 code 同一日的重复行保留（补全只建码集，不去重 df 本身）
    calendar = pl.Series("date", [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)], dtype=pl.Date)
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 3), datetime.date(2024, 1, 3)],
        "code": ["A", "A"],
        "close": [10.0, 11.0],
    })
    out = fill_suspensions(df, calendar).sort(["date", "close"])
    assert out.height == 3
    assert out["close"].to_list() == [None, 10.0, 11.0]


def test_fill_suspensions_empty_calendar_returns_empty():
    calendar = pl.Series("date", [], dtype=pl.Date)
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 3)],
        "code": ["A"],
        "close": [10.0],
    })
    out = fill_suspensions(df, calendar)
    assert out.height == 0
    assert out.columns == ["date", "code", "close"]


def test_fill_suspensions_empty_df_returns_empty():
    calendar = pl.Series("date", [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)], dtype=pl.Date)
    df = pl.DataFrame(schema={"date": pl.Date, "code": pl.String, "close": pl.Float64})
    out = fill_suspensions(df, calendar)
    assert out.height == 0
    assert out.columns == ["date", "code", "close"]


def test_fill_suspensions_missing_columns_raises():
    calendar = pl.Series("date", [datetime.date(2024, 1, 2)], dtype=pl.Date)
    df = pl.DataFrame({"date": [datetime.date(2024, 1, 2)], "close": [10.0]})  # 缺 code
    with pytest.raises(ColumnNotFoundError):
        fill_suspensions(df, calendar)
