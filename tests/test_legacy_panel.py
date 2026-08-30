"""M6-07C2B：legacy panel positional assembly（消除冗余 hash join）。

Signal/Label (date, code) 对齐由 validate_signal_label_alignment 证明后，
仅位置化附加 labels 值列——绝不做 key join（C2A 定位：1,155 万行 hash join
在无页面文件机器上撞 commit 空间 → 0xC0000005）。
"""

import datetime
import inspect

import polars as pl
import pytest

from factorlab.domain.frames import LabelArtifact, SignalArtifact, SignalMeta
from factorlab.domain.timing import DEFAULT_EOD_SIGNAL_TIMING
from factorlab.engine.compute import _build_legacy_panel

D1, D2, D3 = datetime.date(2024, 1, 2), datetime.date(2024, 1, 3), datetime.date(2024, 1, 4)


def _signal_df():
    return pl.DataFrame({
        "date": [D1, D2, D3],
        "code": ["000001", "000002", "000003"],
        "signal": [0.5, None, -1.2],
        "close": [10.0, 11.5, None],
    })


def _labels_df():
    return pl.DataFrame({
        "date": [D1, D2, D3],
        "code": ["000001", "000002", "000003"],
        "forward_return_5d": [0.01, None, -0.03],
        "forward_return_20d": [0.05, -0.02, None],
    })


def _artifacts(signal_df=None, labels_df=None):
    s = signal_df if signal_df is not None else _signal_df()
    l = labels_df if labels_df is not None else _labels_df()
    sa = SignalArtifact(frame=s.select(["date", "code", "signal"]),
                        meta=SignalMeta(name="t", frequency="1d",
                                        timing=DEFAULT_EOD_SIGNAL_TIMING,
                                        adjustment="qfq"))
    la = LabelArtifact(frame=l.select(["date", "code", "forward_return_5d",
                                       "forward_return_20d"]))
    return sa, la


def _join_reference(signal_df=None, labels_df=None):
    """测试 reference（非 production implementation）：旧 LEFT JOIN 数学结果。"""
    s = signal_df if signal_df is not None else _signal_df()
    l = labels_df if labels_df is not None else _labels_df()
    return (s.join(l, on=["date", "code"], how="left")
            .select(["date", "code", "signal", "forward_return_5d",
                     "forward_return_20d", "close"]))


# ---------------------------------------------------------------- 基本输出

def test_panel_schema_and_values():
    sa, la = _artifacts()
    panel = _build_legacy_panel(_signal_df(), _labels_df(), sa, la)
    assert panel.columns == ["date", "code", "signal", "forward_return_5d",
                             "forward_return_20d", "close"]
    assert panel.height == 3
    assert panel["signal"].to_list() == [0.5, None, -1.2]
    assert panel["forward_return_5d"].to_list() == [0.01, None, -0.03]
    assert panel["forward_return_20d"].to_list() == [0.05, -0.02, None]
    assert panel["close"].to_list() == [10.0, 11.5, None]
    assert panel["date"].to_list() == [D1, D2, D3]
    assert panel["code"].to_list() == ["000001", "000002", "000003"]


def test_panel_matches_left_join_reference():
    sa, la = _artifacts()
    panel = _build_legacy_panel(_signal_df(), _labels_df(), sa, la)
    expected = _join_reference()
    assert panel.equals(expected)          # rows/columns/dtypes/values 全等
    assert panel.schema == expected.schema


def test_panel_null_masks_match_reference():
    sa, la = _artifacts()
    panel = _build_legacy_panel(_signal_df(), _labels_df(), sa, la)
    expected = _join_reference()
    for c in ("signal", "forward_return_5d", "forward_return_20d", "close"):
        assert panel[c].null_count() == expected[c].null_count(), c


def test_close_comes_from_signal_row():
    """close 来自 signal runtime 的同一行（位置/值不变），不重新加载 daily。"""
    sig = _signal_df().with_columns(pl.col("close").alias("close"))  # 原样
    sa, la = _artifacts(signal_df=sig)
    panel = _build_legacy_panel(sig, _labels_df(), sa, la)
    assert panel["close"].to_list() == [10.0, 11.5, None]
    # close 顺序与 signal 行顺序一致（不按 labels 重排）
    assert panel["code"].to_list() == sig["code"].to_list()


def test_label_keys_not_duplicated():
    """label 的 date/code 只是 validation key，不重复附加。"""
    sa, la = _artifacts()
    panel = _build_legacy_panel(_signal_df(), _labels_df(), sa, la)
    assert "date_right" not in panel.columns
    assert "code_right" not in panel.columns
    assert len([c for c in panel.columns if c == "date"]) == 1
    assert len([c for c in panel.columns if c == "code"]) == 1


# ---------------------------------------------------------------- mismatch guards

def test_row_count_mismatch_fails():
    sig = _signal_df()
    lab = _labels_df().slice(0, 2)   # 少一行
    sa, la = _artifacts(signal_df=sig, labels_df=lab)
    with pytest.raises(ValueError, match="row count 不一致"):
        _build_legacy_panel(sig, lab, sa, la)


def test_key_mismatch_fails():
    sig = _signal_df()
    lab = _labels_df().with_columns(pl.col("code").replace({"000003": "999999"}))
    sa, la = _artifacts(signal_df=sig, labels_df=lab)
    with pytest.raises(ValueError, match="key 不一致"):
        _build_legacy_panel(sig, lab, sa, la)


def test_key_order_mismatch_fails():
    sig = _signal_df()
    lab = _labels_df().sort("code", descending=True)   # 键集合相同但顺序不同
    sa, la = _artifacts(signal_df=sig, labels_df=lab)
    with pytest.raises(ValueError, match="key 不一致"):
        _build_legacy_panel(sig, lab, sa, la)


# ---------------------------------------------------------------- 实现约束

def test_helper_source_contains_no_join():
    """源码级 guard：_build_legacy_panel 内部禁止任何 join（hash/asof/SQL）。"""
    src = inspect.getsource(_build_legacy_panel)
    assert ".join(" not in src.replace("signal_df", "").replace("labels_df", ""), \
        "legacy panel 构造不得使用 join"
    assert "hstack" in src, "应使用 positional column attachment"
