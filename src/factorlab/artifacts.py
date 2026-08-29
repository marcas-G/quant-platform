"""M6-05：Versioned Signal/Label Artifact Persistence。

结果目录正式契约：

    results/<factor>/
    ├── signal.parquet   ← 未来 Strategy Runtime 唯一允许消费的正式 signal artifact
    ├── labels.parquet   ← FactorEvaluator 使用的未来标签 artifact（evaluation-only）
    ├── panel.parquet    ← legacy compatibility view（CLI/eval/Web 兼容，非正式输出）
    └── summary.json     ← manifest（最后写入 = core artifacts 完成标记）

主从关系：
    SignalArtifact → signal.parquet
    LabelArtifact  → labels.parquet
    SignalArtifact + LabelArtifact + 兼容字段 → panel.parquet

Loader 硬规则：**绝不 fallback 到 panel.parquet**——signal.parquet 缺失即报错。
旧 results 目录（无 artifact_format_version）对新 loader 明确报错，不 silent fallback。

Domain 层（domain/frames.py）只负责数据契约，不负责文件系统 I/O。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from factorlab.domain.frames import LabelArtifact, SignalArtifact, SignalMeta
from factorlab.domain.timing import (ExecutionTiming, InformationCutoff,
                                     SignalAvailability, SignalTiming)
from factorlab.engine.forward import DEFAULT_FORWARD_HORIZONS

_FORWARD_RETURN_RE = re.compile(r"^forward_return_(\d+)d$")

# 结果目录 format version（整数——layout 级版本；schema_version 为单个 artifact 契约版本）
ARTIFACT_FORMAT_VERSION = 1
SIGNAL_SCHEMA_VERSION = 1
LABEL_SCHEMA_VERSION = 1
LEGACY_PANEL_SCHEMA_VERSION = 1

# 文件名常量（单一来源——禁止 compute.py/loader/tests 各自手写字符串）
SIGNAL_FILE = "signal.parquet"
LABELS_FILE = "labels.parquet"
LEGACY_PANEL_FILE = "panel.parquet"
SUMMARY_FILE = "summary.json"

_LEGACY_DIR_MSG = "legacy result directory does not contain versioned Signal/Label artifacts"


# --------------------------------------------------------------------------
# SignalMeta 序列化（timing 以 Enum.value JSON 化——语言无关、JSON 可读）
# --------------------------------------------------------------------------

def _timing_to_dict(t: SignalTiming) -> dict[str, str]:
    return {
        "information_cutoff": t.information_cutoff.value,
        "available_at": t.available_at.value,
        "default_earliest_execution": t.default_earliest_execution.value,
    }


def _meta_to_dict(meta: SignalMeta) -> dict[str, Any]:
    return {
        "name": meta.name,
        "frequency": meta.frequency,
        "adjustment": meta.adjustment,
        "timing": _timing_to_dict(meta.timing),
    }


def _meta_from_dict(sig_manifest: dict[str, Any]) -> SignalMeta:
    """从 manifest 重建 SignalMeta（M6-06：structural validation——清晰 ValueError
    而非裸 KeyError/TypeError；timing 从 Enum.value 反解，非法值清晰报错）。"""
    meta = sig_manifest.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("signal manifest 缺少 meta 或 meta 非 dict")
    for key in ("name", "frequency", "timing"):
        if key not in meta:
            raise ValueError(f"signal meta 缺少字段: {key!r}")
    if not isinstance(meta["name"], str) or not meta["name"]:
        raise ValueError(f"signal meta name 必须为 non-empty str，实际 {meta['name']!r}")
    if not isinstance(meta["frequency"], str) or not meta["frequency"]:
        raise ValueError(f"signal meta frequency 必须为 non-empty str，实际 {meta['frequency']!r}")
    adjustment = meta.get("adjustment")
    if adjustment is not None and not isinstance(adjustment, str):
        raise ValueError(f"signal meta adjustment 必须为 null 或 str，实际 {adjustment!r}")
    timing = meta.get("timing")
    if not isinstance(timing, dict):
        raise ValueError("signal meta timing 非 dict")
    for key in ("information_cutoff", "available_at", "default_earliest_execution"):
        if key not in timing:
            raise ValueError(f"signal meta timing 缺少字段: {key!r}")
        if not isinstance(timing[key], str):
            raise ValueError(f"signal meta timing {key} 必须为 str，实际 {timing[key]!r}")
    try:
        info = InformationCutoff(timing["information_cutoff"])
        avail = SignalAvailability(timing["available_at"])
        exec_t = ExecutionTiming(timing["default_earliest_execution"])
    except ValueError as exc:
        raise ValueError(
            f"invalid signal timing value: {exc}（manifest timing: {timing}）") from exc
    timing_obj = SignalTiming(information_cutoff=info, available_at=avail,
                              default_earliest_execution=exec_t)
    return SignalMeta(name=meta["name"], frequency=meta["frequency"], timing=timing_obj,
                      adjustment=meta.get("adjustment"))


# --------------------------------------------------------------------------
# 原子写（单文件 atomic：temp sibling + os.replace；目录级事务不实现——见风险）
# --------------------------------------------------------------------------

def _atomic_write(path: Path, writer) -> None:
    tmp = path.with_name(path.name + ".tmp")
    writer(tmp)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

def build_manifest(signal_artifact: SignalArtifact, label_artifact: LabelArtifact,
                   panel: pl.DataFrame) -> dict[str, Any]:
    """构造 artifact manifest（rows/columns 直接来自内存 frame——与实际文件一致）。"""
    return {
        "artifact_format_version": ARTIFACT_FORMAT_VERSION,
        "artifacts": {
            "signal": {
                "file": SIGNAL_FILE,
                "schema_version": SIGNAL_SCHEMA_VERSION,
                "rows": signal_artifact.frame.height,
                "columns": list(signal_artifact.frame.columns),
                "meta": _meta_to_dict(signal_artifact.meta),
            },
            "labels": {
                "file": LABELS_FILE,
                "schema_version": LABEL_SCHEMA_VERSION,
                "rows": label_artifact.frame.height,
                "columns": list(label_artifact.frame.columns),
                # M6-06A：horizons 来自实际 LabelArtifact 列（schema-v1 validation
                # 已保证 actual == DEFAULT_FORWARD_HORIZONS——不重新硬编码）
                "horizons": list(extract_forward_horizons(list(label_artifact.frame.columns))),
            },
            "panel": {
                "file": LEGACY_PANEL_FILE,
                "schema_version": LEGACY_PANEL_SCHEMA_VERSION,
                "rows": panel.height,
                "columns": list(panel.columns),
                "role": "legacy_compatibility_view",
            },
        },
    }


def validate_label_schema_v1(labels: LabelArtifact) -> None:
    """Persistence-side Label schema v1：实际 horizons 必须 == DEFAULT_FORWARD_HORIZONS。

    Domain LabelArtifact 允许任意 horizon（forward_return_60d 合法构造），但
    schema v1 persistence 固定 (5, 20)——writer 必须在写文件前验证，否则生成
    自己的 loader 必然拒绝的目录。
    """
    actual = extract_forward_horizons(list(labels.frame.columns))
    if actual != DEFAULT_FORWARD_HORIZONS:
        raise ValueError(
            f"Label schema v1 要求 horizons == {DEFAULT_FORWARD_HORIZONS}，"
            f"实际 {actual}（domain 允许任意 horizon，但不能用 schema v1 落盘）")


def validate_signal_label_alignment(signal: SignalArtifact,
                                    labels: LabelArtifact) -> None:
    """Signal/Label (date, code) key 严格对齐（M6-06）。

    验证行数、date/code 键、**键顺序**三者一致（Polars-native equals——不对
    千万行做 Python set 转换）。不一致 → ValueError（artifact pair mismatch）。
    """
    if signal.frame.height != labels.frame.height:
        raise ValueError(f"Signal/Label row count 不一致: signal {signal.frame.height} "
                         f"vs labels {labels.frame.height}")
    if not signal.frame.select(["date", "code"]).equals(labels.frame.select(["date", "code"])):
        raise ValueError("Signal/Label (date, code) key 不一致（含顺序）——artifact pair mismatch")


def _check_no_internal_columns(frame: pl.DataFrame, name: str) -> None:
    """core persisted artifacts 不得含 __factorlab_* 内部保留列（M6-06）——
    发现即 fail fast（暴露 runtime 泄漏，不 drop 后继续写）。"""
    bad = [c for c in frame.columns if c.startswith("__factorlab_")]
    if bad:
        raise ValueError(f"{name} 包含内部保留列——不允许落盘: {bad}（runtime 泄漏）")


def write_factor_artifacts(output_dir: Path, signal_artifact: SignalArtifact,
                           label_artifact: LabelArtifact, panel: pl.DataFrame,
                           summary: dict) -> dict:
    """统一 artifact 落盘：signal → labels → panel → summary（最后 = 完成标记）。

    三个 parquet 直接来自内存 artifact（signal 绝不从 panel 派生）。
    **写任何文件之前**执行：Signal/Label key 对齐验证 + 内部保留列 guard——
    pair mismatch / runtime 泄漏 → 零文件写入。返回加入 manifest 后的 summary。
    """
    # 全部验证在任何 I/O 之前完成（M6-06A：含 Label schema v1 自洽——
    # 60d-only LabelArtifact 不能生成自己的 loader 必然拒绝的目录）
    validate_signal_label_alignment(signal_artifact, label_artifact)
    _check_no_internal_columns(signal_artifact.frame, "signal")
    _check_no_internal_columns(label_artifact.frame, "labels")
    _check_no_internal_columns(panel, "panel")
    validate_label_schema_v1(label_artifact)
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(output_dir / SIGNAL_FILE,
                  lambda p: signal_artifact.frame.write_parquet(p))
    _atomic_write(output_dir / LABELS_FILE,
                  lambda p: label_artifact.frame.write_parquet(p))
    _atomic_write(output_dir / LEGACY_PANEL_FILE,
                  lambda p: panel.write_parquet(p))
    manifest = build_manifest(signal_artifact, label_artifact, panel)
    summary = {**summary, **manifest}
    _atomic_write(output_dir / SUMMARY_FILE, lambda p: p.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"))
    return summary


# --------------------------------------------------------------------------
# Loaders（fail fast；绝不 fallback panel）
# --------------------------------------------------------------------------

def _load_summary(result_dir: Path) -> dict:
    p = result_dir / SUMMARY_FILE
    if not p.exists():
        raise ValueError(f"summary.json 不存在: {result_dir}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"summary.json 根结构必须是 dict，实际 {type(data).__name__}")
    return data


def _check_format_version(summary: dict) -> None:
    """artifact format version 严格 int（非 bool）——True/1.0/"1"/null/-1 均拒绝。"""
    v = summary.get("artifact_format_version")
    if v is None:
        raise ValueError(_LEGACY_DIR_MSG)
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise ValueError(f"invalid artifact format version type/value: {v!r}"
                         f"（必须为 >=1 的整数，supported version {ARTIFACT_FORMAT_VERSION}）")
    if v != ARTIFACT_FORMAT_VERSION:
        raise ValueError(f"unsupported artifact format version {v}——"
                         f"supported version {ARTIFACT_FORMAT_VERSION}")


def _check_schema_version(manifest: dict, name: str, supported: int) -> None:
    """schema version 严格 int（非 bool）且 >= 1——True/1.0/"1"/0/-1 均拒绝。"""
    v = manifest.get("schema_version")
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise ValueError(f"invalid {name} schema version type/value: {v!r}"
                         f"（必须为 >=1 的整数，supported version {supported}）")
    if v != supported:
        raise ValueError(f"unsupported {name} schema version {v}——"
                         f"supported version {supported}")


def _check_fixed_file(manifest: dict, name: str, fixed: str) -> None:
    declared = manifest.get("file")
    if declared != fixed:
        raise ValueError(f"{name} manifest 声明文件 {declared!r} ≠ 平台固定 {fixed!r}"
                         f"——不信任 manifest 指向的任意路径")


def _require_dict(value: Any, name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{name} 必须是 dict，实际 {type(value).__name__}（{value!r}）")


def _validate_rows(manifest: dict, name: str) -> None:
    v = manifest.get("rows")
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ValueError(f"{name} manifest rows 必须为非负整数，实际 {v!r}")


def _validate_columns(manifest: dict, name: str) -> None:
    v = manifest.get("columns")
    if not isinstance(v, list) or not all(isinstance(c, str) for c in v):
        raise ValueError(f"{name} manifest columns 必须为 list[str]，实际 {v!r}")


def _validate_horizons(manifest: dict, name: str) -> tuple[int, ...]:
    v = manifest.get("horizons")
    if not isinstance(v, list) or not all(
            isinstance(h, int) and not isinstance(h, bool) and h > 0 for h in v):
        raise ValueError(f"{name} manifest horizons 必须为 positive list[int]，实际 {v!r}")
    if len(set(v)) != len(v) or any(v[i] >= v[i + 1] for i in range(len(v) - 1)):
        raise ValueError(f"{name} manifest horizons 必须 strictly increasing，实际 {v!r}")
    return tuple(v)


def extract_forward_horizons(columns: list[str]) -> tuple[int, ...]:
    """从实际 label 列推导 horizons（如 [forward_return_5d, forward_return_20d] → (5, 20)）。"""
    return tuple(sorted(int(m.group(1)) for c in columns
                        if (m := _FORWARD_RETURN_RE.match(c))))


def _get_artifact_entry(summary: dict, name: str) -> dict:
    artifacts = summary.get("artifacts")
    _require_dict(artifacts, "artifacts")
    entry = artifacts.get(name)
    _require_dict(entry, f"artifacts.{name}")
    return entry


def load_signal_artifact(result_dir: Path) -> SignalArtifact:
    """读取 signal.parquet + manifest → 重建 SignalMeta → M6-01 validator 复验磁盘。

    M6-06：manifest rows/columns 与磁盘实际一致（严格、含顺序）；meta structural
    validation（清晰 ValueError）；缺 signal.parquet 时**绝不 fallback panel**；
    旧目录明确报错。
    """
    summary = _load_summary(result_dir)
    _check_format_version(summary)
    sig = _get_artifact_entry(summary, "signal")
    _check_schema_version(sig, "signal", SIGNAL_SCHEMA_VERSION)
    _check_fixed_file(sig, "signal", SIGNAL_FILE)
    _validate_rows(sig, "signal")
    _validate_columns(sig, "signal")
    path = result_dir / SIGNAL_FILE
    if not path.exists():
        raise ValueError(f"signal.parquet 不存在: {path}（禁止 fallback 到 panel.parquet）")
    frame = pl.read_parquet(path)
    if sig["rows"] != frame.height:
        raise ValueError(f"signal manifest rows {sig['rows']} != 实际 parquet rows {frame.height}")
    if sig["columns"] != list(frame.columns):
        raise ValueError(f"signal manifest columns {sig['columns']} != 实际 parquet columns "
                         f"{list(frame.columns)}（含顺序）")
    meta = _meta_from_dict(sig)
    return SignalArtifact(frame=frame, meta=meta)


def load_label_artifact(result_dir: Path) -> LabelArtifact:
    """读取 labels.parquet + manifest → LabelArtifact（validator 复验磁盘内容）。

    M6-06：manifest rows/columns/horizons 与磁盘实际一致；schema v1 horizons
    必须 == DEFAULT_FORWARD_HORIZONS。
    """
    summary = _load_summary(result_dir)
    _check_format_version(summary)
    lab = _get_artifact_entry(summary, "labels")
    _check_schema_version(lab, "labels", LABEL_SCHEMA_VERSION)
    _check_fixed_file(lab, "labels", LABELS_FILE)
    _validate_rows(lab, "labels")
    _validate_columns(lab, "labels")
    manifest_horizons = _validate_horizons(lab, "labels")
    path = result_dir / LABELS_FILE
    if not path.exists():
        raise ValueError(f"labels.parquet 不存在: {path}")
    frame = pl.read_parquet(path)
    if lab["rows"] != frame.height:
        raise ValueError(f"labels manifest rows {lab['rows']} != 实际 parquet rows {frame.height}")
    if lab["columns"] != list(frame.columns):
        raise ValueError(f"labels manifest columns {lab['columns']} != 实际 parquet columns "
                         f"{list(frame.columns)}（含顺序）")
    actual_horizons = extract_forward_horizons(list(frame.columns))
    if manifest_horizons != actual_horizons:
        raise ValueError(f"labels manifest horizons {manifest_horizons} != 实际 label horizons "
                         f"{actual_horizons}")
    if manifest_horizons != DEFAULT_FORWARD_HORIZONS:
        raise ValueError(f"labels schema v1 horizons 必须 == DEFAULT_FORWARD_HORIZONS "
                         f"{DEFAULT_FORWARD_HORIZONS}，实际 {manifest_horizons}")
    return LabelArtifact(frame=frame)


@dataclass(frozen=True)
class FactorArtifactBundle:
    """Signal + Label 组合（integrity / evaluation / research tooling 用）。

    同时含未来标签——**不是 strategy-safe API**；Strategy consumer 只用
    load_signal_artifact()。
    """

    signal: SignalArtifact
    labels: LabelArtifact


def load_factor_artifacts(result_dir: Path) -> FactorArtifactBundle:
    """组合 loader：signal + labels + key alignment 验证（不加载 panel——bundle
    不依赖 legacy view）。"""
    signal = load_signal_artifact(result_dir)
    labels = load_label_artifact(result_dir)
    validate_signal_label_alignment(signal, labels)
    return FactorArtifactBundle(signal=signal, labels=labels)
