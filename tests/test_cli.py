from typer.testing import CliRunner

from factorlab import __version__
from factorlab.cli.main import app


runner = CliRunner()


def test_version_command_prints_package_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
