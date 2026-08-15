import polars as pl
import pytest

from factorlab.data.platform_db import PlatformDB
from factorlab.data.verify import compare_sample, verify_all


def _mk_db(path, close_values=None):
    db = PlatformDB(path)
    db.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103", "20240102", "20240103"],
        "ts_code": ["A.SZ", "A.SZ", "B.SZ", "B.SZ"],
        "close": close_values or [10.0, 11.0, 20.0, 21.0],
        "pct_chg": [0.0, 10.0, 0.0, 5.0],
    }), keys=["trade_date", "ts_code"])
    db.upsert("trade_cal", pl.DataFrame({"cal_date": ["20240102", "20240103"], "is_open": [1, 1]}), keys=[])
    return db


def test_verify_all_runs_integrity(tmp_path):
    db = _mk_db(tmp_path / "p.duckdb")
    report = verify_all(db)
    assert "daily" in report["integrity"]
    assert report["sparse_summary"]["daily"] is not None


def test_compare_sample_matches(tmp_path):
    primary = _mk_db(tmp_path / "p.duckdb")
    ref = _mk_db(tmp_path / "r.duckdb")
    report = compare_sample(primary, ref, n_stocks=2, segments=[("20240102", "20240103")], tol=1e-6)
    assert report["compared_rows"] == 4
    assert report["mismatches"] == 0


def test_compare_sample_detects_mismatch(tmp_path):
    primary = _mk_db(tmp_path / "p.duckdb")
    ref = _mk_db(tmp_path / "r.duckdb", close_values=[10.0, 99.0, 20.0, 21.0])
    report = compare_sample(primary, ref, n_stocks=2, segments=[("20240102", "20240103")], tol=1e-6)
    assert report["mismatches"] >= 1
    assert len(report["details"]) >= 1


def test_verify_all_empty_db(tmp_path):
    """空库：完整性规则全 skipped，稀疏摘要为空，不抛错。"""
    report = verify_all(PlatformDB(tmp_path / "empty.duckdb"))
    assert report["integrity"] != {}  # 规则以 skipped 形式逐条列出
    assert all(e["skipped"] for t in report["integrity"].values() for e in t.values())
    assert report["sparse_summary"] == {}
    assert report["compare"] is None


def test_verify_all_ref_missing_skips_compare(tmp_path):
    db = _mk_db(tmp_path / "p.duckdb")
    report = verify_all(db, ref_db=tmp_path / "nope.duckdb")
    assert report["compare"] is None


def test_verify_all_with_ref(tmp_path):
    db = _mk_db(tmp_path / "p.duckdb")
    ref = _mk_db(tmp_path / "r.duckdb")
    report = verify_all(db, ref_db=ref, n_stocks=2)
    assert report["compare"] is not None
    assert report["compare"]["mismatches"] == 0


def test_compare_sample_no_daily_table(tmp_path):
    """primary 无 daily 表：返回零报告 + note，不抛错。"""
    primary = PlatformDB(tmp_path / "p.duckdb")
    primary.upsert("trade_cal", pl.DataFrame({"cal_date": ["20240102"], "is_open": [1]}), keys=[])
    ref = _mk_db(tmp_path / "r.duckdb")
    report = compare_sample(primary, ref, n_stocks=2, segments=[("20240102", "20240103")])
    assert report["compared_rows"] == 0
    assert report["mismatches"] == 0
    assert "note" in report


def test_compare_sample_empty_daily(tmp_path):
    """daily 空表：股票抽样为 0，零报告。"""
    primary = PlatformDB(tmp_path / "p.duckdb")
    primary.upsert("daily", pl.DataFrame({"trade_date": [], "ts_code": [], "close": []}),
                   keys=["trade_date", "ts_code"])
    ref = _mk_db(tmp_path / "r.duckdb")
    report = compare_sample(primary, ref, n_stocks=2, segments=[("20240102", "20240103")])
    assert report["sampled_stocks"] == 0
    assert report["compared_rows"] == 0


