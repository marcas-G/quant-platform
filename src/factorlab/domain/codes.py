"""Canonical research security identifier contract（M6-07B4）。

平台 research universe 只接受标准 A 股证券标识（canonical v1）：

    ts_code  匹配 ^\d{6}\.(SH|SZ|BJ)$
    symbol   == ts_code 前六位

Vendor source（TeaJoin/Tushare）可能返回历史遗留别名/实体标识（实测如
T600018.SH、TS0018.SH——上港集箱退市残留），不在 canonical 域内。这类行由
source partition 隔离（quarantine，见 rebuild.partition_stock_basic_source），
**绝不 canonicalize / 映射 / 静默丢弃**（M6 无 verified corporate-action
entity-lineage 模型）。隔离 ≠ 合并——alias 保持自身标识，不进 research universe。

本模块是 canonical 谓词的**唯一权威来源**：Python 侧
`is_canonical_stock_code()` 与 DuckDB SQL 侧 `regexp_matches()` 共用同一
pattern 常量，不得在 rebuild/universe 代码中独立重写该正则。
"""

import re

# 唯一权威 pattern（Python re 与 DuckDB RE2 语法兼容：\d / \. / {6} 均支持）。
CANONICAL_TS_CODE_PATTERN = r"^\d{6}\.(SH|SZ|BJ)$"

_TS_CODE_RE = re.compile(CANONICAL_TS_CODE_PATTERN)


def is_canonical_stock_code(ts_code: str) -> bool:
    """ts_code 是否满足 canonical research identifier v1（六位数字 + .SH/.SZ/.BJ）。

    只做 ts_code 形态判断；symbol == 前六位 的一致性由调用方（source
    validator / partition）负责。None / 非 str → False（fail 方向）。
    """
    return isinstance(ts_code, str) and bool(_TS_CODE_RE.match(ts_code))


def is_canonical_stock_row(ts_code: str, symbol: str) -> bool:
    """canonical 行完整契约：ts_code 形态 + symbol == ts_code 前六位。"""
    return is_canonical_stock_code(ts_code) and symbol == ts_code[:6]
