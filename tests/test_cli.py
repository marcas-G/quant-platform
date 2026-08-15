from typer.testing import CliRunner
import yaml

from factorlab import __version__
from factorlab.cli.main import app


runner = CliRunner()


def test_version_command_prints_package_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_lint_valid_spec(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(yaml.safe_dump({
        "name": "demo",
        "category": "custom",
        "direction": 1,
        "universe": {"codes": ["000001.SZ"]},
        "formula": "signal = close / open - 1",
    }, allow_unicode=True), encoding="utf-8")
    result = runner.invoke(app, ["lint", str(spec)])
    assert result.exit_code == 0
    assert "OK" in result.stdout


def test_lint_rejects_forbidden_import(tmp_path):
    spec = tmp_path / "bad.yaml"
    spec.write_text(yaml.safe_dump({
        "name": "bad",
        "category": "custom",
        "direction": 1,
        "universe": {"rules": {"exclude_st": True}},
        "formula": "import os\nsignal = close",
    }, allow_unicode=True), encoding="utf-8")
    result = runner.invoke(app, ["lint", str(spec)])
    assert result.exit_code != 0
    assert "禁止导入" in result.stdout
