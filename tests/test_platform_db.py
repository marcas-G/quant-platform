import duckdb
import polars as pl
import pytest

from factorlab.data.platform_db import PlatformDB


def build_db(tmp_path):
    return PlatformDB(tmp_path / "p.duckdb")


def test_upsert_creates_table_and_deduplicates(tmp_path):
    db = build_db(tmp_path)
    df1 = pl.DataFrame({"trade_date": ["20240102", "20240102"], "ts_code": ["A", "B"], "close": [10.0, 20.0]})
    df2 = pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A"], "close": [11.0]})
    db.upsert("daily", df1, keys=["trade_date", "ts_code"])
    db.upsert("daily", df2, keys=["trade_date", "ts_code"])
    out = db.query("SELECT * FROM daily ORDER BY ts_code")
    assert out.height == 2
    assert out.filter(pl.col("ts_code") == "A")["close"][0] == 11.0  # 去重后更新


def test_upsert_keys_empty_keeps_duplicates(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240102"],
        "ts_code": ["A", "A"],
        "close": [10.0, 10.0],
    }), keys=[])
    assert db.query("SELECT count(*) AS n FROM daily")["n"][0] == 2


def test_upsert_empty_df_is_noop(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({"trade_date": [], "ts_code": [], "close": []}),
              keys=["trade_date", "ts_code"])
    assert db.list_tables() == []


def test_upsert_rollback_on_error(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102"], "ts_code": ["A"], "close": [10.0],
    }), keys=["trade_date", "ts_code"])
    # 同 key 批次插入中途失败：DELETE 与 INSERT 同事务，整体回滚
    with pytest.raises(ValueError, match="daily"):
        db.upsert("daily", pl.DataFrame({
            "trade_date": ["20240102"], "ts_code": ["A"], "close": ["bad"],
        }), keys=["trade_date", "ts_code"])
    out = db.query("SELECT * FROM daily")
    assert out.height == 1
    assert out["close"][0] == 10.0  # 先前已提交行保留（DELETE 已回滚）


def test_connect_returns_usable_write_connection(tmp_path):
    db = build_db(tmp_path)
    with db.connect() as con:
        con.execute("CREATE TABLE t (x INTEGER)")
        con.execute("INSERT INTO t VALUES (1)")
        assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    # 连接随 with 关闭；独立连接可见写入
    assert db.query("SELECT count(*) AS n FROM t")["n"][0] == 1


def test_upsert_on_reuses_connection_and_deduplicates(tmp_path):
    db = build_db(tmp_path)
    with db.connect() as con:
        db.upsert_on(con, "daily", pl.DataFrame({
            "trade_date": ["20240102", "20240102"], "ts_code": ["A", "B"], "close": [10.0, 20.0],
        }), keys=["trade_date", "ts_code"])
        db.upsert_on(con, "daily", pl.DataFrame({
            "trade_date": ["20240102"], "ts_code": ["A"], "close": [11.0],
        }), keys=["trade_date", "ts_code"])
    out = db.query("SELECT * FROM daily ORDER BY ts_code")
    assert out.height == 2
    assert out.filter(pl.col("ts_code") == "A")["close"][0] == 11.0  # 默认 dedup=True 去重更新


def test_upsert_on_dedup_false_keeps_duplicates(tmp_path):
    db = build_db(tmp_path)
    df = pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A"], "close": [10.0]})
    with db.connect() as con:
        db.upsert_on(con, "daily", df, keys=["trade_date", "ts_code"], dedup=False)
        db.upsert_on(con, "daily", df, keys=["trade_date", "ts_code"], dedup=False)
    assert db.query("SELECT count(*) AS n FROM daily")["n"][0] == 2  # 纯 INSERT 不去重


def test_upsert_filters_missing_columns(tmp_path):
    """建表后剔除一列（模拟 build_final_db 稀疏剔除）再 upsert 全字段 df：
    仅插入表存在的列，不抛 Binder 错误（refresh 写最终库的崩溃窗口）。"""
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102"], "ts_code": ["A"], "close": [10.0], "sparse_field": [1.0],
    }), keys=["trade_date", "ts_code"])
    with db.connect() as con:  # 模拟最终库：物理剔除稀疏字段
        con.execute("ALTER TABLE daily DROP COLUMN sparse_field")
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103"],
        "ts_code": ["A", "A"],
        "close": [11.0, 12.0],
        "sparse_field": [2.0, 3.0],  # 表不存在此列：应被过滤
    }), keys=["trade_date", "ts_code"])
    out = db.query("SELECT * FROM daily ORDER BY trade_date")
    assert out.height == 2
    assert out.columns == ["trade_date", "ts_code", "close"]  # sparse_field 未插入
    assert out.filter(pl.col("trade_date") == "20240102")["close"][0] == 11.0  # 去重替换生效


