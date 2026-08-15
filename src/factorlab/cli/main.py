from pathlib import Path

import typer
from rich.console import Console

from factorlab import __version__
from factorlab.config import settings
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
