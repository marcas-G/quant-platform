"""M6-01：领域数据契约——SignalArtifact / LabelArtifact / SignalMeta。

核心边界（M6 最重要 domain invariant）：

    SignalArtifact  frame 中禁止任何 future/label 字段
                    （forward_* / future_* 前缀，target / label 精确字段）
    LabelArtifact   合法包含未来信息（forward_return_<N>d），
                    仅供 FactorEvaluator 使用，不得进入未来 Strategy Runtime

本模块只负责 schema contract + semantic contract，不做数据转换、
不做隐式修复（不 drop duplicate、不自动 cast）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import polars as pl

from factorlab.domain.timing import DEFAULT_EOD_SIGNAL_TIMING, SignalTiming

# future/label 拒绝规则：前缀 + 精确字段（清晰、可维护，非硬编码 horizon）
_FUTURE_PREFIXES = ("forward_", "future_")
_FUTURE_EXACT = {"target", "label"}
# LabelArtifact 允许的 label 列：forward_return_<N>d（任意 horizon）
_FORWARD_RETURN_RE = re.compile(r"^forward_return_\d+d$")

_REQUIRED_MSG = "required columns missing: {}"
_DTYPE_MSG = "dtype 必须为 {}，实际 {}"
_UNIQUE_MSG = "duplicate (date, code) rows not allowed（(date, code) must be unique）"


def _require_columns(frame: pl.DataFrame, cols: list[str], what: str) -> None:
    missing = [c for c in cols if c not in frame.columns]
    if missing:
        raise ValueError(f"{what} {_REQUIRED_MSG.format(missing)}")


def _check_date_code(frame: pl.DataFrame, what: str) -> None:
    """date/code 必需列 + dtype 契约（fail fast，不 cast）。"""
    _require_columns(frame, ["date", "code"], what)
    if frame.schema["date"] != pl.Date:
        raise ValueError(f"date 列 {_DTYPE_MSG.format('pl.Date', frame.schema['date'])}")
    if frame.schema["code"] != pl.String:
        raise ValueError(f"code 列 {_DTYPE_MSG.format('pl.String', frame.schema['code'])}")


def _check_unique_key(frame: pl.DataFrame) -> None:
    """(date, code) 唯一——重复必须 fail fast，绝不静默 dedup。"""
    dup = frame.group_by(["date", "code"]).len().filter(pl.col("len") > 1)
    if dup.height:
        raise ValueError(f"{_UNIQUE_MSG}（{dup.height} 组重复）")


def _check_future_guard(frame: pl.DataFrame) -> None:
    """SignalArtifact 防泄漏：拒绝任何 future/label 字段。"""
    for col in frame.columns:
        if col in _FUTURE_EXACT or col.startswith(_FUTURE_PREFIXES):
            raise ValueError(
                f"future/label columns are not allowed in SignalArtifact: {col!r}")


@dataclass(frozen=True)
class SignalMeta:
    """信号元数据。默认 = EOD 信号（t close 后可知，最早 t+1 open 执行）。"""

    name: str
    frequency: str = "1d"
    timing: SignalTiming = DEFAULT_EOD_SIGNAL_TIMING
    adjustment: str | None = None

    def __post_init__(self) -> None:
        if self.frequency != "1d":
            raise ValueError(f"frequency 当前仅支持 '1d'，实际 {self.frequency!r}")


@dataclass(frozen=True)
class SignalArtifact:
    """信号产物：非未来信息契约——禁止 forward_*/future_*/target/label。

    允许额外非未来列（raw_signal / coverage / quality_flag 等），
    但 (date, code) 必须唯一，核心三列 dtype 严格校验。
    """

    frame: pl.DataFrame
    meta: SignalMeta

    def __post_init__(self) -> None:
        _check_date_code(self.frame, "SignalArtifact")
        _require_columns(self.frame, ["signal"], "SignalArtifact")
        sig_dtype = self.frame.schema["signal"]
        if not sig_dtype.is_numeric():
            raise ValueError(
                f"signal 列 {_DTYPE_MSG.format('numeric (Float*/Int*/UInt*)', sig_dtype)}")
        _check_unique_key(self.frame)
        _check_future_guard(self.frame)


@dataclass(frozen=True)
class LabelArtifact:
    """标签产物：因子研究评估用——合法包含未来信息，不得进入 Strategy Runtime。

    **M6-06 v1 contract：只允许 date / code / forward_return_<N>d 列**——
    任意其他字段（signal/close/industry/__factorlab_*/arbitrary）→ ValueError。
    必需 date/code + 至少一个 forward_return_<N>d（任意 horizon，不写死 5/20——
    domain 层不固定 horizon；schema v1 的 [5,20] 约束在 artifacts loader 层）。
    label 尾部 null 合法（样本尾部无未来数据）。
    """

    frame: pl.DataFrame

    def __post_init__(self) -> None:
        _check_date_code(self.frame, "LabelArtifact")
        fwd_cols = [c for c in self.frame.columns if _FORWARD_RETURN_RE.match(c)]
        if not fwd_cols:
            raise ValueError(
                "LabelArtifact 必须至少包含一个 forward_return_<N>d 列")
        extra = [c for c in self.frame.columns
                 if c not in {"date", "code"} and c not in fwd_cols]
        if extra:
            raise ValueError(
                f"LabelArtifact 不允许非 label 列: {extra}"
                f"（v1 仅允许 date/code/forward_return_<N>d）")
        for c in fwd_cols:
            if not self.frame.schema[c].is_numeric():
                raise ValueError(
                    f"label 列 {c} {_DTYPE_MSG.format('numeric', self.frame.schema[c])}")
        _check_unique_key(self.frame)