def test_upsert_on_empty_df_is_noop(tmp_path):
    db = build_db(tmp_path)
    with db.connect() as con:
        db.upsert_on(con, "daily", pl.DataFrame({"trade_date": [], "ts_code": [], "close": []}),
                     keys=["trade_date", "ts_code"])
    assert db.list_tables() == []


def test_upsert_on_rollback_and_connection_reusable(tmp_path):
    db = build_db(tmp_path)
    with db.connect() as con:
        db.upsert_on(con, "daily", pl.DataFrame({
            "trade_date": ["20240102"], "ts_code": ["A"], "close": [10.0],
        }), keys=["trade_date", "ts_code"])
        with pytest.raises(ValueError, match="daily"):
            db.upsert_on(con, "daily", pl.DataFrame({
                "trade_date": ["20240102"], "ts_code": ["A"], "close": ["bad"],
            }), keys=["trade_date", "ts_code"])
        # 事务已回滚，同一连接可继续使用
        db.upsert_on(con, "daily", pl.DataFrame({
            "trade_date": ["20240103"], "ts_code": ["A"], "close": [11.0],
        }), keys=["trade_date", "ts_code"])
    assert db.query("SELECT count(*) AS n FROM daily")["n"][0] == 2


def test_query_with_params(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103"],
        "ts_code": ["A", "A"],
        "close": [10.0, 11.0],
    }), keys=["trade_date", "ts_code"])
    out = db.query("SELECT close FROM daily WHERE trade_date = ?", ["20240103"])
    assert out["close"][0] == 11.0


def test_list_tables_and_describe(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({"trade_date": ["20240102"], "ts_code": ["A"], "close": [1.0]}), keys=[])
    assert db.list_tables() == ["daily"]
    assert set(db.describe("daily")) >= {"trade_date", "ts_code", "close"}


def test_describe_unknown_table_raises(tmp_path):
    db = build_db(tmp_path)
    with pytest.raises(duckdb.Error):
        db.describe("no_such_table")


def test_integrity_calendar_gaps(tmp_path):
    db = build_db(tmp_path)
    db.upsert("trade_cal", pl.DataFrame({"cal_date": ["20240102", "20240103", "20240104"], "is_open": [1, 1, 1]}), keys=[])
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240104"],
        "ts_code": ["A", "A"],
        "close": [10.0, 11.0],
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    gaps = report["daily"]["calendar_gaps"]
    assert gaps["failed"] > 0
    assert "20240103" in gaps["details"]


def test_integrity_duplicate_rows(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240102"],
        "ts_code": ["A", "A"],
        "close": [10.0, 10.0],
    }), keys=[])
    report = db.integrity_check()
    assert report["daily"]["duplicate_rows"]["failed"] == 1


