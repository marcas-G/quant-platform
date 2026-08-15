import datetime

import polars as pl
import pytest

from factorlab.data.adjust import view_prices, total_return


def _panel():
    # 第 3 日 10 送 5（adj 1.0→1.5）；raw close 除权跳变
    return pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3), datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)],
        "code": ["A", "A", "A", "A"],
        "close": [10.0, 11.0, 8.0, 9.0],
        "adj_factor": [1.0, 1.0, 1.5, 1.5],
    })


def test_view_raw_unchanged():
    out = view_prices(_panel(), "raw")
    assert out["close"].to_list() == [10.0, 11.0, 8.0, 9.0]


def test_view_qfq_scales_by_latest_factor():
    out = view_prices(_panel(), "qfq")
    # factor = adj / adj[latest] = [1/1.5, 1/1.5, 1, 1]
    assert out["close"].to_list() == pytest.approx([10.0 / 1.5, 11.0 / 1.5, 8.0, 9.0])


def test_view_hfq_multiplies_by_factor():
    out = view_prices(_panel(), "hfq")
    assert out["close"].to_list() == pytest.approx([10.0, 11.0, 12.0, 13.5])


def test_view_pit_qfq_uses_asof_factor():
    out = view_prices(_panel(), "pit_qfq", asof=datetime.date(2024, 1, 3))
    # factor = adj / adj[asof=1.0] = [1, 1, 1.5, 1.5]
    assert out["close"].to_list() == pytest.approx([10.0, 11.0, 12.0, 13.5])


def test_view_pit_qfq_requires_asof():
    with pytest.raises(ValueError, match="asof"):
        view_prices(_panel(), "pit_qfq")


def test_view_qfq_uses_date_order_not_row_order():
    df = _panel().sort("date", descending=True)  # 打乱行序
    out = view_prices(df, "qfq")
    assert out["close"].to_list() == pytest.approx([10.0 / 1.5, 11.0 / 1.5, 8.0, 9.0])


def test_view_qfq_groups_by_code():
    # 多 code：不同复权因子不能跨 code 混用（A 1→1.5，B 2→3）
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3), datetime.date(2024, 1, 4)] * 2,
        "code": ["A"] * 3 + ["B"] * 3,
        "close": [10.0, 11.0, 8.0] * 2,
        "adj_factor": [1.0, 1.0, 1.5, 2.0, 2.0, 3.0],
    })
    out = view_prices(df, "qfq")
    assert out["close"].to_list() == pytest.approx(
        [10.0 / 1.5, 11.0 / 1.5, 8.0, 10.0 * 2 / 3, 11.0 * 2 / 3, 8.0])


def test_total_return_grouped_via_over():
    # 多 code 组内平移：调用方对整体 Expr 包 .over("code", order_by="date")
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3), datetime.date(2024, 1, 4)] * 2,
        "code": ["A"] * 3 + ["B"] * 3,
        "close": [10.0, 11.0, 8.0] * 2,
        "adj_factor": [1.0, 1.0, 1.5, 2.0, 2.0, 3.0],
    })
    out = df.with_columns(
        total_return(pl.col("close"), pl.col("adj_factor"))
        .over("code", order_by="date")
        .alias("tr"))
    # A: hfq=[10,11,12]→[null,0.1,12/11-1]；B: hfq=[20,22,24]→[null,0.1,24/22-1]（不跨 code 泄漏）
    assert out["tr"].to_list() == pytest.approx(
        [None, 0.1, 12.0 / 11.0 - 1, None, 0.1, 24.0 / 22.0 - 1], nan_ok=True)


def test_view_unknown_raises():
    with pytest.raises(ValueError, match="view"):
        view_prices(_panel(), "bogus")


def test_total_return_includes_dividend():
    df = _panel()
    out = df.with_columns(total_return(pl.col("close"), pl.col("adj_factor")).alias("tr"))
    # tr[t] = close[t]*adj[t] / (close[t-1]*adj[t-1]) - 1（组内，首行 null）
    assert out["tr"].to_list()[:1] == [None]
    assert out["tr"].to_list()[1:] == pytest.approx([0.1, 12.0 / 11.0 - 1, 13.5 / 12.0 - 1])
