"""M8-01B：Per-Security Quantity Rules——validators + resolver + SecurityQuantityRules。"""

import datetime
from dataclasses import FrozenInstanceError
from pathlib import Path

import duckdb
import polars as pl
import pytest

from factorlab.domain.execution import QuantityRuleKind
from factorlab.execution import (SecurityQuantityRules,
                                 resolve_security_quantity_rules,
                                 is_valid_buy_quantity,
                                 is_valid_sell_quantity)

LOT = QuantityRuleKind.ROUND_LOT_100
STAR = QuantityRuleKind.STAR_MIN_200_STEP_1
BSE = QuantityRuleKind.BSE_MIN_100_STEP_1


# ---------------- QuantityRuleKind ----------------

def test_enum_three_kinds_only():
    assert set(QuantityRuleKind) == {LOT, STAR, BSE}
    assert LOT.value == "round_lot_100"
    assert STAR.value == "star_min_200_step_1"
    assert BSE.value == "bse_min_100_step_1"


def test_invalid_enum_fails():
    with pytest.raises(ValueError):
        QuantityRuleKind("lot100")


# ---------------- ROUND_LOT_100 BUY ----------------

@pytest.mark.parametrize("q,ok", [(0, False), (1, False), (99, False),
                                  (100, True), (101, False), (199, False),
                                  (200, True), (300, True)])
def test_lot_buy(q, ok):
    assert is_valid_buy_quantity(LOT, q) is ok


# ---------------- ROUND_LOT_100 SELL（odd-lot remainder） ----------------

@pytest.mark.parametrize("h,q,ok", [
    (500, 100, True), (500, 200, True), (500, 500, True),
    (500, 50, False), (500, 101, False),
    (299, 99, True), (299, 100, True), (299, 199, True), (299, 200, True),
    (299, 299, True),
    (299, 1, False), (299, 50, False), (299, 101, False), (299, 198, False),
    (99, 99, True), (99, 1, False), (99, 50, False),
])
def test_lot_sell(h, q, ok):
    assert is_valid_sell_quantity(LOT, holding_quantity=h, sell_quantity=q) is ok


# ---------------- STAR BUY ----------------

@pytest.mark.parametrize("q,ok", [(199, False), (200, True), (201, True),
                                  (251, True), (999, True), (1000, True)])
def test_star_buy(q, ok):
    assert is_valid_buy_quantity(STAR, q) is ok


# ---------------- STAR SELL ----------------

@pytest.mark.parametrize("h,q,ok", [
    (500, 200, True), (500, 201, True), (500, 500, True),
    (500, 100, False), (500, 199, False),
    (250, 200, True), (250, 250, True), (250, 50, False),
    (199, 199, True), (199, 100, False), (199, 198, False),
])
def test_star_sell(h, q, ok):
    assert is_valid_sell_quantity(STAR, holding_quantity=h, sell_quantity=q) is ok


# ---------------- BSE BUY ----------------

@pytest.mark.parametrize("q,ok", [(99, False), (100, True), (101, True),
                                  (137, True), (157, True), (1000, True)])
def test_bse_buy(q, ok):
    assert is_valid_buy_quantity(BSE, q) is ok


# ---------------- BSE SELL ----------------

@pytest.mark.parametrize("h,q,ok", [
    (250, 100, True), (250, 101, True), (250, 250, True),
    (250, 50, False), (250, 99, False),
    (80, 80, True), (80, 1, False), (80, 79, False),
])
def test_bse_sell(h, q, ok):
    assert is_valid_sell_quantity(BSE, holding_quantity=h, sell_quantity=q) is ok


# ---------------- invalid quantity types ----------------

@pytest.mark.parametrize("bad", [True, False, 1.0, "100", None])
def test_buy_invalid_types(bad):
    assert is_valid_buy_quantity(LOT, bad) is False


@pytest.mark.parametrize("bad", [True, False, 1.0, "100", None])
def test_sell_invalid_types(bad):
    assert is_valid_sell_quantity(LOT, holding_quantity=100, sell_quantity=bad) is False


def test_sell_holding_invalid_type():
    assert is_valid_sell_quantity(LOT, holding_quantity=1.0, sell_quantity=100) is False


def test_sell_exceeds_holding_fails():
    assert is_valid_sell_quantity(LOT, holding_quantity=100, sell_quantity=200) is False


def test_sell_zero_fails():
    assert is_valid_sell_quantity(LOT, holding_quantity=100, sell_quantity=0) is False


# ---------------- resolver fixture ----------------

def _ref_db(tmp_path, rows):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect(tmp_path / "r.duckdb")
    db.execute("CREATE TABLE stock_basic (symbol VARCHAR, ts_code VARCHAR, market VARCHAR)")
    db.executemany("INSERT INTO stock_basic VALUES (?,?,?)", rows)
    return db