def test_integrity_pct_chg_consistency(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103"],
        "ts_code": ["A", "A"],
        "close": [10.0, 11.0],
        "pct_chg": [0.0, 9.0],  # 应为 10.0
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    assert report["daily"]["pct_chg_consistency"]["failed"] > 0


def test_integrity_pct_chg_consistent_passes(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103"],
        "ts_code": ["A", "A"],
        "close": [10.0, 11.0],
        "pct_chg": [0.0, 10.0],  # (11/10-1)*100 = 10.0
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    assert report["daily"]["pct_chg_consistency"]["failed"] == 0


def test_integrity_adj_factor_valid(tmp_path):
    db = build_db(tmp_path)
    db.upsert("adj_factor", pl.DataFrame({
        "trade_date": ["20240102"], "ts_code": ["A"], "adj_factor": [0.0],
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    assert report["adj_factor"]["adj_factor_valid"]["failed"] == 1


def test_integrity_stk_limit_boundary(tmp_path):
    db = build_db(tmp_path)
    db.upsert("stk_limit", pl.DataFrame({
        "trade_date": ["20240102"], "ts_code": ["A"], "up_limit": [10.0], "down_limit": [5.0],
    }), keys=["trade_date", "ts_code"])
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102"], "ts_code": ["A"], "close": [15.0],  # 超 up_limit
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    assert report["daily"]["stk_limit_boundary"]["failed"] == 1


def test_integrity_stk_limit_at_boundary_passes(tmp_path):
    db = build_db(tmp_path)
    db.upsert("stk_limit", pl.DataFrame({
        "trade_date": ["20240102"], "ts_code": ["A"], "up_limit": [10.0], "down_limit": [5.0],
    }), keys=["trade_date", "ts_code"])
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102"], "ts_code": ["A"], "close": [10.0],  # 恰在涨停价，容差内
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    assert report["daily"]["stk_limit_boundary"]["failed"] == 0


def test_integrity_market_cap_valid(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily_basic", pl.DataFrame({
        "trade_date": ["20240102"], "ts_code": ["A"], "total_mv": [0.0],
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    assert report["daily_basic"]["market_cap_valid"]["failed"] == 1


def test_integrity_skips_missing_dependency(tmp_path):
    db = build_db(tmp_path)
    report = db.integrity_check()
    assert report["daily"]["calendar_gaps"]["passed"] is True
    assert report["daily"]["calendar_gaps"]["skipped"] is True
    assert "跳过" in report["daily"]["calendar_gaps"]["details"][0]
    assert report["adj_factor"]["adj_factor_valid"]["passed"] is True
    assert report["adj_factor"]["adj_factor_valid"]["skipped"] is True


def test_integrity_skipped_when_dep_missing(tmp_path):
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102"], "ts_code": ["A"], "close": [10.0],
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    assert report["daily"]["calendar_gaps"]["skipped"] is True      # 无 trade_cal
    assert report["daily"]["duplicate_rows"]["skipped"] is False
    assert report["daily"]["pct_chg_consistency"]["skipped"] is True  # daily 无 pct_chg 列，结构不匹配


def test_integrity_all_green(tmp_path):
    db = build_db(tmp_path)
    db.upsert("trade_cal", pl.DataFrame({"cal_date": ["20240102", "20240103"], "is_open": [1, 1]}), keys=[])
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103"],
        "ts_code": ["A", "A"],
        "close": [10.0, 11.0],
        "pct_chg": [0.0, 10.0],  # (11/10-1)*100 = 10.0
    }), keys=["trade_date", "ts_code"])
    db.upsert("adj_factor", pl.DataFrame({
        "trade_date": ["20240102", "20240103"], "ts_code": ["A", "A"], "adj_factor": [1.0, 1.0],
    }), keys=["trade_date", "ts_code"])
    db.upsert("stk_limit", pl.DataFrame({
        "trade_date": ["20240102", "20240103"], "ts_code": ["A", "A"],
        "up_limit": [11.0, 11.0], "down_limit": [5.0, 5.0],
    }), keys=["trade_date", "ts_code"])
    db.upsert("daily_basic", pl.DataFrame({
        "trade_date": ["20240102", "20240103"], "ts_code": ["A", "A"], "total_mv": [100.0, 110.0],
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    assert set(report) == {"daily", "adj_factor", "daily_basic"}
    for rules in report.values():
        for entry in rules.values():
            assert entry["passed"] is True
            assert entry["skipped"] is False


def test_integrity_pct_chg_uses_pre_close_on_ex_rights_day(tmp_path):
    # 真实除权（10 送 5）：参考价 7.33 ≠ 前收 11 → lag(close) 环比误报，pre_close 口径正确
    db = build_db(tmp_path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103", "20240104"],
        "ts_code": ["A", "A", "A"],
        "close": [10.0, 11.0, 8.0],
        "pre_close": [None, 10.0, 7.333],    # 官方除权参考价
        "pct_chg": [None, 10.0, 9.09],       # 官方口径（8/7.333-1）
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    assert report["daily"]["pct_chg_consistency"]["passed"] is True  # 须用 pre_close 才通过


def test_integrity_calendar_gaps_ignores_future_days(tmp_path):
    """trade_cal 含未来公告日（如 2026-12-31）——daily 无未来数据，规则应排除未来日。"""
    db = build_db(tmp_path)
    db.upsert("trade_cal", pl.DataFrame({
        "cal_date": ["20240102", "20261231"],  # 未来公告日（20261231）不算缺日
        "is_open": [1, 1],
    }), keys=[])
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102"],
        "ts_code": ["A"],
        "close": [10.0],
    }), keys=["trade_date", "ts_code"])
    report = db.integrity_check()
    gaps = report["daily"]["calendar_gaps"]
    assert gaps["passed"] is True  # 未来日不算缺日
