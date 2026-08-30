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


def test_view_qfq_skips_null_adj_suspension_rows():
    # 回归：fill_suspensions 补全的停牌行 adj 为 null——latest 若把 null 当最后值
    # 则整组 None（窗口末行停牌即触发）；latest 应跳过 null
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
                 datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)],
        "code": ["A"] * 4,
        "close": [10.0, 11.0, 12.0, None],
        "adj_factor": [1.0, 1.0, 1.5, None],
    })
    out = view_prices(df, "qfq")
    # latest = 1.5（末行 null 跳过）；停牌行价格 null
    assert out["close"].to_list() == pytest.approx([10.0 / 1.5, 11.0 / 1.5, 12.0, None], nan_ok=True)


def test_view_pit_qfq_skips_null_adj_asof_row():
    # 回归：asof 当日补全行 adj 为 null——asof 基准取截至日的最近非 null adj
    df = pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
                 datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)],
        "code": ["A"] * 4,
        "close": [10.0, 11.0, None, 13.0],
        "adj_factor": [1.0, 1.0, None, 1.5],
    })
    out = view_prices(df, "pit_qfq", asof=datetime.date(2024, 1, 4))
    # 截止 01-04 的最近非 null adj = 1.0（01-04 补全行 null 跳过）
    assert out["close"].to_list() == pytest.approx([10.0, 11.0, None, 19.5], nan_ok=True)


def test_view_unknown_raises():
    with pytest.raises(ValueError, match="view"):
        view_prices(_panel(), "bogus")


def test_total_return_includes_dividend():
    df = _panel()
    out = df.with_columns(total_return(pl.col("close"), pl.col("adj_factor")).alias("tr"))
    # tr[t] = close[t]*adj[t] / (close[t-1]*adj[t-1]) - 1（组内，首行 null）
    assert out["tr"].to_list()[:1] == [None]
    assert out["tr"].to_list()[1:] == pytest.approx([0.1, 12.0 / 11.0 - 1, 13.5 / 12.0 - 1])


# ================================================================
# M6-07C2E：view_prices qfq fixed-base（qfq_base_col 参数）
# ================================================================

def _panel_with_base():
    """带固定 base 列的 panel（runtime 传入）。"""
    return pl.DataFrame({
        "date": [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3),
                 datetime.date(2024, 1, 4), datetime.date(2024, 1, 5)],
        "code": ["A", "A", "A", "A"],
        "close": [10.0, 11.0, 8.0, 9.0],
        "adj_factor": [1.0, 1.0, 1.5, 1.5],
        "__factorlab_qfq_base_adj": [1.5, 1.5, 1.5, 1.5],
    })


def test_view_qfq_fixed_base_column():
    """qfq_base_col 非 None → factor = adj / base（不再计算块内 latest）。"""
    out = view_prices(_panel_with_base(), "qfq",
                      qfq_base_col="__factorlab_qfq_base_adj")
    assert out["close"].to_list() == pytest.approx([10.0 / 1.5, 11.0 / 1.5, 8.0, 9.0])


def test_view_qfq_fixed_base_differs_from_latest():
    """固定 base ≠ 块内 latest 时必须用固定 base。"""
    df = _panel_with_base().with_columns(pl.lit(1.0).alias("__factorlab_qfq_base_adj"))
    out = view_prices(df, "qfq", qfq_base_col="__factorlab_qfq_base_adj")
    # factor = adj/1.0 = [1,1,1.5,1.5]——若错误用 latest（1.5）则 [1/1.5,1/1.5,1,1]
    assert out["close"].to_list() == pytest.approx([10.0, 11.0, 12.0, 13.5])


def test_view_qfq_fixed_base_null_tail():
    """adj_factor 行内 null：factor=adj/base 逐行语义（null 行 close null）——
    base 列自身的 non-null 由 _load_base_adj 的 FILTER 保证（§23，run_factor 级
    测试覆盖）。"""
    df = _panel_with_base().with_columns(
        pl.col("adj_factor").replace([1.5], [None]))
    out = view_prices(df, "qfq", qfq_base_col="__factorlab_qfq_base_adj")
    assert out["close"].to_list() == pytest.approx([10.0 / 1.5, 11.0 / 1.5, None, None])


def test_view_qfq_default_contract_unchanged():
    """默认调用（无 qfq_base_col）保持 standalone latest 语义（§6）。"""
    out = view_prices(_panel(), "qfq")
    assert out["close"].to_list() == pytest.approx([10.0 / 1.5, 11.0 / 1.5, 8.0, 9.0])


def test_view_hfq_and_pit_unchanged_with_base_param():
    """hfq/pit_qfq 忽略 qfq_base_col（不破坏）。"""
    df = _panel_with_base()
    out = view_prices(df, "hfq", qfq_base_col="__factorlab_qfq_base_adj")
    assert out["close"].to_list() == pytest.approx([10.0, 11.0, 12.0, 13.5])
    out = view_prices(df, "pit_qfq", asof=datetime.date(2024, 1, 3),
                      qfq_base_col="__factorlab_qfq_base_adj")
    assert out["close"].to_list() == pytest.approx([10.0, 11.0, 12.0, 13.5])