def _rules(db, codes):
    db.close()
    return resolve_security_quantity_rules(tmp_path_of(db), codes)


def tmp_path_of(db):
    return db  # 占位


def test_resolver_exact_rules(tmp_path):
    db = _ref_db(tmp_path, [
        ("600000", "600000.SH", "主板"), ("000001", "000001.SZ", "主板"),
        ("300001", "300001.SZ", "创业板"), ("688001", "688001.SH", "科创板"),
        ("920001", "920001.BJ", "北交所")])
    path = tmp_path / "r.duckdb"
    db.close()
    rules = resolve_security_quantity_rules(path, ["600000.SH", "000001.SZ",
                                                   "300001.SZ", "688001.SH",
                                                   "920001.BJ"])
    f = rules.frame
    assert f.columns == ["code", "market", "rule"]
    assert f["code"].to_list() == ["000001.SZ", "300001.SZ", "600000.SH",
                                   "688001.SH", "920001.BJ"]
    assert f["rule"].to_list() == ["round_lot_100", "round_lot_100",
                                   "round_lot_100", "star_min_200_step_1",
                                   "bse_min_100_step_1"]


def test_resolver_unknown_market_fails(tmp_path):
    db = _ref_db(tmp_path, [("000001", "000001.SZ", "UNKNOWN")])
    path = tmp_path / "r.duckdb"
    db.close()
    with pytest.raises(ValueError, match="market"):
        resolve_security_quantity_rules(path, ["000001.SZ"])


def test_resolver_wrong_suffix_fails(tmp_path):
    """科创板 + .SZ（impossible combination）→ fail（不只按 market 分类）。"""
    db = _ref_db(tmp_path, [("688001", "688001.SZ", "科创板")])
    path = tmp_path / "r.duckdb"
    db.close()
    with pytest.raises(ValueError, match="科创板|suffix|组合"):
        resolve_security_quantity_rules(path, ["688001.SZ"])


def test_resolver_missing_reference_fails(tmp_path):
    db = _ref_db(tmp_path, [("600000", "600000.SH", "主板")])
    path = tmp_path / "r.duckdb"
    db.close()
    with pytest.raises(ValueError, match="缺失|找不到"):
        resolve_security_quantity_rules(path, ["600000.SH", "000001.SZ"])


def test_resolver_duplicate_reference_fails(tmp_path):
    db = _ref_db(tmp_path, [("600000", "600000.SH", "主板"),
                            ("600000", "600000.SH", "主板")])
    path = tmp_path / "r.duckdb"
    db.close()
    with pytest.raises(ValueError, match="重复"):
        resolve_security_quantity_rules(path, ["600000.SH"])


def test_resolver_row_order_invariant(tmp_path):
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    db1 = _ref_db(d1, [("600000", "600000.SH", "主板"), ("000001", "000001.SZ", "主板")])
    p1 = d1 / "r.duckdb"
    db1.close()
    db2 = _ref_db(d2, [("000001", "000001.SZ", "主板"), ("600000", "600000.SH", "主板")])
    p2 = d2 / "r.duckdb"
    db2.close()
    a = resolve_security_quantity_rules(p1, ["600000.SH", "000001.SZ"])
    b = resolve_security_quantity_rules(p2, ["000001.SZ", "600000.SH"])
    assert a.frame.equals(b.frame)


def test_resolver_empty_codes(tmp_path):
    db = _ref_db(tmp_path, [("600000", "600000.SH", "主板")])
    path = tmp_path / "r.duckdb"
    db.close()
    rules = resolve_security_quantity_rules(path, [])
    assert rules.frame.height == 0
    assert rules.frame.schema["code"] == pl.String
    assert rules.frame.schema["market"] == pl.String
    assert rules.frame.schema["rule"] == pl.String


def test_resolver_codes_validation(tmp_path):
    db = _ref_db(tmp_path, [("600000", "600000.SH", "主板")])
    path = tmp_path / "r.duckdb"
    db.close()
    with pytest.raises(ValueError):
        resolve_security_quantity_rules(path, ["600000.SH", "600000.SH"])
    with pytest.raises(ValueError):
        resolve_security_quantity_rules(path, ["600000"])


def test_rules_frozen(tmp_path):
    db = _ref_db(tmp_path, [("600000", "600000.SH", "主板")])
    path = tmp_path / "r.duckdb"
    db.close()
    rules = resolve_security_quantity_rules(path, ["600000.SH"])
    with pytest.raises(FrozenInstanceError):
        rules.frame = pl.DataFrame()


def test_market_non_empty(tmp_path):
    db = _ref_db(tmp_path, [("600000", "600000.SH", "")])
    path = tmp_path / "r.duckdb"
    db.close()
    with pytest.raises(ValueError, match="market"):
        resolve_security_quantity_rules(path, ["600000.SH"])
