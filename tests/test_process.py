import polars as pl
import pytest

from factorlab.process.registry import get_processor, parse_chain_item, run_process_chain
from factorlab.process import processors  # noqa: F401  # 注册副作用


def test_parse_chain_item_keyword():
    assert parse_chain_item("winsorize(quantile=0.99)") == ("winsorize", {"quantile": 0.99})


def test_parse_chain_item_no_args():
    assert parse_chain_item("standardize()") == ("standardize", {})


def test_parse_chain_item_positional_and_types():
    name, kwargs = parse_chain_item("clip(-3, 3)")
    assert name == "clip" and kwargs["lower"] == -3.0 and kwargs["upper"] == 3.0


def test_parse_chain_item_edges():
    # bool/字符串字面量
    assert parse_chain_item("foo(flag=true, name=abc)") == ("foo", {"flag": True, "name": "abc"})
    # key=value 与位置参数混用（位置参数按序命名 lower/upper/value）
    assert parse_chain_item("clip(-3, upper=3)") == ("clip", {"lower": -3, "upper": 3})
    # 无括号裸名视为无参
    assert parse_chain_item("winsorize") == ("winsorize", {})
    # 多余逗号（空参数段）拒绝
    with pytest.raises(ValueError):
        parse_chain_item("clip(-3, 3,)")
    # 纯空白项拒绝
    with pytest.raises(ValueError):
        parse_chain_item("   ")


def test_parse_chain_item_invalid():
    with pytest.raises(ValueError):
        parse_chain_item("winsorize(quantile=")


def test_unknown_processor_rejected():
    with pytest.raises(KeyError, match="nope"):
        get_processor("nope")


def test_run_chain_applies_sequentially():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
        "code": ["A", "B", "A", "B"],
        "signal": [1.0, 1000.0, 2.0, 3.0],
    })
    out = run_process_chain(df, ["winsorize(quantile=0.5)", "standardize()"], ctx=None)
    assert out.columns == ["date", "code", "signal"]
    assert out["signal"].abs().max() < 5  # 去极值后 z-score 有界


def _panel():
    return pl.DataFrame({
        "date": ["2024-01-02"] * 4 + ["2024-01-03"] * 4,
        "code": ["A", "B", "C", "D"] * 2,
        "signal": [1.0, 2.0, 3.0, 100.0, 1.0, 2.0, 3.0, 4.0],
    })


def test_winsorize_clips_extremes():
    out = run_process_chain(_panel(), ["winsorize(quantile=0.5)"], ctx=None)
    assert out["signal"].max() < 100.0


def test_standardize_cross_section():
    out = run_process_chain(_panel(), ["standardize()"], ctx=None)
    per_date = out.group_by("date").agg(
        mean=pl.col("signal").mean(),
        std=pl.col("signal").std(),
    )
    assert per_date["mean"].abs().max() < 1e-9
    assert per_date["std"].abs().max() > 0.9


def test_csranknorm_in_unit_interval():
    out = run_process_chain(_panel(), ["csranknorm()"], ctx=None)
    assert out["signal"].min() > 0.0 and out["signal"].max() < 1.0  # rank/(N+1) 最大 N/(N+1) < 1


def test_robustzscore_bounds_extremes():
    out = run_process_chain(_panel(), ["robustzscore()"], ctx=None)
    # 01-02 截面 [1,2,3,100]：中位数 2.5、MAD 1.0，极端值 100.0 → 稳健 z ≈ 65.8
    # （标准 MAD 公式下 <10 在数学上不可能）；断言极端值仍远小于原始幅度、其余在 ±1 附近
    abs_sig = out["signal"].abs()
    assert abs_sig.max() < 100.0
    assert abs_sig.filter(abs_sig < abs_sig.max()).max() < 1.1


def test_clip_bounds():
    out = run_process_chain(_panel(), ["clip(-1, 1)"], ctx=None)
    assert out["signal"].min() >= -1.0 and out["signal"].max() <= 1.0


def test_fillna_value():
    df = _panel().with_columns(pl.when(pl.col("code") == "D").then(None).otherwise(pl.col("signal")).alias("signal"))
    out = run_process_chain(df, ["fillna(method=value, value=0.0)"], ctx=None)
    assert out["signal"].null_count() == 0
    assert out.filter(pl.col("code") == "D")["signal"].to_list() == [0.0, 0.0]


