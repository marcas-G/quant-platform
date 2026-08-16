from __future__ import annotations

import polars as pl


def coverage_report(panel: pl.DataFrame, signal_col: str = "signal") -> dict:
    """覆盖率：有效行比例、股票覆盖数、日期覆盖数。"""
    total = panel.height
    valid = panel[signal_col].drop_nulls().len()
    return {
        "pct_valid": round(valid / total, 4) if total else 0.0,
        "total_rows": total,
        "valid_rows": valid,
        "stocks": panel["code"].n_unique(),
        "weeks": panel["date"].n_unique(),
    }
