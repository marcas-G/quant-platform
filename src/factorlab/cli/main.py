import json
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


@app.command("run")
def run_factor_cli(
    spec_path: Path,
    universe: str | None = None,
    max_memory: str = "4GB",
    output_dir: Path | None = None,
    float32: bool = True,
) -> None:
    """计算因子并评估（平台库）。--universe 默认 FACTORLAB_DEFAULT_UNIVERSE。"""
    from factorlab.engine.compute import RunContext, run_factor as run_impl
    from factorlab.eval.rust_ic import evaluate_factor_weekly

    try:
        spec = load_spec(spec_path)
    except FileNotFoundError as exc:
        console.print(f"错误: {exc}")
        raise typer.Exit(code=1) from exc
    ctx = RunContext(
        db_path=settings.platform_db,
        output_dir=output_dir or (Path("results") / spec.name),
        universe_override=universe or settings.default_universe,
        float32=float32,
    )
    # load_daily 在调用时读取 settings.default_max_memory——临时覆盖并在结束后恢复
    original_memory = settings.default_max_memory
    settings.default_max_memory = max_memory
    try:
        if spec.target != "forward_return_5d":
            console.print(f"提示: quant_core 当前固定评估 forward_return_5d（spec.target={spec.target} 暂未接线，M4b 处理）")
        result = run_impl(spec, ctx)
        evaluation = evaluate_factor_weekly(result.panel, spec.name, spec.direction)
    except (ValueError, FileNotFoundError, FactorDSLError) as exc:
        console.print(f"错误: {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        settings.default_max_memory = original_memory
    # run_factor 已落盘 panel.parquet/summary.json（无 evaluation）；CLI 追加评估结果并重写
    result.summary["evaluation"] = evaluation
    result.panel.write_parquet(ctx.output_dir / "weekly.parquet")  # 评估输入面板
    (ctx.output_dir / "summary.json").write_text(
        json.dumps(result.summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    ic = evaluation.get("ic", {})
    console.print(f"{spec.name}: n_weeks={evaluation.get('n_weeks')} "
                  f"ic_mean={ic.get('mean')} spread={evaluation.get('decile_returns', {}).get('spread', {}).get('ret')}")


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
