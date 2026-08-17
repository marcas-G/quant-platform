import tempfile

import polars as pl
import pytest

from factorlab.eval.correlation import factor_correlation


def _write_panel(td, name, signals):
    df = pl.DataFrame(
        {"date": d, "code": c, "signal": s} for d, c, s in signals
    )
    d = __import__("pathlib").Path(td) / name
    d.mkdir()
    df.write_parquet(d / "panel.parquet")


def test_rank_correlation_positive():
    """完全正相关 → 周度秩相关 ≈ 1。"""
    with tempfile.TemporaryDirectory() as td:
        signals = [(f"2024-01-0{i}", f"{j:06d}", float(i * 100 + j))
                   for i in range(1, 4) for j in range(1, 51)]
        _write_panel(td, "a", signals)
        _write_panel(td, "b", [(d, c, 2 * s + 1) for d, c, s in signals])
        m = factor_correlation(["a", "b"], td)
        assert abs(m["rank_corr"][0] - 1.0) < 1e-6


def test_rank_correlation_negative():
    """完全负相关 → 周度秩相关 ≈ -1。"""
    with tempfile.TemporaryDirectory() as td:
        signals = [(f"2024-01-0{i}", f"{j:06d}", float(j))
                   for i in range(1, 4) for j in range(1, 51)]
        _write_panel(td, "a", signals)
        _write_panel(td, "b", [(d, c, -s) for d, c, s in signals])
        m = factor_correlation(["a", "b"], td)
        assert abs(m["rank_corr"][0] + 1.0) < 1e-6


def test_missing_factor_raises():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(FileNotFoundError):
            factor_correlation(["a", "b"], td)


def test_single_factor_raises():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ValueError):
            factor_correlation(["a"], td)


def test_three_factor_matrix():
    """三因子 → 3 对两两。"""
    with tempfile.TemporaryDirectory() as td:
        signals = [(f"2024-01-0{i}", f"{j:06d}", float(i * 100 + j))
                   for i in range(1, 4) for j in range(1, 51)]
        _write_panel(td, "a", signals)
        _write_panel(td, "b", [(d, c, 2 * s + 1) for d, c, s in signals])
        _write_panel(td, "c", [(d, c, -s) for d, c, s in signals])
        m = factor_correlation(["a", "b", "c"], td)
        assert m.height == 3
        # a×b 正相关、a×c 负相关
        ab = m.filter((pl.col("factor_a") == "a") & (pl.col("factor_b") == "b"))["rank_corr"][0]
        ac = m.filter((pl.col("factor_a") == "a") & (pl.col("factor_b") == "c"))["rank_corr"][0]
        assert abs(ab - 1.0) < 1e-6
        assert abs(ac + 1.0) < 1e-6


def test_svd_identifies_orthogonal_structure():
    """SVD：两个同源因子 + 一个正交因子 → 第一奇异值主导、载荷分离。"""
    from factorlab.eval.correlation import factor_svd
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        signals = [(f"2024-01-0{i}", f"{j:06d}", float(i * 100 + j))
                   for i in range(1, 4) for j in range(1, 51)]
        _write_panel(td, "a", signals)
        _write_panel(td, "b", [(d, c, 2 * s + 1) for d, c, s in signals])
        # c：与 a 正交（打乱 signal 值，保留 date/code 映射）
        import random
        rng = random.Random(1)
        sigs = [s for _, _, s in signals]
        rng.shuffle(sigs)
        shuffled = [(d, c, s2) for (d, c, _), s2 in zip(signals, sigs)]
        _write_panel(td, "c", shuffled)
        r = factor_svd(["a", "b", "c"], td, sample_weeks=3)
        # 第一奇异值 > 第二（同源主导）
        assert r["singular_values"][0] > r["singular_values"][1] + 0.5
        # 载荷：a/b 在 PC1 同向且 |载荷| 大，c 在 PC1 载荷小
        l = r["loadings"]
        assert abs(l[0]["PC1"]) > 0.5 and abs(l[1]["PC1"]) > 0.5
        assert abs(l[2]["PC1"]) < 0.5


def test_svd_sampling_deterministic():
    """同 seed 抽样 → 结果确定。"""
    from factorlab.eval.correlation import factor_svd
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        signals = [(f"2024-01-0{i}", f"{j:06d}", float(i * 100 + j))
                   for i in range(1, 4) for j in range(1, 51)]
        _write_panel(td, "a", signals)
        _write_panel(td, "b", [(d, c, -s) for d, c, s in signals])
        r1 = factor_svd(["a", "b"], td, sample_weeks=2, seed=42)
        r2 = factor_svd(["a", "b"], td, sample_weeks=2, seed=42)
        assert abs(r1["singular_values"][0] - r2["singular_values"][0]) < 1e-9