def test_fillna_forward_within_asset():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        "code": ["A", "A", "A", "A"],
        "signal": [1.0, None, 3.0, None],
    })
    out = run_process_chain(df, ["fillna(method=forward)"], ctx=None)
    assert out["signal"].to_list() == [1.0, 1.0, 3.0, 3.0]


def test_fillna_invalid_method():
    with pytest.raises(ValueError, match="fillna"):
        run_process_chain(_panel(), ["fillna(method=bogus)"], ctx=None)


def test_parse_chain_item_colon_separator():
    assert parse_chain_item("neutralize(by: industry)") == ("neutralize", {"by": "industry"})


def test_parse_chain_item_bad_key_rejected():
    with pytest.raises(ValueError):
        parse_chain_item("clip(=3)")


def test_parse_chain_item_keyword_before_positional_rejected():
    with pytest.raises(ValueError):
        parse_chain_item("clip(upper=3, -3)")


def test_run_chain_requires_signal_column():
    df = pl.DataFrame({"date": ["2024-01-02"], "code": ["A"]})
    with pytest.raises(ValueError, match="signal"):
        run_process_chain(df, ["standardize()"], ctx=None)


def test_fillna_forward_no_cross_asset_leak():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
        "code": ["A", "A", "B", "B"],
        "signal": [1.0, None, None, 4.0],
    })
    out = run_process_chain(df, ["fillna(method=forward)"], ctx=None)
    assert out.filter(pl.col("code") == "A")["signal"].to_list() == [1.0, 1.0]
    assert out.filter(pl.col("code") == "B")["signal"].to_list() == [None, 4.0]  # B 首行不借用 A


def test_zscore_alias_registered():
    assert get_processor("zscore").name == "zscore"


def test_winsorize_rejects_quantile_one():
    with pytest.raises(ValueError):
        run_process_chain(_panel(), ["winsorize(quantile=1.0)"], ctx=None)


def test_standardize_null_preserved_for_constant_section():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
        "code": ["A", "B", "A", "B"],
        "signal": [5.0, 5.0, 1.0, 2.0],
    })
    out = run_process_chain(df, ["standardize()"], ctx=None)
    a2 = out.filter((pl.col("code") == "A") & (pl.col("date") == "2024-01-02"))["signal"]
    assert a2.to_list() == [None]  # 01-02 截面零方差 → null
    assert out["signal"].drop_nulls().len() == 2


