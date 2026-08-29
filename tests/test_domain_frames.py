"""M6-01：Domain Contracts——SignalArtifact / LabelArtifact / SignalMeta 校验。"""

from dataclasses import FrozenInstanceError

import polars as pl
import pytest

from factorlab.domain.frames import LabelArtifact, SignalArtifact, SignalMeta
from factorlab.domain.timing import DEFAULT_EOD_SIGNAL_TIMING

META = SignalMeta(name="test", frequency="1d", timing=DEFAULT_EOD_SIGNAL_TIMING,
                  adjustment="none")


def _frame(**overrides) -> pl.DataFrame:
    base = {
        "date": pl.Series(["2024-01-02", "2024-01-03", "2024-01-04"], dtype=pl.Date),
        "code": pl.Series(["000001", "000002", "000003"], dtype=pl.String),
        "signal": pl.Series([0.5, -0.3, 0.1], dtype=pl.Float32),
    }
    base.update(overrides)
    return pl.DataFrame(base)


def _artifact(frame: pl.DataFrame | None = None, **cols) -> SignalArtifact:
    """SignalArtifact helper（统一带 meta——meta 是必填契约字段）。"""
    return SignalArtifact(frame=_frame(**cols) if frame is None else frame, meta=META)


# ---------------------------------------------------------------- A. 正常路径

def test_signal_artifact_valid():
    a = _artifact()
    assert a.frame.height == 3
    assert a.meta.name == "test"


def test_signal_artifact_null_signal_allowed():
    a = _artifact(signal=pl.Series([0.5, None, 0.1], dtype=pl.Float32))
    assert a.frame["signal"].null_count() == 1


def test_signal_artifact_extra_non_future_columns_allowed():
    a = _artifact(raw_signal=pl.Series([1.0, 2.0, 3.0], dtype=pl.Float64),
                  coverage=pl.Series([0.9, 0.8, 1.0], dtype=pl.Float64))
    assert {"raw_signal", "coverage"} <= set(a.frame.columns)


def test_signal_meta_defaults():
    m = SignalMeta(name="x", frequency="1d")
    assert m.timing == DEFAULT_EOD_SIGNAL_TIMING
    assert m.adjustment is None


# ---------------------------------------------------------------- B. 缺列

@pytest.mark.parametrize("drop", ["date", "code", "signal"])
def test_signal_artifact_missing_column(drop):
    f = _frame().drop(drop)
    with pytest.raises(ValueError, match="required"):
        _artifact(frame=f)


# ---------------------------------------------------------------- C. dtype

@pytest.mark.parametrize("col,series", [
    ("date", pl.Series(["2024-01-02", "2024-01-03", "2024-01-04"])),          # String date
    ("code", pl.Series([1, 2, 3])),                                            # Int code
    ("signal", pl.Series(["a", "b", "c"])),                                    # String signal
    ("signal", pl.Series([True, False, True])),                                # Boolean signal
])
def test_signal_artifact_bad_dtype(col, series):
    with pytest.raises(ValueError, match="dtype"):
        _artifact(**{col: series})


def test_signal_artifact_int_signal_allowed():
    a = _artifact(signal=pl.Series([1, 2, 3], dtype=pl.Int32))
    assert a.frame["signal"].dtype == pl.Int32


# ---------------------------------------------------------------- D. duplicate

def test_signal_artifact_duplicate_key_rejected():
    dup = pl.concat([_frame(), _frame().head(1)])
    with pytest.raises(ValueError, match="unique"):
        _artifact(frame=dup)


# ---------------------------------------------------------------- E. future guard

@pytest.mark.parametrize("bad", [
    "forward_return_5d", "forward_return_20d", "forward_return_60d",
    "forward_price", "future_close", "future_ret", "target", "label",
])
def test_signal_artifact_future_guard(bad):
    f = _frame(**{bad: pl.Series([0.1, 0.2, 0.3], dtype=pl.Float64)})
    with pytest.raises(ValueError, match="future/label columns are not allowed"):
        _artifact(frame=f)


