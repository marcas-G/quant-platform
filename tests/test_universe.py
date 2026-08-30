import duckdb
import pytest

from factorlab.data.universe import normalize_code, resolve_codes
from factorlab.spec import FactorSpec


def build_db(tmp_path):
    """平台库风格假库：stock_basic（无 exchange 列依赖——交易所由 ts_code 后缀推断）/
    stock_st（无 is_st 列——最新 trade_date 快照的 ts_code 集合即 ST 集合）/daily/trade_cal。"""
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE stock_basic (ts_code VARCHAR, symbol VARCHAR, exchange VARCHAR, list_date VARCHAR, industry VARCHAR, market VARCHAR)")
    db.execute("""INSERT INTO stock_basic VALUES
        ('000001.SZ', '000001', 'SZSE', '19910403', '银行', '主板'),
        ('600519.SH', '600519', 'SSE', '20010827', '白酒', '主板'),
        ('830001.BJ', '830001', 'BSE', '20200101', '其他', '北交所')""")
    db.execute("CREATE TABLE stock_st (ts_code VARCHAR, name VARCHAR, trade_date VARCHAR, type VARCHAR, type_name VARCHAR)")
    # 仅 000001 在最新快照（600519 无 ST 记录）——exclude_st 的 ST 集合 = {000001}
    db.execute("""INSERT INTO stock_st VALUES
        ('000001.SZ', 'ST平安', '20260814', 'ST', '实施风险警示')""")
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
    db.execute("INSERT INTO daily VALUES ('000001.SZ', '20260812', 11.0), ('600519.SH', '20260812', 1410.0)")
    db.execute("CREATE TABLE trade_cal (exchange VARCHAR, cal_date VARCHAR, is_open BIGINT)")
    db.execute("INSERT INTO trade_cal VALUES ('SSE', '20260812', 1), ('SSE', '20260813', 1)")
    return db


@pytest.fixture
def db(tmp_path):
    conn = build_db(tmp_path)
    yield conn
    conn.close()


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
    with pytest.raises(ValueError):
        normalize_code("000001.SZ.X")


def test_normalize_code_rejects_whitespace():
    with pytest.raises(ValueError):
        normalize_code(" 00000 ")


def test_resolve_codes_inline(db):
    spec = spec_with(codes=["000001.SZ", "600519"])
    assert resolve_codes(spec, db) == ["000001", "600519"]


def test_resolve_codes_inline_dedup(db):
    spec = spec_with(codes=["600519.SH", "600519", "000001.SZ"])
    assert resolve_codes(spec, db) == ["000001", "600519"]


def test_resolve_codes_exclude_st_platform_db(db):
    # 平台库 stock_st 无 is_st：最新 trade_date 快照的 ts_code 集合 = ST 集合
    spec = spec_with(rules={"exclude_st": True})
    assert resolve_codes(spec, db) == ["600519"]  # 000001 在 stock_st 最新快照


def test_resolve_codes_exclude_st_latest_snapshot_only(db):
    # 600519 曾有 ST 记录（旧快照）但最新 trade_date 快照无 → 不算 ST，不被排除
    db.execute("INSERT INTO stock_st VALUES ('600519.SH', '贵州茅台', '20260101', 'ST', '实施风险警示')")
    spec = spec_with(rules={"exclude_st": True})
    assert resolve_codes(spec, db) == ["600519"]


def test_resolve_codes_exclude_st_missing_stock_st_table(db):
    # 缺 stock_st 表（如未重建的平台库）：明确报错而非 DuckDB Catalog Error
    db.execute("DROP TABLE stock_st")
    with pytest.raises(ValueError, match="stock_st"):
        resolve_codes(spec_with(rules={"exclude_st": True}), db)


def test_resolve_codes_exchanges_by_suffix(db):
    # 平台库 stock_basic 无 exchange 列：SSE 由 ts_code 后缀 .SH 推断
    spec = spec_with(rules={"exchanges": ["SSE"]})
    assert resolve_codes(spec, db) == ["600519"]


def test_resolve_codes_rejects_bse(db):
    # 含 830001.BJ；BSE 显式拒绝（v1 仅 SSE/SZSE）
    with pytest.raises(ValueError, match="BSE"):
        resolve_codes(spec_with(rules={"exchanges": ["BSE"]}), db)


def test_resolve_codes_exchanges_empty_list(db):
    # 空列表等价于未指定：默认 SSE+SZSE（不含 BSE）
    spec = spec_with(rules={"exchanges": []})
    assert resolve_codes(spec, db) == ["000001", "600519"]


def test_resolve_codes_rules_empty(db):
    spec = spec_with(rules={})
    assert resolve_codes(spec, db) == ["000001", "600519"]


def test_resolve_codes_rules_unknown_key_rejected(db):
    with pytest.raises(ValueError, match="未知 universe 规则"):
        resolve_codes(spec_with(rules={"min_list_day": 100}), db)


def test_resolve_codes_rules_negative_min_list_days_rejected(db):
    with pytest.raises(ValueError, match="min_list_days 不能为负"):
        resolve_codes(spec_with(rules={"min_list_days": -1}), db)