def test_robustzscore_null_for_mad_zero_section():
    df = pl.DataFrame({
        "date": ["2024-01-02", "2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
        "code": ["A", "B", "C", "A", "B"],
        "signal": [5.0, 5.0, 5.0, 1.0, 2.0],
    })
    out = run_process_chain(df, ["robustzscore()"], ctx=None)
    sec1 = out.filter(pl.col("date") == "2024-01-02")["signal"]
    assert sec1.to_list() == [None, None, None]  # MAD=0 截面 → null（不产生 inf）
    assert out["signal"].drop_nulls().len() == 2  # 01-03 截面 [1,2] MAD>0 → 有值


from dataclasses import dataclass
import duckdb

@dataclass
class FakeCtx:
    db: duckdb.DuckDBPyConnection | None = None


def build_basic_db(tmp_path):
    db = duckdb.connect(tmp_path / "t.duckdb")
    db.execute("CREATE TABLE stock_basic_tushare (symbol VARCHAR, industry VARCHAR)")
    db.execute("INSERT INTO stock_basic_tushare VALUES ('A', '银行'), ('B', '银行'), ('C', '白酒'), ('D', '白酒')")
    db.execute("CREATE TABLE daily_basic (trade_date VARCHAR, ts_code VARCHAR, total_mv DOUBLE)")
    db.execute("INSERT INTO daily_basic VALUES ('20240102', '000001.SZ', 100.0), ('20240103', '000001.SZ', 120.0)")
    db.close()
    return tmp_path / "t.duckdb"


def test_neutralize_market_demean():
    df = _panel()
    out = run_process_chain(df, ["neutralize(by=market)"], ctx=None)
    per_date = out.group_by("date").agg(pl.col("signal").mean())
    assert per_date["signal"].abs().max() < 1e-9


def test_neutralize_industry_group_mean_zero(tmp_path):
    db_path = build_basic_db(tmp_path)
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = _panel()
        out = run_process_chain(df, ["neutralize(by: industry)"], ctx=con)
    finally:
        con.close()
    # A/B 同行业（银行）组内均值应为 0；C/D 同行业（白酒）同理
    means = out.join(
        pl.DataFrame({"code": ["A", "B"], "industry": ["银行", "银行"]}),
        on="code",
    ).group_by("date").agg(pl.col("signal").mean())
    assert means["signal"].abs().max() < 1e-9


def test_neutralize_unknown_by():
    with pytest.raises(ValueError, match="neutralize"):
        run_process_chain(_panel(), ["neutralize(by=bogus)"], ctx=None)


def test_neutralize_requires_db_context():
    with pytest.raises(ValueError, match="ctx"):
        run_process_chain(_panel(), ["neutralize(by: industry)"], ctx=None)


def test_fillna_industry_mean(tmp_path):
    db_path = build_basic_db(tmp_path)
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = _panel().with_columns(
            pl.when(pl.col("code") == "D").then(None).otherwise(pl.col("signal")).alias("signal")
        )
        out = run_process_chain(df, ["fillna(method: industry_mean)"], ctx=con)
    finally:
        con.close()
    assert out["signal"].null_count() == 0
    # D 属于白酒组（C/D），组内均值 (3+100)/2=51.5 填 D 的 null——但 100 是极端值？
    # 注意：组内均值包含 D 自身的 null（不计入），用 C 的 3.0 与 A/B 无关
    # 更稳的断言：D 的填充值 = C 在对应日期的值（同组唯一非 null）
    d_vals = out.filter(pl.col("code") == "D")["signal"].to_list()
    c_vals = out.filter(pl.col("code") == "C")["signal"].to_list()
    assert d_vals == c_vals


def test_neutralize_size_decile_demean(tmp_path):
    # 按 date 内 total_mv 排名十分位分桶、组内 demean：
    # 20 只市值各异的股票 → 每分位组恰好 2 只 → demean 后恰为 ±0.5（非退化、非全零）；
    # 第二日市值顺序反转 → 分桶结果不变 → 验证分组按日期隔离（不跨日期泄漏）。
    db_path = build_basic_db(tmp_path)
    db = duckdb.connect(str(db_path))  # 可写连接重建 daily_basic（只读连接禁止写）
    db.execute("DROP TABLE IF EXISTS daily_basic")
    db.execute("CREATE TABLE daily_basic (trade_date VARCHAR, ts_code VARCHAR, total_mv DOUBLE)")
    for i in range(20):
        db.execute("INSERT INTO daily_basic VALUES ('20240102', ?, ?)", (f"{chr(ord('A') + i)}.SZ", float(i + 1) * 10.0))
        db.execute("INSERT INTO daily_basic VALUES ('20240103', ?, ?)", (f"{chr(ord('A') + i)}.SZ", float(20 - i) * 10.0))
    db.close()
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = pl.DataFrame({
            "date": ["2024-01-02"] * 20 + ["2024-01-03"] * 20,
            "code": [chr(ord("A") + i) for i in range(20)] * 2,
            "signal": [float(i) for i in range(20)] * 2,
        })
        out = run_process_chain(df, ["neutralize(by: size)"], ctx=con)
    finally:
        con.close()
    assert out["signal"].abs().max() > 0.1  # 非退化：不是全 0
    assert set(out["signal"].to_list()) == {-0.5, 0.5}  # 每分位组 2 只 → 恰好 ±0.5
    per_date = out.group_by("date").agg(pl.col("signal").mean())
    assert per_date["signal"].abs().max() < 1e-9  # 各分位组均值 0 → 每日截面和 0


def test_neutralize_size_missing_mv_raises(tmp_path):
    # daily_basic 无匹配（total_mv 为 null）→ 报错而非静默 demean 0（M3a spec §5）
    db_path = build_basic_db(tmp_path)  # daily_basic 只有 000001.SZ，_panel 的 A/B/C/D 全部缺失
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        with pytest.raises(ValueError, match="total_mv"):
            run_process_chain(_panel(), ["neutralize(by: size)"], ctx=con)
    finally:
        con.close()


def test_neutralize_industry_missing_info(tmp_path):
    # 股票不在 stock_basic_tushare → 行业缺失 → 报错（不做静默按全截面 demean）
    db_path = build_basic_db(tmp_path)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = _panel().with_columns(
            pl.when(pl.col("code") == "D").then(pl.lit("E")).otherwise(pl.col("code")).alias("code")
        )
        with pytest.raises(ValueError, match="缺少行业信息"):
            run_process_chain(df, ["neutralize(by: industry)"], ctx=con)
    finally:
        con.close()
