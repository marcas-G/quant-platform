import duckdb
import pytest

from factorlab.data.universe import normalize_code, resolve_codes
from factorlab.spec import FactorSpec


def build_db(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE stock_basic_tushare (symbol VARCHAR, ts_code VARCHAR, exchange VARCHAR, list_date VARCHAR, industry VARCHAR)")
    db.execute("""INSERT INTO stock_basic_tushare VALUES
        ('000001', '000001.SZ', 'SZSE', '1991-04-03', '银行'),
        ('600519', '600519.SH', 'SSE', '2001-08-27', '白酒'),
        ('830001', '830001.BJ', 'BSE', '2020-01-01', '其他')""")
    db.execute("CREATE TABLE st_status (code VARCHAR, date DATE, is_st BOOLEAN)")
    db.execute("""INSERT INTO st_status VALUES
        ('000001', DATE '2026-01-05', FALSE),
        ('000001', DATE '2026-03-10', TRUE),
        ('600519', DATE '2026-03-10', FALSE)""")
    db.execute("CREATE TABLE daily (date VARCHAR, code VARCHAR, close DOUBLE)")
    return db


def spec_with(**universe_kwargs):
    return FactorSpec.model_validate({
        "name": "demo", "category": "custom", "direction": 1,
        "universe": universe_kwargs, "formula": "signal = close",
    })


def test_normalize_code():
    assert normalize_code("000001.SZ") == "000001"
    assert normalize_code("600519") == "600519"
    with pytest.raises(ValueError):
        normalize_code("abc")


def test_resolve_codes_inline(tmp_path):
    db = build_db(tmp_path)
    spec = spec_with(codes=["000001.SZ", "600519"])
    assert resolve_codes(spec, db) == ["000001", "600519"]


def test_resolve_codes_rules_exclude_st(tmp_path):
    db = build_db(tmp_path)
    spec = spec_with(rules={"exclude_st": True})
    assert resolve_codes(spec, db) == ["600519"]  # 000001 最新 st 标记为 TRUE


def test_resolve_codes_rules_exchanges_rejects_bse(tmp_path):
    db = build_db(tmp_path)
    with pytest.raises(ValueError, match="BSE"):
        resolve_codes(spec_with(rules={"exchanges": ["BSE"]}), db)


def test_resolve_codes_reference_file(tmp_path, monkeypatch):
    db = build_db(tmp_path)
    uni_dir = tmp_path / "universes"
    uni_dir.mkdir()
    (uni_dir / "research_50.yaml").write_text("codes: ['000001.SZ']", encoding="utf-8")
    from factorlab.config import Settings
    settings = Settings(universes_dir=uni_dir)
    spec = spec_with(ref="research_50")
    assert resolve_codes(spec, db, settings=settings) == ["000001"]


def test_resolve_codes_override_beats_spec(tmp_path):
    db = build_db(tmp_path)
    spec = spec_with(codes=["000001.SZ"])
    assert resolve_codes(spec, db, override="600519") == ["600519"]


def test_resolve_codes_missing_reference_file(tmp_path):
    db = build_db(tmp_path)
    from factorlab.config import Settings
    settings = Settings(universes_dir=tmp_path / "nope")
    with pytest.raises(FileNotFoundError):
        resolve_codes(spec_with(ref="ghost"), db, settings=settings)


def test_resolve_codes_rules_min_list_days(tmp_path):
    db = build_db(tmp_path)
    # 600519 上市于 2001-08-27；date.start=2026-01-01 时 600519 上市已超 100 天，000001 同理
    spec = spec_with(rules={"min_list_days": 100})
    spec.date.start = "2026-01-01"
    assert resolve_codes(spec, db) == ["000001", "600519"]


def test_resolve_codes_rules_min_list_days_filters_young(tmp_path):
    db = build_db(tmp_path)
    # 600519 上市于 2001-08-27：距 2002-01-01 不足 365 天 → 被过滤；000001 上市于 1991 → 保留
    spec = spec_with(rules={"min_list_days": 365})
    spec.date.start = "2002-01-01"
    assert resolve_codes(spec, db) == ["000001"]
