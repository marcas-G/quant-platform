from typer.testing import CliRunner

from factorlab.cli.main import app


runner = CliRunner()


def test_serve_help():
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.stdout
