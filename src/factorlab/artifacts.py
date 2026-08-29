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
from pathlib import Path
from typing import Any

import polars as pl

from factorlab.domain.frames import LabelArtifact, SignalArtifact, SignalMeta
from factorlab.domain.timing import (ExecutionTiming, InformationCutoff,
                                     SignalAvailability, SignalTiming)
from factorlab.engine.forward import DEFAULT_FORWARD_HORIZONS

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


def _meta_from_dict(d: dict[str, Any]) -> SignalMeta:
    """从 manifest 重建 SignalMeta（timing 从 Enum.value 反解——不硬编码默认）。"""
    timing = SignalTiming(
        information_cutoff=InformationCutoff(d["timing"]["information_cutoff"]),
        available_at=SignalAvailability(d["timing"]["available_at"]),
        default_earliest_execution=ExecutionTiming(d["timing"]["default_earliest_execution"]),
    )
    return SignalMeta(name=d["name"], frequency=d["frequency"], timing=timing,
                      adjustment=d.get("adjustment"))


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
                "horizons": list(DEFAULT_FORWARD_HORIZONS),
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


def write_factor_artifacts(output_dir: Path, signal_artifact: SignalArtifact,
                           label_artifact: LabelArtifact, panel: pl.DataFrame,
                           summary: dict) -> dict:
    """统一 artifact 落盘：signal → labels → panel → summary（最后 = 完成标记）。

    三个 parquet 直接来自内存 artifact（signal 绝不从 panel 派生）。
    返回加入 manifest 后的 summary。
    """
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
    return json.loads(p.read_text(encoding="utf-8"))


def _check_format_version(summary: dict) -> None:
    v = summary.get("artifact_format_version")
    if v is None:
        raise ValueError(_LEGACY_DIR_MSG)
    if v != ARTIFACT_FORMAT_VERSION:
        raise ValueError(f"unsupported artifact format version {v}——"
                         f"supported version {ARTIFACT_FORMAT_VERSION}")


def _check_schema_version(manifest: dict, name: str, supported: int) -> None:
    v = manifest.get("schema_version")
    if v != supported:
        raise ValueError(f"unsupported {name} schema version {v}——"
                         f"supported version {supported}")


def _check_fixed_file(manifest: dict, name: str, fixed: str) -> None:
    declared = manifest.get("file")
    if declared != fixed:
        raise ValueError(f"{name} manifest 声明文件 {declared!r} ≠ 平台固定 {fixed!r}"
                         f"——不信任 manifest 指向的任意路径")


def load_signal_artifact(result_dir: Path) -> SignalArtifact:
    """读取 signal.parquet + manifest → 重建 SignalMeta → M6-01 validator 再次验证磁盘内容。

    缺 signal.parquet 时**绝不 fallback 到 panel.parquet**；旧目录（无 versioned
    manifest）明确报错。
    """
    summary = _load_summary(result_dir)
    _check_format_version(summary)
    sig = summary.get("artifacts", {}).get("signal")
    if not sig:
        raise ValueError(_LEGACY_DIR_MSG)
    _check_schema_version(sig, "signal", SIGNAL_SCHEMA_VERSION)
    _check_fixed_file(sig, "signal", SIGNAL_FILE)
    path = result_dir / SIGNAL_FILE
    if not path.exists():
        raise ValueError(f"signal.parquet 不存在: {path}（禁止 fallback 到 panel.parquet）")
    frame = pl.read_parquet(path)
    meta = _meta_from_dict(sig["meta"])
    return SignalArtifact(frame=frame, meta=meta)


def load_label_artifact(result_dir: Path) -> LabelArtifact:
    """读取 labels.parquet + manifest → LabelArtifact（validator 验证磁盘内容）。"""
    summary = _load_summary(result_dir)
    _check_format_version(summary)
    lab = summary.get("artifacts", {}).get("labels")
    if not lab:
        raise ValueError(_LEGACY_DIR_MSG)
    _check_schema_version(lab, "labels", LABEL_SCHEMA_VERSION)
    _check_fixed_file(lab, "labels", LABELS_FILE)
    path = result_dir / LABELS_FILE
    if not path.exists():
        raise ValueError(f"labels.parquet 不存在: {path}")
    return LabelArtifact(frame=pl.read_parquet(path))
