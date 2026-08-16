import datetime
import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

from factorlab.engine.compute import RunContext, _formula_columns, run_factor
from factorlab.spec import load_spec

_DATES = ["20240102", "20240103", "20240104", "20240105", "20240108", "20240109"]
# 扩展交易日（>6 天场景：周频评估需要信号与 forward 同时有效的行，如 CLI run 测试）
_EXTRA_DATES = ["20240110", "20240111", "20240112", "20240115", "20240116", "20240117"]
# 平台库风格代码：ts_code 带后缀（000001.SZ），symbol 为纯数字桥梁
_A = ("000001", "000001.SZ", 10.0)
_B = ("600519", "600519.SH", 20.0)


def build_db(tmp_path, ex_date: bool = False, n_days: int = 6):
    """平台库风格假库：trade_date 'YYYYMMDD'/ts_code 带后缀/vol（参考 test_source.py 模式）；
    daily/adj_factor/daily_basic/stock_basic/stock_st/trade_cal 齐全。
    ex_date=True 时 000001 第 3 天（01-04）除权：close 11→8、adj 1.0→1.5。
    n_days 可扩展到 _DATES+_EXTRA_DATES 前缀（ex_date 固定 6 天）。"""
    if ex_date and n_days != 6:
        raise ValueError("ex_date 除权序列固定为 6 天")
    dates = (_DATES + _EXTRA_DATES)[:n_days]
    db = duckdb.connect(tmp_path / "q.duckdb")
    db.execute("CREATE TABLE daily (ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE)")
    for symbol, ts_code, base in (_A, _B):
        closes = [base + i + 1 for i in range(len(dates))]
        if ex_date and symbol == "000001":
            closes = [10.0, 11.0, 8.0, 9.0, 12.0, 13.0]
        for i, d in enumerate(dates):
            db.execute("INSERT INTO daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (ts_code, d, closes[i] - 1.0, closes[i] - 0.5, closes[i] - 1.5,
                        closes[i], closes[i] - 1.0, 1.0, 0.01, 1000.0, 1e6))
    db.execute("CREATE TABLE adj_factor (ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
    for symbol, ts_code, base in (_A, _B):
        adjs = [1.0] * len(dates)
        if ex_date and symbol == "000001":
            adjs = [1.0, 1.0, 1.5, 1.5, 1.5, 1.5]
        for i, d in enumerate(dates):
            db.execute("INSERT INTO adj_factor VALUES (?, ?, ?)", (ts_code, d, adjs[i]))
    db.execute("CREATE TABLE stock_basic (symbol VARCHAR, ts_code VARCHAR, exchange VARCHAR, list_date VARCHAR, industry VARCHAR)")
    db.execute("INSERT INTO stock_basic VALUES ('000001', '000001.SZ', 'SZSE', '19910101', '银行'), ('600519', '600519.SH', 'SSE', '20010101', '白酒')")
    db.execute("CREATE TABLE daily_basic (trade_date VARCHAR, ts_code VARCHAR, total_mv DOUBLE)")
    for d in dates:
        db.execute("INSERT INTO daily_basic VALUES (?, '000001.SZ', 100.0)", (d,))
        db.execute("INSERT INTO daily_basic VALUES (?, '600519.SH', 200.0)", (d,))
    db.execute("CREATE TABLE stock_st (ts_code VARCHAR, trade_date VARCHAR)")
    db.execute("CREATE TABLE trade_cal (cal_date VARCHAR, is_open INT)")
    for d in dates:
        db.execute("INSERT INTO trade_cal VALUES (?, 1)", (d,))
    db.close()


def _spec(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text("""
name: demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
process:
  - standardize()
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    return load_spec(path)


def test_run_factor_end_to_end(tmp_path):
    build_db(tmp_path)
    out_dir = tmp_path / "out"
    result = run_factor(_spec(tmp_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=out_dir))
    panel = result.panel
    assert "signal" in panel.columns and "forward_return_5d" in panel.columns
    assert panel.height > 0
    assert (out_dir / "panel.parquet").exists()
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["name"] == "demo"
    assert summary["universe_count"] == 2
    assert summary["panel_rows"] == panel.height
    assert summary["adjustment"] == "qfq"  # 默认复权口径写入摘要


def test_run_factor_empty_universe_rejected(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.universe.codes = ["999999.SZ"]  # 不存在
    with pytest.raises(ValueError, match="universe"):
        run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out2"))


def test_run_factor_float32_disabled(tmp_path):
    build_db(tmp_path)
    out_dir = tmp_path / "out"
    result = run_factor(_spec(tmp_path), RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=out_dir, float32=False))
    assert result.panel["close"].dtype == pl.Float64
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["float32"] is False


def test_run_factor_universe_override_file(tmp_path):
    build_db(tmp_path)
    pool = tmp_path / "pool_a.yaml"
    pool.write_text("codes: ['000001']", encoding="utf-8")
    out_dir = tmp_path / "out"
    result = run_factor(_spec(tmp_path), RunContext(
        db_path=tmp_path / "q.duckdb", output_dir=out_dir, universe_override=str(pool)))
    assert result.summary["universe_count"] == 1
    assert result.panel["code"].unique().to_list() == ["000001"]


def test_run_factor_empty_process_chain(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.process = []  # 无 process 链：signal 保持原始值
    out_dir = tmp_path / "out"
    result = run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=out_dir))
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["process"] == []
    assert result.panel["signal"].null_count() < result.panel.height


def test_run_factor_empty_date_range_rejected(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.date.start, spec.date.end = "2020-01-01", "2020-01-31"  # 库中无此范围数据
    with pytest.raises(ValueError, match="无数据"):
        run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out3"))


def test_run_factor_formula_without_close_rejected(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.formula = "signal = open"
    with pytest.raises(ValueError, match="close"):
        run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out4"))


def test_run_factor_factors_combine_rejected(tmp_path):
    build_db(tmp_path)
    path = tmp_path / "multi.yaml"
    path.write_text("""
name: multi
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
factors:
  - name: f1
    formula: signal = close
combine:
  method: equal_weight
""", encoding="utf-8")
    with pytest.raises(NotImplementedError, match="factors"):
        run_factor(load_spec(path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out5"))


def test_run_factor_neutralize_industry(tmp_path):
    # 回归：process 链 ctx（duckdb 连接）经 run_factor 完整链路可用（行业来自平台库 stock_basic）
    build_db(tmp_path)
    spec_path = tmp_path / "spec_n.yaml"
    spec_path.write_text("""
name: demo_n
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
process:
  - neutralize(by=industry)
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_n"))
    assert "signal" in result.panel.columns
    assert result.panel.height > 0


def test_run_factor_neutralize_size(tmp_path):
    # 回归：size 分支的日期 join key 必须与面板 date 同 dtype（run_factor 面板为 pl.Date，
    # 原 cast String 导致 SchemaError）；daily_basic 在 build_db fixture 中
    build_db(tmp_path)
    spec_path = tmp_path / "spec_size.yaml"
    spec_path.write_text("""
name: demo_size
category: custom
direction: 1
universe:
  codes: ["000001.SZ", "600519.SH"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
process:
  - neutralize(by=size)
formula: |
  signal = close / open - 1
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_s"))
    assert "signal" in result.panel.columns
    assert result.panel.height > 0
    # 每十分位组单只 → 组内 demean 恒 0（截面 N<10 已知局限）
    assert result.panel["signal"].abs().max() < 1e-9


def test_run_factor_missing_db(tmp_path):
    with pytest.raises(FileNotFoundError, match="nope.duckdb"):
        run_factor(_spec(tmp_path), RunContext(db_path=tmp_path / "nope.duckdb", output_dir=tmp_path / "out6"))


def test_run_factor_syntax_error_rejected(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.formula = "signal = (close"
    with pytest.raises(ValueError, match="语法错误"):
        run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out7"))


def test_run_factor_attribute_call_rejected(tmp_path):
    # 属性调用（np.abs）须在装配层被拒绝，而不是被 _formula_columns 误读为列名
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.formula = "signal = np.abs(close)"
    with pytest.raises(ValueError, match="属性调用"):
        run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out8"))


def test_run_factor_qfq_adjustment(tmp_path):
    # 除权日（adj 1.0→1.5, close 11→8）：qfq 下因子值连续（用 momentum 类公式验证）
    build_db(tmp_path, ex_date=True)
    spec_path = tmp_path / "spec_qfq.yaml"
    spec_path.write_text("""
name: demo_qfq
category: custom
direction: 1
universe:
  codes: ["000001.SZ"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
process: []
formula: |
  from polars_ta.prefix.wq import ts_delay
  signal = close / ts_delay(close, 1) - 1
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_qfq"))
    panel = result.panel.sort(["date"])
    a = panel.filter(pl.col("code") == "000001")
    # qfq 除权日收益 = 8×1.5/11 - 1（raw 口径会是 8/11 - 1）
    day3 = a.filter(pl.col("date") == datetime.date(2024, 1, 4))["signal"][0]
    assert day3 == pytest.approx(8 * 1.5 / 11 - 1)
    # 前向收益 total_return（raw close×adj 序列，含分红再投资）：13×1.5/10 - 1
    day1 = a.filter(pl.col("date") == datetime.date(2024, 1, 2))["forward_return_5d"][0]
    assert day1 == pytest.approx(13 * 1.5 / 10 - 1)
    summary = json.loads((tmp_path / "out_qfq" / "summary.json").read_text(encoding="utf-8"))
    assert summary["adjustment"] == "qfq"


def test_run_factor_default_db_is_platform():
    # RunContext 默认 db_path 指向平台库路径（旧只读库已废弃，平台库为唯一数据源）
    ctx = RunContext()
    assert ctx.db_path == Path("data/factorlab.duckdb")
    assert ctx.adjustment == "qfq"


def test_run_factor_future_calendar_days_not_padded(tmp_path):
    # trade_cal 含未来公告日（20261231）——run_factor 不应补全未来 null 行
    build_db(tmp_path)
    db = duckdb.connect(tmp_path / "q.duckdb")
    db.execute("INSERT INTO trade_cal VALUES ('20261231', 1)")
    db.close()
    spec_path = tmp_path / "spec_future.yaml"
    spec_path.write_text("""
name: demo_future
category: custom
direction: 1
universe:
  codes: ["000001.SZ"]
date:
  start: "2024-01-02"
process: []
formula: |
  signal = close
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_f"))
    assert datetime.date(2026, 12, 31) not in result.panel["date"]
    assert result.panel["date"].max() <= datetime.date.today()


def test_run_factor_consumes_operators_macros(tmp_path):
    # spec.operators 内联宏：mom_ratio(x, n) → delay(x, n)/delay(x, 2n) - 1 展开后计算正确
    build_db(tmp_path)
    spec_path = tmp_path / "spec_macro.yaml"
    spec_path.write_text("""
name: macro_demo
category: custom
direction: 1
universe:
  codes: ["000001.SZ"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
operators:
  mom_ratio:
    params: [x, n]
    formula: "delay(x, n) / delay(x, 2 * n) - 1"
formula: |
  from polars_ta.prefix.wq import ts_delay as delay
  signal = mom_ratio(close, 1)
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out"))
    assert result.panel.height > 0
    # 展开语义：mom_ratio(close, 1) → delay(close, 1)/delay(close, 2) - 1 = close[t-1]/close[t-2] - 1
    # 000001 收盘 11,12,13,14,15,16：第 3 个交易日（01-04）signal = 12/11 - 1
    a = result.panel.filter(pl.col("code") == "000001").sort("date")
    day3 = a.filter(pl.col("date") == datetime.date(2024, 1, 4))["signal"][0]
    assert day3 == pytest.approx(12 / 11 - 1)
    # delay(close, 2) 需要前 2 个交易日：前 2 日 signal 为 null
    assert a.head(2)["signal"].null_count() == 2


def test_run_factor_macro_formula_column_refs_loaded(tmp_path):
    # 宏公式内引用的数据列（volume）须纳入列加载（_formula_columns 在展开后提取）
    build_db(tmp_path)
    spec_path = tmp_path / "spec_macro_vol.yaml"
    spec_path.write_text("""
name: macro_vol
category: custom
direction: 1
universe:
  codes: ["000001.SZ"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
operators:
  vwap_ratio:
    params: [x]
    formula: "x * volume"
formula: |
  signal = vwap_ratio(close)
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_v"))
    assert result.panel.height > 0
    a = result.panel.filter(pl.col("code") == "000001").sort("date")
    # 展开后 signal = close * volume：首日 = 11 × 1000
    assert a["signal"][0] == pytest.approx(11 * 1000.0)


def test_run_factor_spec_adjustment_raw(tmp_path):
    # spec.adjustment 字段消费：声明 raw 时以 spec 为准（覆盖 qfq 默认），除权日保留假崩
    build_db(tmp_path, ex_date=True)
    spec_path = tmp_path / "spec_raw.yaml"
    spec_path.write_text("""
name: demo_raw
category: custom
direction: 1
universe:
  codes: ["000001.SZ"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
adjustment: raw
process: []
formula: |
  from polars_ta.prefix.wq import ts_delay
  signal = close / ts_delay(close, 1) - 1
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_raw"))
    panel = result.panel.sort(["date"])
    a = panel.filter(pl.col("code") == "000001")
    # raw：除权日 8/11 - 1（qfq 下会是 8×1.5/11 - 1）
    day3 = a.filter(pl.col("date") == datetime.date(2024, 1, 4))["signal"][0]
    assert day3 == pytest.approx(8 / 11 - 1)
    summary = json.loads((tmp_path / "out_raw" / "summary.json").read_text(encoding="utf-8"))
    assert summary["adjustment"] == "raw"


def test_run_factor_unknown_adjustment_rejected(tmp_path):
    build_db(tmp_path)
    spec = _spec(tmp_path)
    spec.adjustment = "bogus"  # spec 级声明非法口径（spec 默认 qfq，ctx 兜底不再生效）
    with pytest.raises(ValueError, match="view"):
        run_factor(spec, RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_x"))


def test_run_factor_pit_qfq_asof(tmp_path):
    # spec.adjustment=pit_qfq：view_prices asof=spec.date.end（研究日视角）——装配不崩且口径生效
    build_db(tmp_path, ex_date=True)
    spec_path = tmp_path / "spec_pit.yaml"
    spec_path.write_text("""
name: demo_pit
category: custom
direction: 1
universe:
  codes: ["000001.SZ"]
date:
  start: "2024-01-02"
  end: "2024-01-09"
adjustment: pit_qfq
process: []
formula: |
  from polars_ta.prefix.wq import ts_delay
  signal = close / ts_delay(close, 1) - 1
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_pit"))
    assert result.panel.height > 0
    a = result.panel.filter(pl.col("code") == "000001").sort("date")
    # asof=2024-01-09（adj=1.5）：除权日 01-04 因子 = 8×1.5/11 - 1（raw 口径会是 8/11 - 1）
    day3 = a.filter(pl.col("date") == datetime.date(2024, 1, 4))["signal"][0]
    assert day3 == pytest.approx(8 * 1.5 / 11 - 1)
    summary = json.loads((tmp_path / "out_pit" / "summary.json").read_text(encoding="utf-8"))
    assert summary["adjustment"] == "pit_qfq"


def test_run_factor_pit_qfq_without_date_end(tmp_path):
    # 边界：spec.date.end 为空时 asof 回落面板最大日期（不崩）
    build_db(tmp_path, ex_date=True)
    spec_path = tmp_path / "spec_pit_noend.yaml"
    spec_path.write_text("""
name: demo_pit_noend
category: custom
direction: 1
universe:
  codes: ["000001.SZ"]
date:
  start: "2024-01-02"
adjustment: pit_qfq
process: []
formula: |
  signal = close
""", encoding="utf-8")
    result = run_factor(load_spec(spec_path), RunContext(db_path=tmp_path / "q.duckdb", output_dir=tmp_path / "out_pit2"))
    assert result.panel.height > 0
    summary = json.loads((tmp_path / "out_pit2" / "summary.json").read_text(encoding="utf-8"))
    assert summary["adjustment"] == "pit_qfq"


def test_formula_columns_extracts_data_cols_only():
    formula = '''
from polars_ta.prefix.wq import ts_mean, ts_delay

def helper(x, n):
    return ts_mean(x, n)

_vol = helper(close, 20)
_mom = ts_delay(close, 1)
signal = abs(_vol) + _mom * open - if_else(close > open, 1, 0)
'''
    # def 名/参数、import 名、算子调用名、_ 前缀中间变量、signal 均排除
    assert _formula_columns(formula) == ["close", "open"]


def test_formula_columns_excludes_date_code():
    assert _formula_columns("signal = close / open - 1") == ["close", "open"]
    assert _formula_columns("signal = close / date") == ["close"]


def test_formula_columns_assign_intermediate_variable():
    # 回归：赋值中间变量（非下划线，如 ret）不能误判为数据列（否则 load_daily 报「未知列名: ['ret']」）
    assert _formula_columns("ret = ts_delay(close, 1)\nsignal = ret") == ["close"]
    assert _formula_columns("ret = close * 2\nsignal = ret + open") == ["close", "open"]
    # AnnAssign 目标名同样纳入 defined（target 为单个，非 targets 列表）
    assert _formula_columns("ret: float = close * 2\nsignal = ret") == ["close"]
