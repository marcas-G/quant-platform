from __future__ import annotations

import ast
import importlib.util
import json
import shutil
from pathlib import Path

from factorlab.ops import registry


MANIFEST = "manifest.json"


def _manifest_path(plugin_dir: Path) -> Path:
    return plugin_dir / MANIFEST


def _load_manifest(plugin_dir: Path) -> dict:
    path = _manifest_path(plugin_dir)
    if not path.exists():
        return {"operators": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(plugin_dir: Path, manifest: dict) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path(plugin_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _scan_plugin_ast(source: str) -> None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec", "open", "compile", "__import__"}:
                raise ValueError(f"插件禁止调用: {node.func.id}")
        if isinstance(node, ast.Import):
            bad = [a.name for a in node.names if a.name.split(".")[0] in {"os", "sys", "subprocess", "socket", "shutil"}]
            if bad:
                raise ValueError(f"插件禁止导入: {bad}")


def _import_plugin(path: Path) -> None:
    spec = importlib.util.spec_from_file_location(f"factorlab_plugin_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"无法加载插件: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def add_plugin(path: str | Path, plugin_dir: Path, force: bool = False) -> list[str]:
    source_path = Path(path)
    if not source_path.exists() or source_path.suffix != ".py":
        raise ValueError("插件路径必须存在且为 .py 文件")

    source = source_path.read_text(encoding="utf-8")
    _scan_plugin_ast(source)

    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(plugin_dir)
    existing = {item["name"] for item in manifest["operators"]}

    before = {op.name for op in registry.list_ops()}
    _import_plugin(source_path)
    new_names = {op.name for op in registry.list_ops()} - before
    if not new_names:
        raise ValueError("插件未注册任何新算子")

    conflicts = new_names & existing
    if conflicts and not force:
        raise ValueError(f"算子已存在: {sorted(conflicts)}，使用 --force 覆盖")

    dest = plugin_dir / source_path.name
    if source_path.resolve() != dest.resolve():
        shutil.copyfile(source_path, dest)
    for name in new_names:
        op = registry.get_op(name)
        item = {
            "name": name,
            "kind": op.kind,
            "version": op.version,
            "file": dest.name,
            "enabled": True,
        }
        manifest["operators"] = [x for x in manifest["operators"] if x["name"] != name]
        manifest["operators"].append(item)
    _save_manifest(plugin_dir, manifest)
    return sorted(new_names)


def remove_plugin(name: str, plugin_dir: Path) -> None:
    manifest = _load_manifest(plugin_dir)
    matched = [item for item in manifest["operators"] if item["name"] == name]
    if not matched:
        raise KeyError(f"未找到算子: {name}")
    for item in matched:
        item["enabled"] = False
    _save_manifest(plugin_dir, manifest)


def discover_plugins(plugin_dir: Path) -> None:
    manifest = _load_manifest(plugin_dir)
    for item in manifest["operators"]:
        if not item.get("enabled", True):
            continue
        path = plugin_dir / item["file"]
        if path.exists():
            _import_plugin(path)


def list_enabled_operators(plugin_dir: Path) -> set[str]:
    manifest = _load_manifest(plugin_dir)
    return {
        registry.canonical_name(item["name"], item["kind"])
        for item in manifest["operators"]
        if item.get("enabled", True)
    }
