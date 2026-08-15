import typer

from factorlab import __version__


app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """factorlab 因子 DSL 计算平台"""


@app.command()
def version() -> None:
    typer.echo(__version__)
