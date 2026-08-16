import datetime

import polars as pl
import pytest

from factorlab.eval.layered import layered_backtest


def _weekly_panel(weeks=4, stocks=10, wiggle=0.0):
    """构造周频面板：每周 stocks 只，signal 单调（0.1-1.0），forward 与 signal 正相关。

    wiggle>0 时周收益加确定性周间偏移 ((w+1)*wiggle，无 rng)：常值序列的 std=0
    （vol=0，sharpe 恒等式退化），摘要指标测试用它保证 vol>0。
    """
    rows = []
    for w in range(weeks):
        d = datetime.date(2024, 1, 5) + datetime.timedelta(weeks=w)
        for s in range(stocks):
            signal = (s + 1) / stocks
            rows.append({"date": d, "code": f"{s:06d}",
                         "signal": signal, "forward_return_5d": signal * 0.1 + (w + 1) * wiggle})
    return pl.DataFrame(rows)


def test_layered_backtest_structure():
    result = layered_backtest(_weekly_panel(), direction=1)
    assert result["n_groups"] == 10
    assert result["periods"] == 4
    assert set(result["net_values"]) >= {f"D{i}" for i in range(1, 11)} | {"long_short"}
    assert len(result["net_values"]["D1"]) == 4  # 每期一点
    assert len(result["dates"]) == 4
    assert "D1" in result["summary"] and "long_short" in result["summary"]


def test_layered_backtest_direction_flips_groups():
    up = layered_backtest(_weekly_panel(), direction=1)
    down = layered_backtest(_weekly_panel(), direction=-1)
    # direction=-1 时原 D1（最高 signal）成为最差档——净值应互换
    assert up["net_values"]["D1"][-1] == down["net_values"]["D10"][-1]
    assert up["net_values"]["D10"][-1] == down["net_values"]["D1"][-1]


def test_layered_backtest_net_value_math():
    # 单期单档：D1（最高 signal）档的 forward 等权平均 → 净值
    panel = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5), datetime.date(2024, 1, 5)],
        "code": ["000001", "000002"],
        "signal": [1.0, 0.9],  # 2 只，n_groups=2 → 各 1 只
        "forward_return_5d": [0.02, 0.01],
    })
    result = layered_backtest(panel, direction=1, n_groups=2)
    assert result["net_values"]["D1"][-1] == 1.02  # 最高档 = signal 1.0 → ret 0.02
    assert result["net_values"]["D2"][-1] == 1.01


def test_layered_backtest_long_short():
    panel = _weekly_panel(weeks=2)
    result = layered_backtest(panel, direction=1)
    # long-short = D1 - D10 逐期差值序列（净值序列"每期一点"、无首期 1.0 起点，
    # 故 long_short[0] = D1[0]-D10[0]，不恒为 0——计划草稿的 0.0 断言与其自身
    # "差值序列"语义冲突，这里改为逐期差断言）
    assert result["net_values"]["long_short"][0] == pytest.approx(
        result["net_values"]["D1"][0] - result["net_values"]["D10"][0])
    assert result["net_values"]["long_short"][-1] == pytest.approx(
        result["net_values"]["D1"][-1] - result["net_values"]["D10"][-1])


def test_layered_backtest_summary_metrics():
    # 计划原稿 `_weekly_panel(weeks=52)` 的 D1 周收益恒为 0.1（std=0 → vol=0，
    # sharpe 恒等式 5.2/0.0 在测试内除零）——wiggle 加确定性周间波动使 vol>0。
    # 摘要值 round(...,6) 引入 ~1e-6 相对舍入误差，恒等式断言用 rel=1e-3。
    result = layered_backtest(_weekly_panel(weeks=52, wiggle=0.001), direction=1)
    s = result["summary"]["D1"]
    assert set(s) >= {"annual_return", "annual_vol", "sharpe", "max_drawdown", "win_rate"}
    assert s["annual_return"] > 0  # D1 正收益（forward 正相关）
    assert s["sharpe"] == pytest.approx(s["annual_return"] / s["annual_vol"], rel=1e-3)


def test_layered_backtest_empty_panel():
    result = layered_backtest(pl.DataFrame({"date": [], "code": [], "signal": [], "forward_return_5d": []}), 1)
    assert result["periods"] == 0
    assert result["net_values"] == {}
    assert result["summary"] == {}


def test_layered_backtest_dead_week_excluded():
    # signal/forward 全 null 的周（头部窗口未满/尾部无未来收益）不计入回测期数
    # ——与 quant_core 周频评估的 n_weeks 口径一致（有效周才计）
    panel = _weekly_panel(weeks=3)  # 3 周有效
    dead = pl.DataFrame({
        "date": [datetime.date(2024, 2, 2), datetime.date(2024, 2, 2)],
        "code": ["000001", "000002"],
        "signal": [None, None],
        "forward_return_5d": [None, None],
    })
    result = layered_backtest(pl.concat([panel, dead]), direction=1)
    assert result["periods"] == 3
    assert len(result["dates"]) == 3
    assert all(len(v) == 3 for v in result["net_values"].values())


def test_layered_backtest_tail_week_with_partial_null_kept():
    # 周内部分行 signal/forward 为 null（尾部停牌/无未来收益）——该周仍计入期数
    # （组内其余股票 forward 等权平均；全 null 的档该周收益记 0、净值保持）
    panel = _weekly_panel(weeks=2, stocks=2)
    panel = pl.concat([
        panel,
        pl.DataFrame({
            "date": [datetime.date(2024, 1, 5)],
            "code": ["000099"],
            "signal": [0.5],
            "forward_return_5d": [None],  # 尾行无未来收益
        }),
    ])
    result = layered_backtest(panel, direction=1, n_groups=2)
    assert result["periods"] == 2
    assert len(result["net_values"]["D1"]) == 2


def test_layered_backtest_all_null_signal_empty():
    # 设计 §2.3：signal 全 null → 空回测（过滤后无有效行，不产出平值 1.0 假净值）
    panel = pl.DataFrame({
        "date": [datetime.date(2024, 1, 5), datetime.date(2024, 1, 5)],
        "code": ["000001", "000002"],
        "signal": [None, None],
        "forward_return_5d": [0.02, 0.01],
    })
    result = layered_backtest(panel, direction=1)
    assert result["periods"] == 0
    assert result["net_values"] == {}
    assert result["summary"] == {}


def test_layered_backtest_single_week():
    result = layered_backtest(_weekly_panel(weeks=1), direction=1)
    assert result["periods"] == 1
    assert all(len(v) == 1 for v in result["net_values"].values())
