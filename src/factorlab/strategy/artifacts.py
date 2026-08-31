"""M7-04：Strategy Artifact Persistence——Strategy Runtime 磁盘边界。

布局（strategy result dir）：

    <dir>/
    ├── target_portfolio.parquet     （TargetPortfolio.frame 直接落盘）
    ├── rebalance_schedule.parquet   （decision_dates——core artifact，单独保存
    │                                 否则 explicit all-cash 日期无法恢复）
    └── strategy_manifest.json       （最后写 = 完成标记）

策略安全：**不持久化/加载 LabelArtifact / labels.parquet / forward_return_* /
panel.parquet / FactorResult**。source SignalArtifact 只记录 SignalMeta
provenance（不复制 signal 数据；不保存 source 路径——无 run-id/hash 前
不做 byte-identity binding）。

版本语义：FORMAT_VERSION = 目录布局；SCHEMA_VERSION = 单个 persisted
contract。与 M6 factor artifact（factorlab.artifacts）独立版本化。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from factorlab.domain.frames import SignalArtifact, SignalMeta
from factorlab.domain.portfolio import TargetPortfolio, TargetPortfolioMeta
from factorlab.strategy.schedule import RebalanceSchedule
from factorlab.strategy.spec import StrategySpec

TARGET_PORTFOLIO_FILE = "target_portfolio.parquet"
REBALANCE_SCHEDULE_FILE = "rebalance_schedule.parquet"
STRATEGY_MANIFEST_FILE = "strategy_manifest.json"

STRATEGY_ARTIFACT_FORMAT_VERSION = 1
TARGET_PORTFOLIO_SCHEMA_VERSION = 1
REBALANCE_SCHEDULE_SCHEMA_VERSION = 1
STRATEGY_SPEC_SCHEMA_VERSION = 1

_TARGET_COLUMNS = ["decision_date", "code", "target_weight"]
_SCHEDULE_COLUMNS = ["decision_date"]


@dataclass(frozen=True)
class StrategyArtifactBundle:
    """Strategy 三对象聚合（不含 LabelArtifact/SignalArtifact/panel/PnL）。"""

    spec: StrategySpec
    schedule: RebalanceSchedule
    target: TargetPortfolio


# ---------------------------------------------------------------------------
# 通用校验 helpers
# ---------------------------------------------------------------------------

def _strict_int(value, field: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} 必须为 strict int（bool 拒绝，收到 {value!r}）")
    if value < minimum:
        raise ValueError(f"{field} 必须 >= {minimum}（收到 {value!r}）")
    return value


def _require(value, cls, name: str):
    if not isinstance(value, cls):
        raise TypeError(f"{name} 必须为 {cls.__name__}（收到 {type(value).__name__}）"
                        f"——Strategy Runtime 边界，不自动转换")


def _timing_json(timing) -> dict:
    return {"information_cutoff": timing.information_cutoff.value,
            "available_at": timing.available_at.value,
            "default_earliest_execution": timing.default_earliest_execution.value}


def _timing_from_json(d: dict):
    from factorlab.domain.timing import (ExecutionTiming, InformationCutoff,
                                         SignalAvailability, SignalTiming)
    try:
        return SignalTiming(
            information_cutoff=InformationCutoff(d["information_cutoff"]),
            available_at=SignalAvailability(d["available_at"]),
            default_earliest_execution=ExecutionTiming(d["default_earliest_execution"]),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"source_signal.timing 非法: {exc}") from exc


# ---------------------------------------------------------------------------
# 单文件 atomic write（sibling .tmp → os.replace）
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, writer) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as f:
        writer(f)
    os.replace(tmp, path)


def _write_text(path: Path, text: str) -> None:
    _atomic_write(path, lambda f: f.write(text.encode("utf-8")))


# ---------------------------------------------------------------------------
# Cross-object invariants（所有 I/O 前完成）
# ---------------------------------------------------------------------------

def _validate_cross(signal: SignalArtifact, spec: StrategySpec,
                    schedule: RebalanceSchedule, target: TargetPortfolio) -> None:
    if signal.meta.name != spec.signal_name:
        raise ValueError(
            f"source/spec signal_name 不匹配：{signal.meta.name!r} vs "
            f"{spec.signal_name!r}")
    if schedule.source_signal_name != signal.meta.name:
        raise ValueError(
            f"source/schedule signal_name 不匹配：{signal.meta.name!r} vs "
            f"{schedule.source_signal_name!r}")
    if schedule.frequency != spec.rebalance_frequency:
        raise ValueError(
            f"spec/schedule frequency 不匹配：{spec.rebalance_frequency!r} vs "
            f"{schedule.frequency!r}")
    if target.decision_dates != schedule.decision_dates:
        raise ValueError(
            f"target/schedule decision_dates 不一致（含顺序与 all-cash 日期）")
    if target.meta.strategy_name != spec.name:
        raise ValueError(
            f"target/spec strategy_name 不匹配：{target.meta.strategy_name!r} vs "
            f"{spec.name!r}")
    if target.meta.source_signal_name != signal.meta.name:
        raise ValueError(
            f"target/source signal_name 不匹配：{target.meta.source_signal_name!r} "
            f"vs {signal.meta.name!r}")
    if target.meta.source_timing != signal.meta.timing:
        raise ValueError("target/source timing 不匹配")
    if target.meta.frequency != signal.meta.frequency:
        raise ValueError(
            f"target/source frequency 不匹配：{target.meta.frequency!r} vs "
            f"{signal.meta.frequency!r}")
    if target.meta.rebalance_frequency != spec.rebalance_frequency:
        raise ValueError(
            f"target/spec rebalance_frequency 不匹配："
            f"{target.meta.rebalance_frequency!r} vs {spec.rebalance_frequency!r}")
    if target.meta.gross_exposure != spec.gross_exposure:
        raise ValueError(
            f"target/spec gross_exposure 不匹配：{target.meta.gross_exposure!r} vs "
            f"{spec.gross_exposure!r}")


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_strategy_artifacts(
    output_dir: Path,
    *,
    source_signal: SignalArtifact,
    spec: StrategySpec,
    schedule: RebalanceSchedule,
    target: TargetPortfolio,
) -> dict:
    """策略三对象持久化（validate all → target → schedule → manifest LAST）。

    source_signal 只用于 cross-validation + provenance（其 frame 不写入
    strategy directory——正式 signal 数据仍属 Factor Artifact）。
    不重新运行 constructor/scheduler——本函数是 persistence layer。
    """
    _require(output_dir, Path, "output_dir")
    _require(source_signal, SignalArtifact, "source_signal")
    _require(spec, StrategySpec, "spec")
    _require(schedule, RebalanceSchedule, "schedule")
    _require(target, TargetPortfolio, "target")
    _validate_cross(source_signal, spec, schedule, target)

    output_dir.mkdir(parents=True, exist_ok=True)
    tp_path = output_dir / TARGET_PORTFOLIO_FILE
    sch_path = output_dir / REBALANCE_SCHEDULE_FILE
    mani_path = output_dir / STRATEGY_MANIFEST_FILE

    # 1. target（直接来自 TargetPortfolio.frame）
    target.frame.write_parquet(tp_path)
    # 2. schedule（严格一列 Date，decision_dates 原样顺序）
    sch = pl.DataFrame({"decision_date": pl.Series(
        schedule.decision_dates, dtype=pl.Date)})
    sch.write_parquet(sch_path)
    # 3. manifest（最后 = core artifacts complete）
    manifest = {
        "strategy_artifact_format_version": STRATEGY_ARTIFACT_FORMAT_VERSION,
        "strategy_spec": {
            "schema_version": STRATEGY_SPEC_SCHEMA_VERSION,
            "value": spec.model_dump(mode="json"),
        },
        "source_signal": {
            "name": source_signal.meta.name,
            "frequency": source_signal.meta.frequency,
            "adjustment": source_signal.meta.adjustment,
            "timing": _timing_json(source_signal.meta.timing),
        },
        "artifacts": {
            "target_portfolio": {
                "file": TARGET_PORTFOLIO_FILE,
                "schema_version": TARGET_PORTFOLIO_SCHEMA_VERSION,
                "rows": target.frame.height,
                "columns": target.frame.columns,
                "meta": {
                    "strategy_name": target.meta.strategy_name,
                    "source_signal_name": target.meta.source_signal_name,
                    "signal_frequency": target.meta.frequency,
                    "rebalance_frequency": target.meta.rebalance_frequency,
                    "gross_exposure": target.meta.gross_exposure,
                    "source_timing": _timing_json(target.meta.source_timing),
                },
            },
            "rebalance_schedule": {
                "file": REBALANCE_SCHEDULE_FILE,
                "schema_version": REBALANCE_SCHEDULE_SCHEMA_VERSION,
                "rows": len(schedule.decision_dates),
                "columns": _SCHEDULE_COLUMNS,
                "frequency": schedule.frequency,
                "source_signal_name": schedule.source_signal_name,
            },
        },
    }
    _write_text(mani_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


# ---------------------------------------------------------------------------
# Loader helpers
# ---------------------------------------------------------------------------

def _load_manifest(result_dir: Path) -> dict:
    p = result_dir / STRATEGY_MANIFEST_FILE
    if not p.exists():
        raise ValueError(
            f"{STRATEGY_MANIFEST_FILE} 不存在——不是完整的 versioned strategy "
            f"artifact directory（目录级事务未实现，manifest 缺失 = incomplete）")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"manifest 根结构必须是 dict，实际 {type(data).__name__}")
    return data


def _check_format_version(m: dict) -> None:
    v = m.get("strategy_artifact_format_version")
    try:
        v = _strict_int(v, "strategy_artifact_format_version")
    except ValueError as exc:
        raise ValueError(f"strategy_artifact_format_version 必须为 strict int"
                         f"（True/1.0/'1'/0/-1/null 均拒绝）: {v!r}") from exc
    if v != STRATEGY_ARTIFACT_FORMAT_VERSION:
        raise ValueError(
            f"unsupported strategy artifact format version {v}"
            f"（当前支持 {STRATEGY_ARTIFACT_FORMAT_VERSION}）")


def _check_schema_version(v, field: str) -> int:
    try:
        return _strict_int(v, field)
    except ValueError as exc:
        raise ValueError(f"{field} 必须为 strict int >= 1（收到 {v!r}）") from exc


def _require_manifest_sections(m: dict) -> None:
    for key, typ in (("strategy_spec", dict), ("source_signal", dict),
                     ("artifacts", dict)):
        if not isinstance(m.get(key), typ):
            raise ValueError(f"manifest.{key} 必须为 {typ.__name__}（收到 "
                             f"{type(m.get(key)).__name__}）")
    arts = m["artifacts"]
    for key in ("target_portfolio", "rebalance_schedule"):
        if not isinstance(arts.get(key), dict):
            raise ValueError(f"manifest.artifacts.{key} 必须为 dict")


def _check_fixed_file(m: dict, key: str, expected: str) -> None:
    f = m.get("file")
    if f != expected:
        raise ValueError(
            f"manifest.artifacts.{key}.file 必须精确等于 {expected}"
            f"（收到 {f!r}——manifest 不能是任意路径 loader）")


def _check_rows_columns(disk: pl.DataFrame, m: dict, label: str) -> None:
    rows, cols = m.get("rows"), m.get("columns")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise ValueError(f"{label} rows 必须为 non-negative strict int（收到 {rows!r}）")
    if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
        raise ValueError(f"{label} columns 必须为 list[str]（收到 {cols!r}）")
    if disk.height != rows or disk.columns != cols:
        raise ValueError(
            f"{label} 磁盘 rows/columns 与 manifest 不一致："
            f"disk=({disk.height}, {disk.columns}) manifest=({rows}, {cols})")


def _signal_meta_from_manifest(m: dict) -> SignalMeta:
    ss = m["source_signal"]
    timing = _timing_from_json(ss.get("timing") or {})
    return SignalMeta(
        name=ss["name"],
        frequency=ss["frequency"],
        timing=timing,
        adjustment=ss.get("adjustment"),
    )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_strategy_spec(result_dir: Path) -> StrategySpec:
    """只读 manifest → StrategySpec（严格版本 + extra=forbid 复验）。"""
    m = _load_manifest(result_dir)
    _check_format_version(m)
    _require_manifest_sections(m)
    ss = m["strategy_spec"]
    _check_schema_version(ss.get("schema_version"), "strategy_spec.schema_version")
    try:
        return StrategySpec.model_validate(ss["value"])
    except Exception as exc:
        raise ValueError(f"manifest StrategySpec 非法（extra=forbid 保持）: {exc}") from exc


def load_rebalance_schedule(result_dir: Path) -> RebalanceSchedule:
    """manifest + schedule parquet（不加载 target）。"""
    m = _load_manifest(result_dir)
    _check_format_version(m)
    _require_manifest_sections(m)
    sch_m = m["artifacts"]["rebalance_schedule"]
    _check_schema_version(sch_m.get("schema_version"),
                          "rebalance_schedule.schema_version")
    _check_fixed_file(sch_m, "rebalance_schedule", REBALANCE_SCHEDULE_FILE)
    p = result_dir / REBALANCE_SCHEDULE_FILE
    if not p.exists():
        raise ValueError(f"{REBALANCE_SCHEDULE_FILE} 缺失——不 fallback")
    disk = pl.read_parquet(p)
    _check_rows_columns(disk, sch_m, "rebalance_schedule")
    if disk.schema["decision_date"] != pl.Date:
        raise ValueError(
            f"rebalance_schedule.decision_date dtype 必须为 Date"
            f"（收到 {disk.schema['decision_date']}——不自动 parse）")
    dates = tuple(disk["decision_date"].to_list())
    return RebalanceSchedule(decision_dates=dates,
                             frequency=sch_m["frequency"],
                             source_signal_name=sch_m["source_signal_name"])


def load_target_portfolio(result_dir: Path) -> TargetPortfolio:
    """manifest + schedule parquet + target parquet（恢复 all-cash decision dates）。

    不读取 signal/labels/panel（strategy-safe；无 factor fallback）。
    """
    m = _load_manifest(result_dir)
    _check_format_version(m)
    _require_manifest_sections(m)
    tp_m = m["artifacts"]["target_portfolio"]
    _check_schema_version(tp_m.get("schema_version"),
                          "target_portfolio.schema_version")
    _check_fixed_file(tp_m, "target_portfolio", TARGET_PORTFOLIO_FILE)
    p = result_dir / TARGET_PORTFOLIO_FILE
    if not p.exists():
        raise ValueError(f"{TARGET_PORTFOLIO_FILE} 缺失——绝不从 panel/signal 推断")
    disk = pl.read_parquet(p)
    _check_rows_columns(disk, tp_m, "target_portfolio")
    schedule = load_rebalance_schedule(result_dir)
    tm = tp_m["meta"]
    meta = TargetPortfolioMeta(
        strategy_name=tm["strategy_name"],
        source_signal_name=tm["source_signal_name"],
        source_timing=_timing_from_json(tm["source_timing"]),
        gross_exposure=tm["gross_exposure"],
        frequency=tm["signal_frequency"],
        rebalance_frequency=tm["rebalance_frequency"],
    )
    # M7-01 domain validator 复验（dtype/canonical/weights/sorting/gross）
    return TargetPortfolio(frame=disk, decision_dates=schedule.decision_dates,
                           meta=meta)


def load_strategy_artifacts(result_dir: Path) -> StrategyArtifactBundle:
    """完整加载 spec/schedule/target + 全部 cross-object invariants。

    不加载 source SignalArtifact（只以 manifest provenance 存在）——
    不要求原 factor directory 在磁盘。
    """
    spec = load_strategy_spec(result_dir)
    schedule = load_rebalance_schedule(result_dir)
    target = load_target_portfolio(result_dir)
    # 用 manifest provenance 重建 SignalMeta 做 cross-check（不构造 SignalArtifact）
    _signal_meta_from_manifest(_load_manifest(result_dir))
    if spec.signal_name != schedule.source_signal_name:
        raise ValueError(
            f"spec/schedule signal_name 不一致（tamper？）：{spec.signal_name!r} vs "
            f"{schedule.source_signal_name!r}")
    if spec.rebalance_frequency != schedule.frequency:
        raise ValueError(
            f"spec/schedule frequency 不一致（tamper？）：{spec.rebalance_frequency!r} "
            f"vs {schedule.frequency!r}")
    if target.meta.strategy_name != spec.name:
        raise ValueError(
            f"target/spec strategy_name 不一致（tamper？）：{target.meta.strategy_name!r} "
            f"vs {spec.name!r}")
    if target.meta.source_signal_name != spec.signal_name:
        raise ValueError(
            f"target/spec signal_name 不一致（tamper？）：{target.meta.source_signal_name!r} "
            f"vs {spec.signal_name!r}")
    if target.meta.rebalance_frequency != spec.rebalance_frequency:
        raise ValueError(
            f"target/spec rebalance_frequency 不一致（tamper？）")
    if target.meta.gross_exposure != spec.gross_exposure:
        raise ValueError(f"target/spec gross_exposure 不一致（tamper？）")
    return StrategyArtifactBundle(spec=spec, schedule=schedule, target=target)
