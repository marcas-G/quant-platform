import datetime

import polars as pl
import pytest

from factorlab.engine.forward import align_weekly, compute_forward_returns


def _panel():
    return pl.DataFrame({
        "date": [datetime.date(2024, 1, d) for d in (2, 3, 4, 5)] * 2,
        "code": ["A"] * 4 + ["B"] * 4,
        "close": [10.0, 11.0, 12.0, 13.0, 20.0, 22.0, 24.0, 26.0],
        "adj_factor": [1.0] * 8,
    })


def test_forward_returns_5d():
    df = _panel()
    out = compute_forward_returns(df, horizons=(5,))
    assert "forward_return_5d" in out.columns
    assert out["forward_return_5d"][0] is None  # 仅 4 天，无第 5 交易日


def test_forward_returns_value():
    # spec 2.5：forward_return_h = close[t+h]/close[t] - 1，h 为补全后序列的索引差。
    # t+5 为 1/2 往后第 5 个交易日 = 1/9；5 行面板内 row0 无 t+5 → None
    df = _panel()
    df = df.vstack(pl.DataFrame({
        "date": [datetime.date(2024, 1, 8), datetime.date(2024, 1, 8),
                 datetime.date(2024, 1, 9), datetime.date(2024, 1, 9)],
        "code": ["A", "B", "A", "B"],
        "close": [15.0, 30.0, 18.0, 36.0],
        "adj_factor": [1.0, 1.0, 1.0, 1.0],
    }))
    out = compute_forward_returns(df, horizons=(5,))
    a = out.filter(pl.col("code") == "A").sort("date")
    b = out.filter(pl.col("code") == "B").sort("date")
    assert a["forward_return_5d"][0] == 18.0 / 10.0 - 1  # close[1/9]/close[1/2] - 1
    assert b["forward_return_5d"][0] == 36.0 / 20.0 - 1  # 组内对齐，B 不借用 A 的数据
    assert a["forward_return_5d"][-1] is None
    assert b["forward_return_5d"][-1] is None


def test_forward_returns_float32_precision():
    # Task 4 输出 close 为 float32：比值 18/10-1 在 float32 下精确，且输出保持 float32
    df = _panel().with_columns(pl.col("close").cast(pl.Float32), pl.col("adj_factor").cast(pl.Float32))
    df = df.vstack(pl.DataFrame({
        "date": [datetime.date(2024, 1, 8), datetime.date(2024, 1, 8),
                 datetime.date(2024, 1, 9), datetime.date(2024, 1, 9)],
        "code": ["A", "B", "A", "B"],
        "close": [15.0, 30.0, 18.0, 36.0],
        "adj_factor": [1.0, 1.0, 1.0, 1.0],
    }).with_columns(pl.col("close").cast(pl.Float32), pl.col("adj_factor").cast(pl.Float32)))
    out = compute_forward_returns(df, horizons=(5,))
    assert out["forward_return_5d"].dtype == pl.Float32
    a = out.filter(pl.col("code") == "A").sort("date")
    # 0.8 在 float32 下不可精确表示（0.79999995…），用 approx
    assert a["forward_return_5d"][0] == pytest.approx(18.0 / 10.0 - 1)


def test_forward_returns_default_horizons():
    df = _panel()
    out = compute_forward_returns(df)
    assert out.columns == ["date", "code", "close", "adj_factor", "forward_return_5d", "forward_return_20d"]
    assert out["forward_return_20d"].null_count() == out.height  # 仅 4 天，20 日全部缺失


def test_forward_returns_custom_close_col():
    out = compute_forward_returns(_panel().rename({"close": "adj_close"}), horizons=(5,), close_col="adj_close")
    assert "forward_return_5d" in out.columns
    assert out["forward_return_5d"][0] is None


def test_forward_returns_rejects_non_positive_horizon():
    df = _panel()
    for bad in (0, -1):
        with pytest.raises(ValueError, match="horizon"):
            compute_forward_returns(df, horizons=(bad,))


def test_forward_returns_empty_panel():
    df = pl.DataFrame(schema={"date": pl.Date, "code": pl.String, "close": pl.Float64, "adj_factor": pl.Float64})
    out = compute_forward_returns(df)
    assert out.height == 0
    assert "forward_return_5d" in out.columns


def test_forward_returns_total_return_semantics():
    # total_return 口径：close[t+h]×adj[t+h] / (close[t]×adj[t]) - 1（含分红再投资）
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3), datetime.date(2024, 1, 4),
                 datetime.date(2024, 1, 5), datetime.date(2024, 1, 8)],
        "code": ["A"] * 5,
        "close": [10.0, 11.0, 8.0, 9.0, 12.0],
        "adj_factor": [1.0, 1.0, 1.5, 1.5, 1.5],
    })
    out = compute_forward_returns(df, horizons=(4,))
    # close[1/8]×adj[1/8] / (close[1/2]×adj[1/2]) - 1 = 12×1.5/10 - 1 = 0.8
    # （raw close 口径会是 12/10 - 1 = 0.2——除权日假崩被 adj 修正）
    assert out["forward_return_4d"][0] == 0.8


def test_forward_returns_total_return_custom_adj_col():
    df = _panel().rename({"adj_factor": "adj"})
    out = compute_forward_returns(df, horizons=(5,), adj_col="adj")
    assert "forward_return_5d" in out.columns


def test_forward_returns_missing_adj_col_raises():
    # total_return 需要 adj_factor：缺列时显式报错（而非 polars ColumnNotFoundError）
    df = _panel().drop("adj_factor")
    with pytest.raises(ValueError, match="adj_factor"):
        compute_forward_returns(df, horizons=(5,))


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
