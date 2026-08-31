"""factorlab run 命令测试：help、tmp 平台库端到端落盘（含 evaluation）、--set 变体、错误路径。"""
import json

import polars as pl
import pytest
import yaml
from typer.testing import CliRunner

from factorlab.cli.main import app
from test_run_factor import build_db

runner = CliRunner()


def test_run_help():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    for opt in ("--universe", "--max-memory", "--output-dir", "--backtest", "--no-backtest", "--groups", "--set"):
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
    assert summary["codes"] == ["600519.SH"]


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
    assert summary["codes"] == ["000001.SZ"]


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


def test_run_backtest_flag(tmp_path, monkeypatch):
    # --backtest（默认）：summary.evaluation 含 layered_backtest；--output-dir 缺省 results_dir/<name>
    # 9 个交易日：第 1 个 ISO 周（01-05）的 forward 在面板内 → 1 个有效周，
    # 回测期数 = 评估周数（无效周不计，M4b 期数口径）
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
  signal = close / open - 1
""", encoding="utf-8")
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path / "results")
    result = runner.invoke(app, ["run", str(spec_path)])
    assert result.exit_code == 0, result.output
    summary = json.loads((tmp_path / "results" / "demo" / "summary.json").read_text(encoding="utf-8"))
    assert "layered_backtest" in summary["evaluation"]
    assert summary["evaluation"]["layered_backtest"]["n_groups"] == 10
    assert summary["evaluation"]["layered_backtest"]["periods"] == summary["evaluation"]["n_weeks"] == 1


def test_run_no_backtest_flag(tmp_path, monkeypatch):
    # --no-backtest：跳过 layered_backtest（评估仍在），weekly 落盘不受开关影响
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
    out_dir = tmp_path / "out_nobt"
    result = runner.invoke(app, ["run", "--no-backtest", str(spec_path), "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert "evaluation" in summary
    assert "layered_backtest" not in summary["evaluation"]
    assert (out_dir / "weekly.parquet").exists()


def test_run_groups_param(tmp_path, monkeypatch):
    # --groups 传递到 layered_backtest.n_groups
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
  signal = close / open - 1
""", encoding="utf-8")
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    out_dir = tmp_path / "out_g"
    result = runner.invoke(app, ["run", "--groups", "5", str(spec_path), "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["evaluation"]["layered_backtest"]["n_groups"] == 5


def test_run_groups_invalid_rejected(tmp_path, monkeypatch):
    # 边界：--groups < 2 在 typer 解析期拒绝（分层回测至少 2 档）
    build_db(tmp_path)
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
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    result = runner.invoke(app, ["run", "--groups", "1", str(spec_path)])
    assert result.exit_code != 0
    assert "groups" in result.output


def test_run_weekly_parquet_is_weekly_aligned(tmp_path, monkeypatch):
    # weekly.parquet 为周频对齐面板（行数 = 周数 × 股票数），不再冗余日频（panel.parquet 保留日频）
    build_db(tmp_path, n_days=9)  # 9 交易日 = 2 个 ISO 周（01-05 / 01-12 各为周内最后交易日）
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
  signal = close / open - 1
""", encoding="utf-8")
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    out_dir = tmp_path / "out_weekly"
    result = runner.invoke(app, ["run", str(spec_path), "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    weekly = pl.read_parquet(out_dir / "weekly.parquet")
    assert weekly.height == 2 * 2  # 2 周 × 2 只
    daily = pl.read_parquet(out_dir / "panel.parquet")
    assert daily.height == 9 * 2
    assert daily.height > weekly.height


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


def test_run_set_param_variant(tmp_path, monkeypatch):
    # --set win=2 → 变体名 demo_win2 + results 独立目录；默认变体（无 --set）并存不覆盖
    # 覆盖生效证明（计算层面）：默认 win=20 窗口 > 9 交易日 → signal 全 null（ratio=1.0）；
    # --set win=2 → 仅每资产头部 2 行 null（ratio=4/18）
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
params: {win: 20}
formula: |
  signal = close / ts_delay(close, ${win}) - 1
""", encoding="utf-8")
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path / "results")
    # 默认变体：params 原样（win=20 → 全 null）
    result = runner.invoke(app, ["run", str(spec_path)])
    assert result.exit_code == 0, result.output
    default_dir = tmp_path / "results" / "demo"
    assert (default_dir / "summary.json").exists()
    default_summary = json.loads((default_dir / "summary.json").read_text(encoding="utf-8"))
    assert default_summary["signal_null_ratio"] == 1.0
    assert yaml.safe_load(default_summary["spec_yaml"])["params"] == {"win": 20}
    # --set 变体：独立目录 + 覆盖值进入计算
    result = runner.invoke(app, ["run", str(spec_path), "--set", "win=2"])
    assert result.exit_code == 0, result.output
    variant_dir = tmp_path / "results" / "demo_win2"
    assert (variant_dir / "summary.json").exists()
    assert (variant_dir / "panel.parquet").exists()
    summary = json.loads((variant_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["signal_null_ratio"] == pytest.approx(4 / 18, abs=1e-4)  # 2 只 × 头部 2 天 null
    assert yaml.safe_load(summary["spec_yaml"])["params"] == {"win": 2}  # values 合并进 spec.params
    # 变体名回显到 stdout；默认变体目录未受影响
    assert "demo_win2" in result.stdout
    assert (default_dir / "summary.json").exists()


def test_run_set_multiple_typed_values(tmp_path, monkeypatch):
    # --set 可多次；int/float/bool/str 解析；变体名按 k+v 拼接（values 合并进 spec.params）
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
params: {win: 20, gain: 2.0, tag: "base"}
formula: |
  signal = close / open - 1 + ${gain} * 0
""", encoding="utf-8")
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    monkeypatch.setattr("factorlab.config.settings.results_dir", tmp_path / "results")
    result = runner.invoke(app, [
        "run", str(spec_path),
        "--set", "win=100", "--set", "gain=2.5",
        "--set", "fast=true", "--set", "tag=abc",
    ])
    assert result.exit_code == 0, result.output
    variant_dir = tmp_path / "results" / "demo_win100_gain2.5_fastTrue_tagabc"
    assert (variant_dir / "summary.json").exists()
    summary = json.loads((variant_dir / "summary.json").read_text(encoding="utf-8"))
    params = yaml.safe_load(summary["spec_yaml"])["params"]
    assert params["win"] == 100 and params["gain"] == 2.5  # int/float 解析
    assert params["fast"] is True and params["tag"] == "abc"  # bool/str 解析
    assert "demo_win100_gain2.5_fastTrue_tagabc" in result.stdout


def test_run_set_bad_format_rejected(tmp_path, monkeypatch):
    # 边界：--set 缺 =（win100）或空值（win=）→ 非 0 退出并提示格式
    build_db(tmp_path)
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
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    for kv in ("win100", "win="):
        result = runner.invoke(app, ["run", str(spec_path), "--set", kv])
        assert result.exit_code != 0, kv
        assert "--set" in result.output
        assert kv in result.output


def test_run_help_chunk_options():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    for opt in ("--chunk-days", "--warmup-days"):
        assert opt in result.stdout


def test_run_chunked_end_to_end(tmp_path, monkeypatch):
    # --chunk-days 接线：分块跑通并落盘（9 天、chunk 2 → 5 块）
    build_db(tmp_path, n_days=9)
    spec_path = tmp_path / "demo_chunk.yaml"
    spec_path.write_text("""
name: demo_chunk
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
    monkeypatch.setattr("factorlab.config.settings.platform_db", tmp_path / "q.duckdb")
    out_dir = tmp_path / "results" / "demo_chunk"
    result = runner.invoke(app, [
        "run", str(spec_path), "--chunk-days", "2", "--warmup-days", "1",
        "--output-dir", str(out_dir), "--no-backtest"])
    assert result.exit_code == 0, result.output
    assert (out_dir / "panel.parquet").exists()
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["panel_rows"] == 9 * 2
