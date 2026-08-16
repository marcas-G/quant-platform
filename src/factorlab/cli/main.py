from pathlib import Path

import typer
from rich.console import Console

from factorlab import __version__
from factorlab.config import settings
from factorlab.data.fetcher import TeaJoinClient
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import RebuildScope, build_final_db, rebuild_all
from factorlab.data.refresh import refresh, refresh_indexes
from factorlab.data.verify import verify_all
from factorlab.factor.errors import FactorDSLError
from factorlab.factor.ast_gate import validate_formula
from factorlab.ops import plugins, registry
from factorlab.spec import load_spec


app = typer.Typer(no_args_is_help=True)
console = Console()
op_app = typer.Typer(no_args_is_help=True)
app.add_typer(op_app, name="op")


@app.callback()
def main() -> None:
    """factorlab 因子 DSL 计算平台"""


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def lint(spec_path: Path) -> None:
    """校验 YAML Spec 与 factor formula AST。"""
    try:
        spec = load_spec(spec_path)
        formulas = [spec.formula] if spec.formula is not None else [item.formula for item in spec.factors or []]
        for formula in formulas:
            validate_formula(formula)
    except (ValueError, FactorDSLError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"OK {spec.name}")


@op_app.command("list")
def op_list() -> None:
    plugins.discover_plugins(settings.plugin_dir)
    rows = [
        {
            "name": op.name,
            "kind": op.kind,
            "version": op.version,
        }
        for op in registry.list_ops()
    ]
    console.print(rows)


@op_app.command("doc")
def op_doc(name: str) -> None:
    plugins.discover_plugins(settings.plugin_dir)
    op = registry.get_op(name)
    console.print(f"{op.name} ({op.kind}, {op.version})")
    console.print(op.doc or "no doc")


@op_app.command("add")
def op_add(path: Path, force: bool = False) -> None:
    names = plugins.add_plugin(path, plugin_dir=settings.plugin_dir, force=force)
    console.print(f"registered: {', '.join(names)}")


@op_app.command("remove")
def op_remove(name: str) -> None:
    plugins.remove_plugin(name, plugin_dir=settings.plugin_dir)
    console.print(f"disabled: {name}")


data_app = typer.Typer(no_args_is_help=True)
app.add_typer(data_app, name="data")


def _staging_db() -> PlatformDB:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return PlatformDB(settings.data_dir / "rebuild_staging.duckdb")


def _final_db() -> PlatformDB:
    return PlatformDB(settings.data_dir / "factorlab.duckdb")


def _client() -> TeaJoinClient:
    return TeaJoinClient(token=settings.teajoin_token, base_url=settings.teajoin_base_url)


@data_app.command("rebuild")
def data_rebuild(start: str = "20000104", end: str | None = None, resume: bool = True) -> None:
    """teajoin 全量重建平台数据（暂存库 → 稀疏剔除 → 最终库）。"""
    if not settings.teajoin_token:
        console.print("错误: 未配置 FACTORLAB_TEAJOIN_TOKEN（.env）")
        raise typer.Exit(code=1)
    staging = _staging_db()
    report = rebuild_all(staging, _client(), scope=RebuildScope(start=start, end=end), resume=resume)
    console.print(f"rebuild 完成: {report['tables']}")
    final = build_final_db(staging, settings.data_dir / "factorlab.duckdb")
    console.print(f"稀疏剔除: {final['excluded_fields']}")
    console.print(f"最终库表: {final['tables']}")


@data_app.command("refresh")
def data_refresh() -> None:
    """增量拉取到最新交易日。"""
    if not settings.teajoin_token:
        console.print("错误: 未配置 FACTORLAB_TEAJOIN_TOKEN（.env）")
        raise typer.Exit(code=1)
    report = refresh(_final_db(), _client())
    console.print(f"refresh 完成: {report}")


@data_app.command("update")
def data_update() -> None:
    """一键更新：行情增量 + 指数增量 + 自动验证 + 报告（手动触发）。"""
    if not settings.teajoin_token:
        console.print("错误: 未配置 FACTORLAB_TEAJOIN_TOKEN（.env）")
        raise typer.Exit(code=1)
    report = refresh(_final_db(), _client())
    index_report = refresh_indexes(_final_db(), _client())
    verify = verify_all(_final_db())
    failures = [
        (t, info["failed"])
        for t, info in report.get("tables", {}).items()
        if info.get("failed")
    ]
    index_failures = [
        (t, info["failed"])
        for t, info in index_report.items()
        if info.get("failed")
    ]
    console.print(f"行情增量: {report['tables']}")
    console.print(f"指数增量: {index_report}")
    console.print(f"verify: integrity 规则 "
                  f"{sum(1 for r in verify['integrity'].values() for x in r.values() if x.get('passed'))}"
                  f"/{sum(len(r) for r in verify['integrity'].values())} 通过")
    if failures or index_failures:
        console.print(f"⚠ 失败项: {failures + index_failures}（下次 update 自动重试）")
    else:
        console.print("更新完成，无失败")


@data_app.command("verify")
def data_verify(compare: Path | None = None) -> None:
    """完整性自检 + 稀疏摘要 + 可选抽样对拍。"""
    report = verify_all(_final_db(), ref_db=compare)
    console.print(report)
