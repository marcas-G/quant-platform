import datetime

import polars as pl
import pytest

from factorlab.data.adjust import (
    adjustment_sensitivity_check,
    lookahead_check,
    scale_invariance_check,
    view_prices,
)


def _panel():
    return pl.DataFrame({
        "date": [datetime.date(2024, 1, d) for d in (2, 3, 4, 5)] * 2,
        "code": ["A"] * 4 + ["B"] * 4,
        "close": [10.0, 11.0, 8.0, 9.0, 20.0, 22.0, 16.0, 18.0],
        "adj_factor": [1.0, 1.0, 1.5, 1.5] * 2,
    })


def _returns_factor(df):
    """收益率因子（scale-invariant，无未来信息）。"""
    return df.select([
        "date", "code",
        (pl.col("close") / pl.col("close").shift(1) - 1).over("code", order_by="date").alias("signal"),
    ])


def _leaky_factor(df):
    """泄漏因子：用了未来价格（shift(-1)）。"""
    return df.select([
        "date", "code",
        (pl.col("close").shift(-1).over("code", order_by="date") / pl.col("close") - 1).alias("signal"),
    ])


def test_lookahead_check_detects_future_leak():
    report = lookahead_check(_leaky_factor, _panel(), asof=datetime.date(2024, 1, 4))
    assert report.passed is False
    assert report.details["affected_rows"] > 0


def test_lookahead_check_clean_factor_passes():
    report = lookahead_check(_returns_factor, _panel(), asof=datetime.date(2024, 1, 4))
    assert report.passed is True


def test_scale_invariance_returns_factor_passes():
    # 用无除权事件面板：QFQ 退化为常数缩放；跨除权日时朴素收益率在 RAW/QFQ
    # 下天然不同（RAW 除权跳变 vs QFQ 含分红），不属于尺度依赖问题
    flat = _panel().with_columns(pl.lit(1.0).alias("adj_factor"))
    report = scale_invariance_check(_returns_factor, flat)
    assert report.passed is True


def test_scale_invariance_raw_price_factor_fails():
    def raw_price_factor(df):
        return df.select(["date", "code", pl.col("close").alias("signal")])

    report = scale_invariance_check(raw_price_factor, _panel())
    assert report.passed is False
    assert report.details["max_abs_diff"] > 1.0


def test_sensitivity_reports_variation():
    def raw_price_factor(df):
        return df.select(["date", "code", pl.col("close").alias("signal")])

    report = adjustment_sensitivity_check(raw_price_factor, _panel())
    assert report.passed is False  # 视图间变化显著
    assert "max_abs_diff" in report.details


def test_lookahead_asof_before_all_dates_passes():
    # asof 在数据范围之前：截断后无行可对比，不应误报泄漏
    report = lookahead_check(_leaky_factor, _panel(), asof=datetime.date(2023, 12, 31))
    assert report.passed is True
    assert report.details["affected_rows"] == 0


def test_scale_invariance_empty_panel_passes():
    report = scale_invariance_check(_returns_factor, _panel().clear())
    assert report.passed is True
    assert report.details["compared_rows"] == 0


def test_audit_rejects_factor_missing_signal_column():
    def bad_factor(df):
        return df.select(["date", "code", pl.col("close").alias("other")])

    with pytest.raises(ValueError, match="缺少列"):
        lookahead_check(bad_factor, _panel(), asof=datetime.date(2024, 1, 4))
    with pytest.raises(ValueError, match="缺少列"):
        scale_invariance_check(bad_factor, _panel())
    with pytest.raises(ValueError, match="缺少列"):
        adjustment_sensitivity_check(bad_factor, _panel())
