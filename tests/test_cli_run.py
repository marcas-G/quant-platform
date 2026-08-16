"""factorlab run 命令测试：help、tmp 平台库端到端落盘（含 evaluation）、错误路径。"""
import json

from typer.testing import CliRunner

from factorlab.cli.main import app
from test_run_factor import build_db

runner = CliRunner()


def test_run_help():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    for opt in ("--universe", "--max-memory", "--output-dir"):
        assert opt in result.stdout


def test_run_end_to_end(tmp_path, monkeypatch):
    # 平台库风格 tmp 库 + spec → run 落盘（panel/weekly/summary，summary 含 evaluation）
    # 9 个交易日：align_weekly 取周内最后交易日（01-05），其 forward_return_5d 需 t+5
    # （01-12）在面板内——9 天恰好使第 1 个 ISO 周有 2 行有效，n_weeks=1
    build_db(tmp_path, n_days=9)
    spec_path = tmp_path / "demo.yaml"
    spec_path.write_text("""
name: demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
date:
  start: "2024-01-02"
  end: "2024-01-12"
formula: |
  signal = close / ts_delay(close, 1) - 1
""", encoding="utf-8")
    # run 命令在调用时读取 settings.platform_db——monkeypatch 指向 tmp 库
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    out_dir = tmp_path / "results" / "demo"
    result = runner.invoke(app, ["run", str(spec_path), "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert (out_dir / "panel.parquet").exists()
    assert (out_dir / "weekly.parquet").exists()
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["name"] == "demo"
    assert "evaluation" in summary
    assert summary["evaluation"]["n_weeks"] >= 1
    # 评估信息回显到 stdout
    assert "n_weeks=" in result.stdout


def test_run_universe_override(tmp_path, monkeypatch):
    # --universe 覆盖 spec.codes（6 位代码直通），默认回落 settings.default_universe
    build_db(tmp_path)
    spec_path = tmp_path / "demo.yaml"
    spec_path.write_text("""
name: demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    out_dir = tmp_path / "results" / "demo"
    result = runner.invoke(app, ["run", str(spec_path), "--universe", "600519", "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["universe_count"] == 1
    assert summary["codes"] == ["600519"]


def test_run_default_universe_wired(tmp_path, monkeypatch):
    # FACTORLAB_DEFAULT_UNIVERSE（settings.default_universe）接线：--universe 缺省时生效
    build_db(tmp_path)
    spec_path = tmp_path / "demo.yaml"
    spec_path.write_text("""
name: demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    monkeypatch.setattr("factorlab.config.settings.default_universe", "000001")
    out_dir = tmp_path / "results" / "demo"
    result = runner.invoke(app, ["run", str(spec_path), "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["universe_count"] == 1
    assert summary["codes"] == ["000001"]


def test_run_missing_spec(tmp_path):
    result = runner.invoke(app, ["run", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0
    assert "nope.yaml" in result.output


def test_run_missing_db(tmp_path, monkeypatch):
    spec_path = tmp_path / "demo.yaml"
    spec_path.write_text("""
name: demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ"]
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "nope.duckdb")
    result = runner.invoke(app, ["run", str(spec_path)])
    assert result.exit_code != 0
    assert "nope.duckdb" in result.output


def test_run_empty_universe(tmp_path, monkeypatch):
    build_db(tmp_path)
    spec_path = tmp_path / "demo.yaml"
    spec_path.write_text("""
name: demo
category: custom
direction: 1
universe:
  codes: ["999999.SZ"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    result = runner.invoke(app, ["run", str(spec_path)])
    assert result.exit_code != 0
    assert "universe" in result.output
