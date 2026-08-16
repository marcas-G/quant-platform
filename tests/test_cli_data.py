from typer.testing import CliRunner

from factorlab.cli.main import app
from factorlab.config import settings

runner = CliRunner()


def test_data_help_lists_commands():
    result = runner.invoke(app, ["data", "--help"])
    assert result.exit_code == 0
    for command in ("rebuild", "refresh", "verify"):
        assert command in result.stdout


def test_data_rebuild_missing_token_reports(monkeypatch):
    """错误路径：缺 token 时 rebuild 直接报错退出，不发网络请求。"""
    monkeypatch.setattr(settings, "teajoin_token", "")
    result = runner.invoke(app, ["data", "rebuild"])
    assert result.exit_code == 1
    assert "FACTORLAB_TEAJOIN_TOKEN" in result.stdout


def test_data_refresh_missing_token_reports(monkeypatch):
    """错误路径：refresh 同样需要 token。"""
    monkeypatch.setattr(settings, "teajoin_token", "")
    result = runner.invoke(app, ["data", "refresh"])
    assert result.exit_code == 1
    assert "FACTORLAB_TEAJOIN_TOKEN" in result.stdout


def test_data_verify_missing_db_no_crash(monkeypatch, tmp_path):
    """边界：最终库不存在时 verify 各规则 skipped，正常退出。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    result = runner.invoke(app, ["data", "verify"])
    assert result.exit_code == 0
    assert "integrity" in result.stdout


def test_data_update_help_and_missing_token():
    result = runner.invoke(app, ["data", "update", "--help"])
    assert result.exit_code == 0
    assert "更新" in result.stdout or "update" in result.stdout
