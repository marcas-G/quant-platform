from pathlib import Path

import typer
from rich.console import Console

from factorlab import __version__
from factorlab.factor.errors import FactorDSLError
from factorlab.factor.ast_gate import validate_formula
from factorlab.spec import load_spec


app = typer.Typer(no_args_is_help=True)
console = Console()


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
