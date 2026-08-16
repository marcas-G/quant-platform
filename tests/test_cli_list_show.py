"""factorlab list/show 命令测试：列表摘要、空目录、详情展示、缺失报错、mtime 兜底、损坏 JSON。"""
import json
import os
from pathlib import Path

from typer.testing import CliRunner

from factorlab.cli.main import app

runner = CliRunner()


def _write_summary(results_dir: Path, name: str, **overrides):
    out = results_dir / name
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "name": name, "category": "custom", "direction": 1,
        "universe_count": 5, "panel_rows": 100,
        "evaluation": {"ic": {"mean": 0.05}, "decile_returns": {"spread": {"ret": 0.02}}},
        "timestamp": "2026-08-16T12:00:00",
    }
    summary.update(overrides)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


def test_list_shows_factors(monkeypatch, tmp_path):
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path)
    _write_summary(tmp_path, "alpha_1")
    _write_summary(tmp_path, "beta_2")
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "alpha_1" in result.stdout and "beta_2" in result.stdout
    assert "0.05" in result.stdout  # IC 摘要


def test_list_empty_results(monkeypatch, tmp_path):
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path / "nope")
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "暂无" in result.stdout


def test_show_factor_summary(monkeypatch, tmp_path):
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path)
    _write_summary(tmp_path, "alpha_1")
    result = runner.invoke(app, ["show", "alpha_1"])
    assert result.exit_code == 0
    assert "alpha_1" in result.stdout and "0.05" in result.stdout


def test_show_missing_factor(monkeypatch, tmp_path):
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path)
    result = runner.invoke(app, ["show", "ghost"])
    assert result.exit_code == 1
    assert "ghost" in result.stdout


def test_list_falls_back_to_mtime_without_timestamp(monkeypatch, tmp_path):
    # 边界：M4a run 落盘的 summary 无 timestamp 字段——list 用 summary.json 文件 mtime 兜底
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path)
    _write_summary(tmp_path, "old_1", timestamp=None)
    _write_summary(tmp_path, "new_2", timestamp=None)
    old_path = tmp_path / "old_1" / "summary.json"
    mtime = old_path.stat().st_mtime
    os.utime(old_path, (mtime - 3600, mtime - 3600))  # old_1 拨回 1 小时前，排序确定
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "old_1" in result.stdout and "new_2" in result.stdout
    assert result.stdout.index("new_2") < result.stdout.index("old_1")  # 新运行在前


def test_list_skips_corrupt_summary(monkeypatch, tmp_path):
    # 边界：目录内存在损坏 summary.json 时跳过，其余因子正常列出
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path)
    _write_summary(tmp_path, "alpha_1")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "summary.json").write_text("{not json", encoding="utf-8")
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "alpha_1" in result.stdout
    assert "broken" not in result.stdout


def test_show_corrupt_summary(monkeypatch, tmp_path):
    # 错误路径：show 的 summary.json 损坏 → 报错 exit 1（不崩栈）
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "summary.json").write_text("{not json", encoding="utf-8")
    result = runner.invoke(app, ["show", "broken"])
    assert result.exit_code == 1
