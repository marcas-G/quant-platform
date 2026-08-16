import datetime

import polars as pl
import pytest

from factorlab.eval.alignment import align_weekly
from factorlab.eval.metrics import coverage_report


def test_align_weekly_last_trading_day():
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3), datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)],
        "code": ["A"] * 4,
        "signal": [1.0, 2.0, 3.0, 4.0],
    })
    out = align_weekly(df)
    assert out["date"].to_list() == [datetime.date(2024, 1, 5)]  # 周五为该周最后交易日
    assert out["signal"].to_list() == [4.0]


def test_align_weekly_cross_year_iso_week():
    # 2021-01-01 与 2020-12-31 同属 ISO 2020-W53 → 合并为该周最后交易日 2021-01-01
    df = pl.DataFrame({
        "date": [datetime.date(2020, 12, 31), datetime.date(2021, 1, 1)],
        "code": ["A", "A"],
        "signal": [1.0, 2.0],
    })
    out = align_weekly(df)
    assert out.height == 1
    assert out["date"].to_list() == [datetime.date(2021, 1, 1)]


def test_align_weekly_full_year_keeps_first_bar():
    # 回归：组合键 (日历年, ISO 周号) 会让周号 1 在一年内出现两次——2024-12-30/31
    # 属于 ISO 2025-W1 但日历年为 2024，与 2024-01-02..05 同组后首个周频 bar
    # （2024-01-05）被 12-31 顶掉；ISO 分组下两者不同组，且 12-30/31 与 2025-01-02/03
    # 同属 ISO 2025-W1，合并为该周最后交易日 2025-01-03
    dates = [datetime.date(2024, 1, d) for d in (2, 3, 4, 5)]
    dates += [datetime.date(2024, 12, 30), datetime.date(2024, 12, 31)]
    dates += [datetime.date(2025, 1, 2), datetime.date(2025, 1, 3)]
    df = pl.DataFrame({"date": dates, "code": ["A"] * len(dates), "signal": [1.0] * len(dates)})
    out = align_weekly(df)
    bars = out["date"].to_list()
    assert datetime.date(2024, 1, 5) in bars          # 2024 首个周频 bar 保留
    assert datetime.date(2025, 1, 3) in bars          # ISO 2025-W1（含 2024-12-30/31）最后交易日
    assert datetime.date(2024, 12, 31) not in bars    # 与 2025-01-02/03 同周，不单独成 bar


def test_align_weekly_per_code_no_leak():
    # A、B 同处 2024 年第 1 周：分组若忽略 code 会把整组周末取为 1/5，丢弃 A 的观测
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
                 datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)],
        "code": ["A", "A", "B", "B"],
        "signal": [1.0, 3.0, 4.0, 5.0],
    })
    out = align_weekly(df).sort(["code", "date"])
    assert out["code"].to_list() == ["A", "B"]
    assert out["date"].to_list() == [datetime.date(2024, 1, 3), datetime.date(2024, 1, 5)]
    assert out["signal"].to_list() == [3.0, 5.0]


def test_align_weekly_empty_panel():
    df = pl.DataFrame(schema={"date": pl.Date, "code": pl.String, "signal": pl.Float64})
    out = align_weekly(df)
    assert out.height == 0
    assert out.columns == ["date", "code", "signal"]


def test_align_weekly_rejects_non_date_dtype():
    # date 非 pl.Date 时 dt 周运算应显式报错，而不是静默错位
    df = pl.DataFrame({
        "date": ["2020-12-31", "2021-01-01"],
        "code": ["A", "A"],
        "signal": [1.0, 2.0],
    })
    with pytest.raises(pl.exceptions.InvalidOperationError):
        align_weekly(df)


def test_coverage_report():
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5), datetime.date(2024, 1, 5), datetime.date(2024, 1, 12)],
        "code": ["A", "B", "A"],
        "signal": [1.0, None, 2.0],
    })
    report = coverage_report(df)
    # pct_valid 保留 4 位小数（round(2/3, 4) = 0.6667），与 2/3 相差 3.3e-5
    assert report["pct_valid"] == pytest.approx(2 / 3, abs=1e-3)
    assert report["stocks"] == 2
    assert report["weeks"] == 2


def test_coverage_report_empty():
    report = coverage_report(pl.DataFrame({"date": [], "code": [], "signal": []}))
    assert report["pct_valid"] == 0.0
