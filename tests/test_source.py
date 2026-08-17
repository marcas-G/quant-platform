import datetime
import os

import duckdb
import polars as pl
import pytest

from factorlab.data.source import load_daily


def build_db(tmp_path):
    """平台库风格假库：tushare 原始列名（trade_date 'YYYYMMDD'/ts_code 带后缀/vol）。"""
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE)")
    db.execute("""INSERT INTO daily VALUES
        ('000001.SZ', '20240102', 10.0, 11.0, 9.5, 10.5, 10.2, 0.3, 0.0294, 100000.0, 1e6),
        ('000001.SZ', '20240103', 10.5, 11.5, 10.0, 11.0, 10.5, 0.5, 0.0476, 110000.0, 1.1e6),
        ('600519.SH', '20240102', 20.0, 21.0, 19.0, 20.5, 19.8, 0.7, 0.0354, 200000.0, 2e6)""")
    db.execute("CREATE TABLE adj_factor (ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
    db.execute("""INSERT INTO adj_factor VALUES
        ('000001.SZ', '20240102', 1.0), ('000001.SZ', '20240103', 1.0),
        ('600519.SH', '20240102', 1.2)""")
    db.execute("CREATE TABLE daily_basic (ts_code VARCHAR, trade_date VARCHAR, turnover_rate DOUBLE, total_mv DOUBLE)")
    db.execute("""INSERT INTO daily_basic VALUES
        ('000001.SZ', '20240102', 1.5, 1e6), ('000001.SZ', '20240103', 1.8, 1.1e6),
        ('600519.SH', '20240102', 0.5, 5e6)""")
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


def test_load_daily_maps_platform_columns(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["close", "adj_factor"]).collect()
    assert df.columns == ["date", "code", "close", "adj_factor"]
    assert df["code"].to_list() == ["000001", "000001"]  # ts_code 去后缀
    assert df["date"].dtype == pl.Date


def test_load_daily_maps_volume_column(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["volume"]).collect()
    assert "volume" in df.columns  # vol → volume
    assert df["volume"].to_list() == [100000.0, 110000.0]


def test_load_daily_joins_daily_basic_when_requested(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["close", "turnover"]).collect()
    assert "turnover" in df.columns
    assert df["turnover"].to_list() == pytest.approx([1.5, 1.8])  # turnover_rate join（float32 精度）


def test_load_daily_joins_total_mv(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["close", "total_mv"]).collect()
    assert df["total_mv"].to_list() == [1000000.0, 1100000.0]


def test_load_daily_close_always_loaded(tmp_path):
    # close 恒加载（forward/评估依赖——M3a 契约），即使 cols 未请求
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["open"]).collect()
    assert df.columns == ["date", "code", "open", "close"]


def test_load_daily_basic_columns_not_joined_by_default(tmp_path):
    # daily_basic 仅按需 join：cols 不含 turnover/total_mv 时无 basic 列
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["open"]).collect()
    assert "turnover" not in df.columns
    assert "total_mv" not in df.columns


def test_load_daily_mixed_daily_and_basic_cols(tmp_path):
    build_db(tmp_path)
    df = load_daily(tmp_path / "t.duckdb", ["000001"], cols=["open", "turnover", "close"]).collect()
    assert df["open"].to_list() == [10.0, 10.5]
    assert df["turnover"].to_list() == pytest.approx([1.5, 1.8])
    assert df["close"].to_list() == [10.5, 11.0]


def test_load_daily_accepts_yyyymmdd_date_range(tmp_path):
    # 日期过滤参数化：'YYYYMMDD' 与 'YYYY-MM-DD' 均接受（平台库 trade_date 为 YYYYMMDD）
    build_db(tmp_path)
    df = load_daily(
        tmp_path / "t.duckdb", ["000001", "600519"],
        date_start="20240102", date_end="20240102",
    ).collect()
    assert df["date"].to_list() == [datetime.date(2024, 1, 2), datetime.date(2024, 1, 2)]


def test_load_daily_drops_daily_row_without_adj_factor(tmp_path):
    # adj_factor 恒 join（inner）：daily 行缺 adj_factor 时被排除（复权不可消费）
    build_db(tmp_path)
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("INSERT INTO daily VALUES ('000001.SZ', '20240104', 11.5, 12.0, 11.0, 12.0, 11.0, 1.0, 0.0909, 120000.0, 1.2e6)")  # adj_factor 无此日
    db.close()
    df = load_daily(tmp_path / "t.duckdb", ["000001"]).collect()
    assert df["date"].to_list() == [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)]


def test_load_daily_float32_disabled(tmp_path):
    build_db(tmp_path)
    df = load_daily(
        tmp_path / "t.duckdb", ["000001"], cols=["close", "adj_factor"], float32=False
    ).collect()
    assert df.schema["close"] == pl.Float64
    assert df.schema["adj_factor"] == pl.Float64
    assert df.schema["date"] == pl.Date
    assert df.schema["code"] == pl.String


def test_load_daily_rejects_raw_platform_vol_name(tmp_path):
    # 平台库原始列名 vol 不暴露：请求引擎列名 volume（错误消息给提示）
    build_db(tmp_path)
    with pytest.raises(ValueError, match="未知列名"):
        load_daily(tmp_path / "t.duckdb", ["000001"], cols=["vol"]).collect()


def test_daily_basic_extended_columns_loaded(tmp_path):
    """扩展字段（pe_ttm/pb/dv_ratio）经 daily_basic join 加载。"""
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("create table daily (trade_date varchar, ts_code varchar, open double, high double, low double, close double, vol double, amount double)")
    con.execute("create table adj_factor (trade_date varchar, ts_code varchar, adj_factor double)")
    con.execute("create table daily_basic (trade_date varchar, ts_code varchar, turnover_rate double, total_mv double, circ_mv double, pe_ttm double, pb double, dv_ratio double)")
    for d in ["20240102", "20240103", "20240104"]:
        con.execute("insert into daily values (?, ?, 10, 11, 9, 10.5, 1000, 100000)", [d, "000001.SZ"])
        con.execute("insert into adj_factor values (?, ?, 1.0)", [d, "000001.SZ"])
        con.execute("insert into daily_basic values (?, ?, 1.0, 1e10, 5e9, 12.0, 1.5, 0.02)", [d, "000001.SZ"])
    con.close()
    df = load_daily(db, ["000001"], cols=["close", "pe_ttm", "pb", "dv_ratio"]).collect()
    assert df["pe_ttm"].to_list() == [12.0] * 3
    assert df["pb"].to_list() == [1.5] * 3
    assert df["dv_ratio"].to_list() == [0.02] * 3
