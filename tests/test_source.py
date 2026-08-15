import datetime
import os

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


def test_load_daily_float32_cast_and_code_string(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"]).collect()
    assert df.schema["close"] == pl.Float32
    assert df.schema["code"] == pl.String


def test_load_daily_column_pruning(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["close"]).collect()
    assert df.columns == ["date", "code", "close"]


def test_load_daily_rejects_empty_codes(tmp_path):
    build_db(tmp_path)
    with pytest.raises(ValueError, match="universe"):
        load_daily(tmp_path / "t.duckdb", [])


def test_load_daily_opens_read_only(tmp_path):
    build_db(tmp_path)
    # 持有一个只读连接；若 load_daily 以读写模式打开，会因配置不同抛 ConnectionException
    ro = duckdb.connect(tmp_path / "t.duckdb", read_only=True)
    try:
        df = load_daily(tmp_path / "t.duckdb", ["000001"]).collect()
        assert df.height == 2
    finally:
        ro.close()


def test_load_daily_date_end_inclusive(tmp_path):
    build_db(tmp_path)
    df = load_daily(
        tmp_path / "t.duckdb", ["000001"], date_start="2024-01-02", date_end="2024-01-02"
    ).collect()
    assert df["date"].to_list() == [datetime.date(2024, 1, 2)]


def test_load_daily_multi_code_filter(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001", "600519"]).collect()
    assert df["code"].to_list() == ["000001", "000001", "600519"]


def test_load_daily_empty_result_keeps_schema(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["999999"]).collect()
    assert df.height == 0
    assert df.schema["date"] == pl.Date
    assert df.schema["code"] == pl.String
    assert df.schema["close"] == pl.Float32


def test_load_daily_unknown_col_raises_value_error(tmp_path):
    build_db(tmp_path)
    with pytest.raises(ValueError, match="未知列名"):
        load_daily(tmp_path / "t.duckdb", ["000001"], cols=["nonexistent"]).collect()


def test_load_daily_unknown_col_does_not_lock_file(tmp_path):
    build_db(tmp_path)
    db_path = tmp_path / "t.duckdb"
    with pytest.raises(ValueError, match="未知列名"):
        load_daily(db_path, ["000001"], cols=["nonexistent"]).collect()
    # 错误后无残留锁：可重新以读写模式打开并删除文件（Windows 锁回归验证）
    db = duckdb.connect(db_path, read_only=False)
    db.execute("CREATE TABLE x (a INT)")
    db.close()
    os.remove(db_path)


def test_load_daily_query_error_does_not_lock_file(tmp_path):
    # 连接内部报错（daily 表不存在 -> BinderException）也必须释放连接
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE other (x INT)")
    db.close()
    db_path = tmp_path / "t.duckdb"
    with pytest.raises(duckdb.Error):
        load_daily(db_path, ["000001"]).collect()
    db2 = duckdb.connect(db_path, read_only=False)
    db2.execute("CREATE TABLE y (a INT)")
    db2.close()
    db_path.unlink()
