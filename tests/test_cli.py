from typer.testing import CliRunner
import textwrap
import yaml

from factorlab import __version__
from factorlab.cli.main import app
from factorlab.ops import registry


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


def test_op_list_empty(monkeypatch, tmp_path):
    registry.reset_registry()
    monkeypatch.setattr("factorlab.config.settings.plugin_dir", tmp_path)
    result = runner.invoke(app, ["op", "list"])
    assert result.exit_code == 0


def test_op_add_and_remove(tmp_path):
    registry.reset_registry()
    plugin_path = tmp_path / "my_op.py"
    plugin_path.write_text(textwrap.dedent('''
        import polars as pl
        from factorlab.ops.registry import factor_op

        @factor_op("cli_dummy", kind="el", version="0.1.0")
        def cli_dummy(x: pl.Expr) -> pl.Expr:
            return x
    '''), encoding="utf-8")

    from factorlab.config import settings
    original = settings.plugin_dir
    settings.plugin_dir = tmp_path
    try:
        add = runner.invoke(app, ["op", "add", str(plugin_path)])
        assert add.exit_code == 0
        remove = runner.invoke(app, ["op", "remove", "cli_dummy"])
        assert remove.exit_code == 0
    finally:
        settings.plugin_dir = original


def test_op_doc_prints_registered_operator(tmp_path):
    registry.reset_registry()
    plugin_path = tmp_path / "doc_op.py"
    plugin_path.write_text(textwrap.dedent('''
        import polars as pl
        from factorlab.ops.registry import factor_op

        @factor_op("doc_dummy", kind="el", version="0.2.0")
        def doc_dummy(x: pl.Expr) -> pl.Expr:
            """return input unchanged"""
            return x
    '''), encoding="utf-8")

    from factorlab.config import settings
    original = settings.plugin_dir
    settings.plugin_dir = tmp_path
    try:
        assert runner.invoke(app, ["op", "add", str(plugin_path)]).exit_code == 0
        result = runner.invoke(app, ["op", "doc", "doc_dummy"])
        assert result.exit_code == 0
        assert "doc_dummy" in result.stdout
        assert "0.2.0" in result.stdout
    finally:
        settings.plugin_dir = original


def test_m1_cli_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("version", "lint", "op"):
        assert command in result.stdout
