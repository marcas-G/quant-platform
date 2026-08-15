import polars as pl
import pytest

from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import assess_sparsity, build_final_db


def _staging(tmp_path):
    """daily 4 只股票 1 天：sparse_field 75% null、half_field 25% null。"""
    db = PlatformDB(tmp_path / "staging.duckdb")
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102"] * 4,
        "ts_code": ["A", "B", "C", "D"],
        "close": [10.0, 20.0, 30.0, 40.0],
        "sparse_field": [1.0, None, None, None],  # null_ratio 0.75
        "half_field": [1.0, 2.0, 3.0, None],      # null_ratio 0.25
    }), keys=["trade_date", "ts_code"])
    return db


def test_assess_sparsity_metrics(tmp_path):
    db = _staging(tmp_path)
    report = assess_sparsity(db)
    sf = report["daily"]["sparse_field"]
    assert sf["null_ratio"] == 0.75
    assert sf["stock_coverage"] == 0.25
    assert sf["first_date"] == "20240102"
    assert report["daily"]["half_field"]["null_ratio"] == 0.25


def test_build_final_db_excludes_sparse_fields(tmp_path):
    staging = _staging(tmp_path)
    final_path = tmp_path / "final.duckdb"
    result = build_final_db(staging, final_path)
    excluded = result["excluded_fields"]["daily"]
    assert "sparse_field" in excluded and "half_field" in excluded  # 75%/25% 均 > 20%
    final = PlatformDB(final_path)
    assert "sparse_field" not in final.describe("daily")
    assert "half_field" not in final.describe("daily")
    assert "close" in final.describe("daily")


def test_build_final_db_thresholds_configurable(tmp_path):
    staging = _staging(tmp_path)
    # half_field 的 stock_coverage=0.75 < 默认 0.8，仅放宽 null 阈值仍会被 coverage 剔除；
    # 同时放宽 coverage_threshold 才能观察 null_threshold 生效（任一超限即剔除）
    result = build_final_db(staging, tmp_path / "f2.duckdb",
                            null_threshold=0.5, coverage_threshold=0.7)
    assert "half_field" not in result["excluded_fields"]["daily"]  # null 25% < 50% 且 coverage 75% >= 70% → 保留
    assert "sparse_field" in result["excluded_fields"]["daily"]    # null 75% > 50% 仍剔除


def test_assess_sparsity_skips_keys_and_trade_cal(tmp_path):
    """键列（trade_date/ts_code）与 trade_cal 不进稀疏报告。"""
    db = _staging(tmp_path)
    db.upsert("trade_cal", pl.DataFrame({
        "exchange": ["SSE"],
        "cal_date": ["20240102"],
        "is_open": [1],
    }), keys=["exchange", "cal_date"])
    report = assess_sparsity(db)
    assert set(report) == {"daily"}
    assert set(report["daily"]) == {"close", "sparse_field", "half_field"}


def test_assess_sparsity_all_null_field(tmp_path):
    db = PlatformDB(tmp_path / "an.duckdb")
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102"] * 2,
        "ts_code": ["A", "B"],
        "all_null": [None, None],
        "full": [1.0, 2.0],
    }), keys=["trade_date", "ts_code"])
    report = assess_sparsity(db)
    an = report["daily"]["all_null"]
    assert an["null_ratio"] == 1.0
    assert an["stock_coverage"] == 0.0
    assert an["first_date"] is None
    assert report["daily"]["full"]["null_ratio"] == 0.0
    assert report["daily"]["full"]["stock_coverage"] == 1.0


def test_assess_sparsity_empty_table(tmp_path):
    """空表：无行可评估，null_ratio 按约定为 1.0，first_date None，不报错。"""
    db = PlatformDB(tmp_path / "et.duckdb")
    with db.connect() as con:
        con.execute('CREATE TABLE "daily" ("trade_date" VARCHAR, "ts_code" VARCHAR, "close" DOUBLE)')
    report = assess_sparsity(db)
    assert report["daily"]["close"]["null_ratio"] == 1.0
    assert report["daily"]["close"]["first_date"] is None