def test_signal_artifact_future_guard_fail_fast_no_mutation():
    f = _frame(forward_return_5d=pl.Series([0.1, 0.2, 0.3], dtype=pl.Float64))
    with pytest.raises(ValueError):
        _artifact(frame=f)
    assert "forward_return_5d" in f.columns  # 原 frame 未被修改


# ---------------------------------------------------------------- F. LabelArtifact 正常

def test_label_artifact_valid_5d():
    l = LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series(["2024-01-02", "2024-01-03"], dtype=pl.Date),
        "code": pl.Series(["000001", "000002"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.1, 0.2], dtype=pl.Float64),
    }))
    assert l.frame.height == 2


def test_label_artifact_multi_horizon():
    l = LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series(["2024-01-02", "2024-01-03"], dtype=pl.Date),
        "code": pl.Series(["000001", "000002"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.1, 0.2], dtype=pl.Float64),
        "forward_return_20d": pl.Series([0.3, 0.4], dtype=pl.Float64),
    }))
    assert {"forward_return_5d", "forward_return_20d"} <= set(l.frame.columns)


def test_label_artifact_arbitrary_horizon():
    l = LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series(["2024-01-02"], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "forward_return_60d": pl.Series([0.5], dtype=pl.Float64),
    }))
    assert "forward_return_60d" in l.frame.columns


def test_label_artifact_tail_null_allowed():
    l = LabelArtifact(frame=pl.DataFrame({
        "date": pl.Series(["2024-01-02", "2024-01-03"], dtype=pl.Date),
        "code": pl.Series(["000001", "000002"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.1, None], dtype=pl.Float64),
    }))
    assert l.frame["forward_return_5d"].null_count() == 1


# ---------------------------------------------------------------- G. LabelArtifact 错误

@pytest.mark.parametrize("drop", ["date", "code"])
def test_label_artifact_missing_column(drop):
    f = pl.DataFrame({
        "date": pl.Series(["2024-01-02"], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.1], dtype=pl.Float64),
    }).drop(drop)
    with pytest.raises(ValueError, match="required"):
        LabelArtifact(frame=f)


def test_label_artifact_no_forward_return_rejected():
    f = pl.DataFrame({
        "date": pl.Series(["2024-01-02"], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "signal": pl.Series([0.5], dtype=pl.Float32),
    })
    with pytest.raises(ValueError, match="forward_return"):
        LabelArtifact(frame=f)


def test_label_artifact_bad_dtype():
    f = pl.DataFrame({
        "date": pl.Series(["2024-01-02"], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "forward_return_5d": pl.Series(["a"], dtype=pl.String),
    })
    with pytest.raises(ValueError, match="dtype"):
        LabelArtifact(frame=f)


def test_label_artifact_duplicate_rejected():
    f = pl.DataFrame({
        "date": pl.Series(["2024-01-02", "2024-01-02"], dtype=pl.Date),
        "code": pl.Series(["000001", "000001"], dtype=pl.String),
        "forward_return_5d": pl.Series([0.1, 0.2], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="unique"):
        LabelArtifact(frame=f)


# ---------------------------------------------------------------- 边界 invariant

def test_signal_label_boundary():
    """Signal 含未来列 → 拒绝；同数据去掉 signal → Label 合法（M6 最重要 invariant）。"""
    f = pl.DataFrame({
        "date": pl.Series(["2024-01-02"], dtype=pl.Date),
        "code": pl.Series(["000001"], dtype=pl.String),
        "signal": pl.Series([0.5], dtype=pl.Float32),
        "forward_return_5d": pl.Series([0.1], dtype=pl.Float64),
    })
    with pytest.raises(ValueError, match="future/label columns are not allowed"):
        SignalArtifact(frame=f, meta=META)
    LabelArtifact(frame=f.drop("signal"))   # 去掉 signal → Label 合法


# ---------------------------------------------------------------- 不可变

def test_objects_immutable():
    a = _artifact()
    with pytest.raises(FrozenInstanceError):
        a.meta = None
    m = SignalMeta(name="x", frequency="1d")
    with pytest.raises(FrozenInstanceError):
        m.name = "y"
