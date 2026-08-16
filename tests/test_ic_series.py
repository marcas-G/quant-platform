import datetime

import polars as pl
import pytest

from factorlab.eval.ic_series import weekly_ic


def _panel(weeks=4, stocks=10, seed=1):
    import random
    rng = random.Random(seed)
    rows = []
    for w in range(weeks):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for s in range(stocks):
            signal = s / stocks + rng.uniform(-0.05, 0.05)
            rows.append({"date": d, "code": f"{s:06d}",
                         "signal": signal, "forward_return_5d": signal * 0.1 + rng.uniform(-0.01, 0.01)})
    return pl.DataFrame(rows)


def test_weekly_ic_structure():
    result = weekly_ic(_panel())
    assert result.columns == ["date", "ic"]
    assert result.height == 4  # 每周一点
    assert result["ic"].null_count() == 0


def test_weekly_ic_positive_correlation():
    # signal 与 forward 正相关构造 → ic 应为正
    result = weekly_ic(_panel())
    assert result["ic"].mean() > 0


def test_weekly_ic_exact_rank_correlation():
    # 手工推演：signal = [1,2,3,4], forward = [0.1,0.2,0.3,0.4]（完全单调）→ ic = 1.0
    panel = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5)] * 4,
        "code": ["a", "b", "c", "d"],
        "signal": [1.0, 2.0, 3.0, 4.0],
        "forward_return_5d": [0.1, 0.2, 0.3, 0.4],
    })
    result = weekly_ic(panel)
    assert result["ic"][0] == pytest.approx(1.0)


def test_weekly_ic_insufficient_stocks_null():
    # 单期只有 2 只 → 秩相关不稳健 → null
    panel = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5)] * 2,
        "code": ["a", "b"],
        "signal": [1.0, 2.0],
        "forward_return_5d": [0.1, 0.2],
    })
    result = weekly_ic(panel)
    assert result["ic"][0] is None


def test_weekly_ic_excludes_null_rows():
    # 某行 signal null → 排除（不影响其余）
    panel = _panel(weeks=1, stocks=10)
    panel = panel.with_columns(pl.when(pl.col("code") == "000000").then(None).otherwise(pl.col("signal")).alias("signal"))
    result = weekly_ic(panel)
    assert result["ic"].null_count() == 0


def test_weekly_ic_week_all_null():
    # 某周 signal 全 null → 有效股票 0（< MIN_STOCKS）→ 该周保留、ic = null
    dates = [datetime.date(2024, 1, 5), datetime.date(2024, 1, 12)]
    rows = []
    for d in dates:
        for s in range(5):
            rows.append({"date": d, "code": f"{s:06d}",
                         "signal": float(s), "forward_return_5d": 0.01})
    panel = pl.DataFrame(rows).with_columns(
        pl.when(pl.col("date") == dates[0]).then(None).otherwise(pl.col("signal")).alias("signal")
    )
    result = weekly_ic(panel)
    assert result.height == 2  # 周仍保留在序列中
    assert result["ic"].is_null().sum() == 1
    assert result.filter(pl.col("date") == dates[1])["ic"][0] is not None


def test_weekly_ic_rank_ties():
    # 平局用 average rank：signal = [1,1,2,2], forward = [1,2,1,2] → 秩相关 = 0
    panel = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5)] * 4,
        "code": ["a", "b", "c", "d"],
        "signal": [1.0, 1.0, 2.0, 2.0],
        "forward_return_5d": [1.0, 2.0, 1.0, 2.0],
    })
    result = weekly_ic(panel)
    assert result["ic"][0] == pytest.approx(0.0)


def test_weekly_ic_empty_panel():
    # 空面板（列齐全）→ 空序列
    panel = pl.DataFrame(schema={
        "date": pl.Date, "code": pl.String, "signal": pl.Float64, "forward_return_5d": pl.Float64,
    })
    result = weekly_ic(panel)
    assert result.columns == ["date", "ic"]
    assert result.height == 0


def test_weekly_ic_missing_target_column():
    # 缺列（target 缺失）→ ValueError（不依赖 polars 的内部异常）
    with pytest.raises(ValueError, match="缺少列"):
        weekly_ic(_panel().drop("forward_return_5d"))
