import datetime
import json
import re
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


def _parse_param_value(value: str) -> int | float | bool | str:
    """--set 值类型解析：int → float → bool（true/false）→ str 原样。"""
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    return value


@app.command("run")
def run_factor_cli(
    spec_path: Path,
    universe: str | None = None,
    max_memory: str = "4GB",
    output_dir: Path | None = None,
    float32: bool = True,
    backtest: bool = True,
    groups: int = typer.Option(10, min=2),
    set_params: list[str] = typer.Option(None, "--set", help="覆盖 spec.params（k=v，可多次，生成 name_kv 变体）"),
) -> None:
    """计算因子并评估（平台库）。--backtest 默认产出分层回测；--no-backtest 关闭（快速评估）。
    --groups 分层档数（>=2）。--set k=v 覆盖 spec.params 生成变体（results 独立目录）。
    --universe 默认 FACTORLAB_DEFAULT_UNIVERSE。"""
    from factorlab.engine.compute import RunContext, run_factor as run_impl
    from factorlab.eval.alignment import align_weekly
    from factorlab.eval.layered import layered_backtest
    from factorlab.eval.rust_ic import evaluate_factor_weekly

    overrides = {}
    for kv in set_params or []:
        key, _, value = kv.partition("=")
        if not key or not value:
            raise typer.BadParameter(f"--set 格式应为 k=v: {kv}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise typer.BadParameter(f"--set 值含非法字符（仅字母数字_.-）: {value}")
        overrides[key] = _parse_param_value(value)
    try:
        spec = load_spec(spec_path)
    except FileNotFoundError as exc:
        console.print(f"错误: {exc}")
        raise typer.Exit(code=1) from exc
    variant = spec.name
    if overrides:
        spec.params = {**spec.params, **overrides}
        variant = spec.name + "_" + "_".join(f"{k}{v}" for k, v in overrides.items())
    ctx = RunContext(
        db_path=settings.platform_db,
        output_dir=output_dir or (settings.results_dir / variant),
        universe_override=universe or settings.default_universe,
        float32=float32,
    )
    # load_daily 在调用时读取 settings.default_max_memory——临时覆盖并在结束后恢复
    original_memory = settings.default_max_memory
    settings.default_max_memory = max_memory
    try:
        if spec.target != "forward_return_5d":
            console.print(f"提示: quant_core 当前固定评估 forward_return_5d（spec.target={spec.target} 暂未接线，后续里程碑处理）")
        result = run_impl(spec, ctx)
        # 周频对齐面板：评估与分层回测的实际输入（evaluate_factor_weekly 内部重复对齐——YAGNI 不优化）
        weekly = align_weekly(result.panel)
        evaluation = evaluate_factor_weekly(result.panel, spec.name, spec.direction)
        if backtest:
            bt = layered_backtest(weekly, spec.direction, n_groups=groups)
            evaluation["layered_backtest"] = bt
            if bt.get("empty_groups"):
                console.print(f"提示: 档位 {bt['empty_groups']} 全期无股票——universe 过小或 --groups 过大")
    except (ValueError, FileNotFoundError, FactorDSLError) as exc:
        console.print(f"错误: {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        settings.default_max_memory = original_memory
    # run_factor 已落盘 panel.parquet/summary.json（无 evaluation）；CLI 追加评估结果并重写
    result.summary["evaluation"] = evaluation
    weekly.write_parquet(ctx.output_dir / "weekly.parquet")  # 周频对齐面板（替代原日频冗余）
    (ctx.output_dir / "summary.json").write_text(
        json.dumps(result.summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    ic = evaluation.get("ic", {})
    console.print(f"{variant}: n_weeks={evaluation.get('n_weeks')} "
                  f"ic_mean={ic.get('mean')} spread={evaluation.get('decile_returns', {}).get('spread', {}).get('ret')}")


def _run_at(summary: dict, summary_path: Path) -> tuple[str, float]:
    """summary 运行时间的 (展示值, 排序键)：timestamp 字段优先；
    缺失/不可解析时回退 summary.json 文件 mtime（M4a run 落盘无 timestamp）。"""
    ts = summary.get("timestamp")
    if ts:
        try:
            return str(ts), datetime.datetime.fromisoformat(str(ts)).timestamp()
        except ValueError:
            pass
    mtime = summary_path.stat().st_mtime
    return datetime.datetime.fromtimestamp(mtime).isoformat(timespec="seconds"), mtime


@app.command("list")
def list_factors() -> None:
    """列出已保存因子与最近运行摘要（results_dir/*/summary.json）。"""
    results_dir = settings.results_dir
    if not results_dir.is_dir():
        console.print("暂无因子结果（先运行 factorlab run）")
        return
    rows = []
    for summary_path in sorted(results_dir.glob("*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # 损坏/不可读的 summary 跳过
        ev = summary.get("evaluation", {})
        run_at, sort_key = _run_at(summary, summary_path)
        rows.append({
            # 变体目录（name_kv）的 summary.name 是基础名——目录名优先可区分
            "name": summary_path.parent.name if summary_path.parent.name != summary.get("name") else summary.get("name"),
            "category": summary.get("category", ""),
            "direction": summary.get("direction", ""),
            "ic_mean": ev.get("ic", {}).get("mean"),
            "spread": ev.get("decile_returns", {}).get("spread", {}).get("ret"),
            "run_at": run_at,
            "_sort": sort_key,
        })
    if not rows:
        console.print("暂无因子结果（先运行 factorlab run）")
        return
    for row in sorted(rows, key=lambda r: r["_sort"], reverse=True):
        console.print(f"{row['name']} | {row['category']} | dir={row['direction']} "
                      f"| ic={row['ic_mean']} | spread={row['spread']} | {row['run_at']}")


@app.command("show")
def show_factor(name: str) -> None:
    """查看单因子完整摘要（spec 原文/评估/分层回测）。"""
    summary_path = settings.results_dir / name / "summary.json"
    if not summary_path.exists():
        console.print(f"错误: 因子 {name} 不存在（{settings.results_dir / name}）")
        raise typer.Exit(code=1)
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"错误: 因子 {name} 的 summary.json 读取失败: {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"=== {name} ===")
    console.print(f"spec: {summary.get('spec_yaml', '')}")
    console.print(f"universe: {summary.get('universe_count')} 只 | "
                  f"{summary.get('date_start')} ~ {summary.get('date_end')} | "
                  f"rows={summary.get('panel_rows')} | null_ratio={summary.get('signal_null_ratio')}")
    ev = summary.get('evaluation', {})
    console.print(f"IC: {ev.get('ic')}")
    console.print(f"十分位 spread: {ev.get('decile_returns', {}).get('spread')}")
    console.print(f"换手: {ev.get('turnover')} | 覆盖: {ev.get('coverage')}")
    console.print(f"评估: ic={summary.get('evaluation', {}).get('ic')}")
    console.print(f"分层回测: {summary.get('evaluation', {}).get('layered_backtest', {}).get('summary', '无')}")


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


@app.command("corr")
def corr_factors(names: list[str] = typer.Argument(...)) -> None:
    """因子两两相关性：周度横截面秩相关均值 + 全局 Pearson。

    用法: factorlab corr <name1> <name2> [<name3>...]
    """
    if len(names) < 2:
        console.print("错误: 至少需要 2 个因子", style="red")
        raise typer.Exit(code=1)
    from factorlab.eval.correlation import factor_correlation
    try:
        m = factor_correlation(names, settings.results_dir)
    except FileNotFoundError as e:
        console.print(f"错误: {e}", style="red")
        raise typer.Exit(code=1)
    console.print(m.to_pandas().to_string(index=False))


@app.command("svd")
def svd_factors(names: list[str] = typer.Argument(None),
                weeks: int = typer.Option(15, "--weeks", help="抽样交易周数（内存护栏，默认 15）")) -> None:
    """因子库 SVD 分解：奇异值谱 + 主成分载荷（因子结构/有效维度分析）。

    用法: factorlab svd [name1 name2 ...] [--weeks 15]
    缺省 names = 全部有 panel 的因子（排除验证目录）。
    """
    from factorlab.eval.correlation import factor_svd
    from factorlab.config import settings as _settings
    results_dir = _settings.results_dir
    if not names:
        skip = {"acceptance", "demo_vol_skew", "m4b_smoke"}
        names = sorted(p.parent.name for p in results_dir.glob("*/panel.parquet")
                       if p.parent.name not in skip)
    if len(names) < 2:
        console.print("错误: 至少需要 2 个因子", style="red")
        raise typer.Exit(code=1)
    try:
        r = factor_svd(names, results_dir, sample_weeks=weeks)
    except FileNotFoundError as e:
        console.print(f"错误: {e}", style="red")
        raise typer.Exit(code=1)
    console.print(f"SVD（{len(names)} 因子，抽样 {weeks} 周）：")
    console.print("奇异值谱：")
    for k, (sv, cum) in enumerate(zip(r["singular_values"], r["cum_explained"]), 1):
        console.print(f"  PC{k:<2} 奇异值 {sv:8.3f}  累计解释 {cum * 100:5.1f}%")
    console.print("主成分载荷（每 PC 取 |载荷| 最大 5 因子）：")
    loadings = r["loadings"]
    for k in range(len(r["singular_values"])):
        pc = f"PC{k + 1}"
        ranked = sorted(loadings, key=lambda x: abs(x[pc]), reverse=True)[:5]
        parts = ", ".join(f"{x['name']}({x[pc]:+.2f})" for x in ranked)
        console.print(f"  {pc}: {parts}")


@app.command("serve")
def serve(port: int = 8000, host: str = "127.0.0.1") -> None:
    """启动 Web 可视化（只读 results_dir）。"""
    import uvicorn

    from factorlab.web.app import create_app
    uvicorn.run(create_app(settings.results_dir), host=host, port=port)