def test_resolve_codes_rules_min_list_days(db):
    # 600519 上市于 2001-08-27；date.start=2026-01-01 时 600519 上市已超 100 天，000001 同理
    spec = spec_with(rules={"min_list_days": 100})
    spec.date.start = "2026-01-01"
    assert resolve_codes(spec, db) == ["000001", "600519"]


def test_resolve_codes_rules_min_list_days_filters_young(db):
    # 600519 上市于 2001-08-27：距 2002-01-01 不足 365 天 → 被过滤；000001 上市于 1991 → 保留
    spec = spec_with(rules={"min_list_days": 365})
    spec.date.start = "2002-01-01"
    assert resolve_codes(spec, db) == ["000001"]


def test_resolve_codes_rules_min_list_days_from_daily(db):
    # 不设 date.start → 回退到 daily 最早 trade_date（平台库 'YYYYMMDD'）；600519 上市晚于该日期 → 被过滤
    db.execute("INSERT INTO daily VALUES ('000001.SZ', '20000104', 10.0)")
    spec = spec_with(rules={"min_list_days": 100})
    assert resolve_codes(spec, db) == ["000001"]


def test_resolve_codes_min_list_days_no_date_source_raises(db):
    # date.start 未设置且 daily 为空 → 无基准日期，明确报错
    db.execute("DELETE FROM daily")
    with pytest.raises(ValueError, match="date.start"):
        resolve_codes(spec_with(rules={"min_list_days": 100}), db)


def test_resolve_codes_empty_result_error(db):
    with pytest.raises(ValueError, match="universe 无有效股票"):
        resolve_codes(spec_with(codes=["999999.SZ"]), db)


def test_resolve_codes_reference_file(db, tmp_path):
    uni_dir = tmp_path / "universes"
    uni_dir.mkdir()
    (uni_dir / "research_50.yaml").write_text("codes: ['000001.SZ']", encoding="utf-8")
    from factorlab.config import Settings
    settings = Settings(universes_dir=uni_dir)
    spec = spec_with(ref="research_50")
    assert resolve_codes(spec, db, settings=settings) == ["000001"]


def test_resolve_codes_reference_file_missing_keys(db, tmp_path):
    uni_dir = tmp_path / "universes"
    uni_dir.mkdir()
    (uni_dir / "empty.yaml").write_text("{}", encoding="utf-8")
    from factorlab.config import Settings
    settings = Settings(universes_dir=uni_dir)
    with pytest.raises(ValueError, match="必须包含 codes 或 rules"):
        resolve_codes(spec_with(ref="empty"), db, settings=settings)


def test_resolve_codes_override_beats_spec(db):
    spec = spec_with(codes=["000001.SZ"])
    assert resolve_codes(spec, db, override="600519") == ["600519"]


def test_resolve_codes_override_file_path(db, tmp_path):
    pool = tmp_path / "my_pool.yaml"
    pool.write_text("codes: ['600519']", encoding="utf-8")
    spec = spec_with(codes=["000001.SZ"])
    assert resolve_codes(spec, db, override=str(pool)) == ["600519"]


def test_resolve_codes_missing_reference_file(db, tmp_path):
    from factorlab.config import Settings
    settings = Settings(universes_dir=tmp_path / "nope")
    with pytest.raises(FileNotFoundError):
        resolve_codes(spec_with(ref="ghost"), db, settings=settings)


# ================================================================
# M6-07B4：rules universe 排除 legacy vendor aliases（T/TS 前缀历史残留）
# ================================================================

from factorlab.data.universe import resolve_candidate_codes


def _build_db_with_aliases(tmp_path):
    """stock_basic 含 canonical 600018.SH + legacy aliases T600018.SH/TS0018.SH。"""
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE stock_basic (ts_code VARCHAR, symbol VARCHAR, exchange VARCHAR, list_date VARCHAR, industry VARCHAR, market VARCHAR)")
    db.execute("""INSERT INTO stock_basic VALUES
        ('000001.SZ', '000001', 'SZSE', '19910403', '银行', '主板'),
        ('600018.SH', '600018', 'SSE', '20061026', '港口', '主板'),
        ('T600018.SH', 'T600018', 'SSE', '20000719', '港口', '主板'),
        ('TS0018.SH', 'TS0018', 'SSE', '20000719', '港口', '主板')""")
    return db


@pytest.fixture
def db_alias(tmp_path):
    conn = _build_db_with_aliases(tmp_path)
    yield conn
    conn.close()


def test_resolve_codes_rules_excludes_legacy_aliases(db_alias):
    spec = spec_with(rules={})
    assert resolve_codes(spec, db_alias) == ["000001", "600018"]


def test_resolve_candidate_codes_rules_excludes_legacy_aliases(db_alias):
    spec = spec_with(rules={"exchanges": ["SSE", "SZSE"]})
    assert resolve_candidate_codes(spec, db_alias) == ["000001", "600018"]


def test_resolve_codes_exchanges_by_suffix_excludes_aliases(db_alias):
    spec = spec_with(rules={"exchanges": ["SSE"]})
    assert resolve_codes(spec, db_alias) == ["600018"]
