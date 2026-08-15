from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import yaml

from factorlab.config import settings
from factorlab.spec import FactorSpec

VALID_EXCHANGES = ("SSE", "SZSE")


def normalize_code(code: str) -> str:
    """'000001.SZ' -> '000001'；纯数字直通；非法格式报错。"""
    base = code.split(".")[0].strip()
    if not base.isdigit() or len(base) != 6:
        raise ValueError(f"非法股票代码: {code}（期望 6 位数字或 ts_code 格式）")
    return base


def load_universe_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"universe 文件不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"universe 文件必须是映射: {path}")
    return data


def _resolve_source(name: str, universes_dir: Path) -> dict[str, Any]:
    path = Path(name)
    if path.is_file():
        return load_universe_file(path)
    candidate = universes_dir / f"{name}.yaml"
    return load_universe_file(candidate)


def _codes_from_rules(rules: dict[str, Any], db: duckdb.DuckDBPyConnection, date_start: str | None) -> list[str]:
    sql = "SELECT symbol FROM stock_basic_tushare WHERE exchange IN (SELECT unnest(?))"
    params: list[Any] = [list(VALID_EXCHANGES)]
    if rules.get("exclude_st"):
        sql += " AND symbol NOT IN (SELECT code FROM st_status WHERE is_st AND date = (SELECT max(date) FROM st_status))"
    exchanges = rules.get("exchanges")
    if exchanges:
        bad = [e for e in exchanges if e not in VALID_EXCHANGES]
        if bad:
            raise ValueError(f"不支持的交易所: {bad}（v1 仅支持 {VALID_EXCHANGES}，不含 BSE）")
        sql += " AND exchange IN (SELECT unnest(?))"
        params.append(list(exchanges))
    min_days = rules.get("min_list_days")
    if min_days:
        if date_start is None:
            date_start = db.execute("SELECT min(date) FROM daily").fetchone()[0]
        sql += " AND CAST(list_date AS DATE) <= CAST(? AS DATE) - INTERVAL (?) DAY"
        params.extend([date_start, int(min_days)])
    rows = db.execute(sql, params).fetchall()
    return sorted(r[0] for r in rows)


def resolve_codes(
    spec: FactorSpec,
    db: duckdb.DuckDBPyConnection,
    override: str | None = None,
    settings=settings,
) -> list[str]:
    """universe 三层解析：override > spec 内联/引用 > 全局默认。返回纯数字代码列表。"""
    if override is not None:
        try:
            normalize_code(override)
        except ValueError:
            data = _resolve_source(override, settings.universes_dir)
        else:
            data = {"codes": [override]}
    elif spec.universe.ref is not None:
        data = _resolve_source(spec.universe.ref, settings.universes_dir)
    elif spec.universe.codes is not None:
        data = {"codes": spec.universe.codes}
    else:
        assert spec.universe.rules is not None
        data = {"rules": spec.universe.rules}

    if "codes" in data:
        codes = [normalize_code(c) for c in data["codes"]]
    elif "rules" in data:
        codes = _codes_from_rules(data["rules"], db, spec.date.start)
    else:
        raise ValueError(f"universe 数据必须包含 codes 或 rules: {data}")

    if not codes:
        raise ValueError("universe 无有效股票，请检查 codes/rules/引用文件")
    return codes