def test_compare_sample_n_stocks_exceeds_universe(tmp_path):
    """n_stocks > 库内股票数：抽样全部股票，不抛错。"""
    primary = _mk_db(tmp_path / "p.duckdb")
    ref = _mk_db(tmp_path / "r.duckdb")
    report = compare_sample(primary, ref, n_stocks=10, segments=[("20240102", "20240103")], tol=1e-6)
    assert report["sampled_stocks"] == 2
    assert report["compared_rows"] == 4


def test_compare_sample_ref_missing_raises(tmp_path):
    primary = _mk_db(tmp_path / "p.duckdb")
    with pytest.raises(ValueError, match="参考库不存在"):
        compare_sample(primary, tmp_path / "nope.duckdb", n_stocks=2)


def test_compare_sample_ref_no_daily_skips(tmp_path):
    """参考库无 daily 表：每段捕获 duckdb.Error 跳过，零报告不抛错。"""
    primary = _mk_db(tmp_path / "p.duckdb")
    ref = PlatformDB(tmp_path / "r.duckdb")
    ref.upsert("trade_cal", pl.DataFrame({"cal_date": ["20240102"], "is_open": [1]}), keys=[])
    report = compare_sample(primary, ref, n_stocks=2, segments=[("20240102", "20240103")])
    assert report["compared_rows"] == 0
    assert report["mismatches"] == 0


def test_compare_sample_tol_boundary(tmp_path):
    """容差边界：相对误差 == tol 判为一致，刚超 tol 判为不一致。"""
    primary = _mk_db(tmp_path / "p.duckdb")
    base = [10.0, 11.0, 20.0, 21.0]
    ref_at_tol = _mk_db(tmp_path / "r1.duckdb", close_values=[v * (1 + 1e-6) for v in base])
    report = compare_sample(primary, ref_at_tol, n_stocks=2,
                            segments=[("20240102", "20240103")], tol=1e-6)
    assert report["mismatches"] == 0  # 误差恰在容差上
    ref_over_tol = _mk_db(tmp_path / "r2.duckdb", close_values=[v * (1 + 2e-6) for v in base])
    report = compare_sample(primary, ref_over_tol, n_stocks=2,
                            segments=[("20240102", "20240103")], tol=1e-6)
    assert report["mismatches"] == 4


def test_compare_sample_seed_determinism(tmp_path):
    """同 seed 两次抽样结果一致。"""
    primary = _mk_db(tmp_path / "p.duckdb")
    ref = _mk_db(tmp_path / "r.duckdb", close_values=[10.0, 99.0, 20.0, 21.0])
    a = compare_sample(primary, ref, n_stocks=2, segments=[("20240102", "20240103")], tol=1e-6)
    b = compare_sample(primary, ref, n_stocks=2, segments=[("20240102", "20240103")], tol=1e-6)
    assert a["details"] == b["details"]


def test_compare_sample_null_handling(tmp_path):
    """close 单侧 null 记 mismatch，双侧 null 不算差异。"""
    primary = PlatformDB(tmp_path / "p.duckdb")
    primary.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103", "20240102", "20240103"],
        "ts_code": ["A.SZ", "A.SZ", "B.SZ", "B.SZ"],
        "close": [10.0, 11.0, None, None],  # B 本身停牌无数据
    }), keys=["trade_date", "ts_code"])
    ref = PlatformDB(tmp_path / "r.duckdb")
    ref.upsert("daily", pl.DataFrame({
        "trade_date": ["20240102", "20240103", "20240102", "20240103"],
        "ts_code": ["A.SZ", "A.SZ", "B.SZ", "B.SZ"],
        "close": [10.0, None, None, None],  # A 20240103 单侧 null；B 双侧 null
    }), keys=["trade_date", "ts_code"])
    report = compare_sample(primary, ref, n_stocks=2, segments=[("20240102", "20240103")], tol=1e-6)
    assert report["mismatches"] == 1
    assert report["details"][0]["ts_code"] == "A.SZ"
    assert report["details"][0]["trade_date"] == "20240103"
    assert report["details"][0]["local"] == 11.0
    assert report["details"][0]["ref"] is None