def test_assess_sparsity_stock_basic_no_date(tmp_path):
    """stock_basic 无日期列：first_date 为 None，不报错。"""
    db = PlatformDB(tmp_path / "sb.duckdb")
    db.upsert("stock_basic", pl.DataFrame({
        "ts_code": ["A.SZ", "B.SZ"],
        "name": ["甲", "乙"],
        "empty_field": [None, None],
    }), keys=["ts_code"])
    report = assess_sparsity(db)
    assert report["stock_basic"]["name"]["first_date"] is None
    assert report["stock_basic"]["name"]["null_ratio"] == 0.0
    assert report["stock_basic"]["empty_field"]["null_ratio"] == 1.0


def test_assess_sparsity_missing_db(tmp_path):
    """库文件不存在：返回空报告而非抛错。"""
    assert assess_sparsity(PlatformDB(tmp_path / "nope.duckdb")) == {}


def test_build_final_db_preserves_data_and_keys(tmp_path):
    staging = _staging(tmp_path)
    final = PlatformDB(tmp_path / "final.duckdb")
    build_final_db(staging, final.path)
    assert final.describe("daily") == ["trade_date", "ts_code", "close"]  # 稀疏列物理剔除
    assert final.query('SELECT count(*) AS n FROM "daily"')["n"][0] == 4
    assert final.query('SELECT "close" FROM "daily" ORDER BY "ts_code"')["close"].to_list() == \
        [10.0, 20.0, 30.0, 40.0]


def test_build_final_db_coverage_threshold(tmp_path):
    """stock_coverage 低于阈值的字段剔除（与 null_ratio 独立生效）。"""
    staging = _staging(tmp_path)
    result = build_final_db(staging, tmp_path / "f3.duckdb",
                            null_threshold=0.5, coverage_threshold=0.3)
    excluded = result["excluded_fields"]["daily"]
    assert "sparse_field" in excluded     # coverage 0.25 < 0.3
    assert "half_field" not in excluded   # coverage 0.75 >= 0.3 且 null 25% < 50%
    assert "close" not in excluded


def test_build_final_db_skips_table_when_no_keep_columns(tmp_path):
    """表内全部字段被剔除（无可保留列）时跳过建表。"""
    staging = PlatformDB(tmp_path / "s.duckdb")
    staging.upsert("extra", pl.DataFrame({"payload": [None, None]}), keys=[])
    result = build_final_db(staging, tmp_path / "final.duckdb")
    assert "extra" not in result["tables"]
    assert "extra" not in PlatformDB(tmp_path / "final.duckdb").list_tables()


def test_build_final_db_non_ascii_table(tmp_path):
    """非 ASCII 表名/列名（带引号标识符）正常评估与复制。"""
    staging = PlatformDB(tmp_path / "na.duckdb")
    staging.upsert("行情表", pl.DataFrame({
        "trade_date": ["20240102"] * 2,
        "ts_code": ["A", "B"],
        "价格": [1.0, 2.0],
    }), keys=["trade_date", "ts_code"])
    result = build_final_db(staging, tmp_path / "final.duckdb")
    assert "行情表" in result["tables"]
    final = PlatformDB(tmp_path / "final.duckdb")
    assert final.describe("行情表") == ["trade_date", "ts_code", "价格"]


def test_build_final_db_overwrites_existing(tmp_path):
    """最终库已存在时重建应整体替换：schema 按最新评估收缩，而非报表已存在报错。"""
    staging = _staging(tmp_path)
    final_path = tmp_path / "final.duckdb"
    build_final_db(staging, final_path)
    assert "close" in PlatformDB(final_path).describe("daily")
    staging.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102"] * 4,
        "ts_code": ["A", "B", "C", "D"],
        "close": [10.0, None, None, None],  # 二次评估时 close 也稀疏
    }), keys=["trade_date", "ts_code"])
    build_final_db(staging, final_path)
    final = PlatformDB(final_path)
    assert final.describe("daily") == ["trade_date", "ts_code"]
    assert final.query('SELECT count(*) AS n FROM "daily"')["n"][0] == 4


def test_build_final_db_missing_staging_raises(tmp_path):
    """暂存库不存在：报明确中文错误，而非 ATTACH 的英文 IO 错。"""
    staging = PlatformDB(tmp_path / "nope.duckdb")
    with pytest.raises(ValueError, match="暂存库"):
        build_final_db(staging, tmp_path / "final.duckdb")
