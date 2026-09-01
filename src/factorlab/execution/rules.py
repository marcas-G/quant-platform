"""M8-01B：Per-Security Order Quantity Rules。

- 全局 lot_size 已从 ExecutionSpec 移除——SecurityQuantityRule 是唯一数量权威
- 分类唯一来源：stock_basic.ts_code + stock_basic.market（**禁止 code-prefix
  板块推断**；market/suffix 一致性显式校验）
- pure validators 只回答"某个 quantity 是否合法"，不做数量投影（M8-03）
- SELL validator 接收 holding_quantity（申报数量结构）——不接收
  sellable_quantity（T+1 限制在 M8-03 单独处理）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl

from factorlab.domain.codes import is_canonical_stock_code
from factorlab.domain.execution import QuantityRuleKind

# 显式分类映射（stock_basic.market 实际规范值 + ts_code suffix 一致性校验）
# ——不自动 normalize market 字符串（strip/contains 均禁止）。
_QUANTITY_RULE_MAP: dict[tuple[str, str], QuantityRuleKind] = {
    ("主板", "SH"): QuantityRuleKind.ROUND_LOT_100,
    ("主板", "SZ"): QuantityRuleKind.ROUND_LOT_100,
    ("创业板", "SZ"): QuantityRuleKind.ROUND_LOT_100,
    ("科创板", "SH"): QuantityRuleKind.STAR_MIN_200_STEP_1,
    ("北交所", "BJ"): QuantityRuleKind.BSE_MIN_100_STEP_1,
}


def _strict_int(value) -> int | None:
    """quantity 必须 Python int 且非 bool；非法返回 None（validator 语义 False）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def is_valid_buy_quantity(rule: QuantityRuleKind, quantity: int) -> bool:
    """BUY 申报数量合法性（quantity 结构规则——不做 target projection）。"""
    q = _strict_int(quantity)
    if q is None:
        return False
    if rule is QuantityRuleKind.ROUND_LOT_100:
        return q >= 100 and q % 100 == 0
    if rule is QuantityRuleKind.STAR_MIN_200_STEP_1:
        return q >= 200
    if rule is QuantityRuleKind.BSE_MIN_100_STEP_1:
        return q >= 100
    return False


def project_buy_quantity(rule: QuantityRuleKind, max_quantity: int) -> int:
    """返回 <= max_quantity 的最大合法 BUY quantity；不存在则 0。

    M8-04C：从 orders.py 提取的**唯一 quantity projection authority**
    （M8-03 / M8-04C funding 缩量共用——禁止第三份公式）。
    """
    if rule is QuantityRuleKind.ROUND_LOT_100:
        return (max_quantity // 100) * 100
    if rule is QuantityRuleKind.STAR_MIN_200_STEP_1:
        return max_quantity if max_quantity >= 200 else 0
    if rule is QuantityRuleKind.BSE_MIN_100_STEP_1:
        return max_quantity if max_quantity >= 100 else 0
    raise ValueError(f"unknown QuantityRuleKind {rule!r}")


def project_sell_quantity(
    rule: QuantityRuleKind,
    *,
    holding_quantity: int,
    max_quantity: int,
) -> int:
    """返回不超过 max_quantity 的最大合法 SELL quantity；不存在则 0。

    - ROUND_LOT_100：整手（100/200/...）或一次完整零股 remainder（R, R+100,
      R+200, ...）中取 <= max 的最大值
    - STAR（最小 200）/ BSE（最小 100）：holding < 最小单位只能全量卖出
      （L >= H → H）；否则 L >= 最小单位 → L
    - 绝不超卖 target（max_quantity 已含 desired_sell 上限）
    - M8-04C：唯一 quantity projection authority（与 M8-03 共用）
    """
    h = holding_quantity
    if rule is QuantityRuleKind.ROUND_LOT_100:
        best = 0
        lots = (max_quantity // 100) * 100
        if lots >= 100:
            best = lots
        remainder = h % 100
        if remainder > 0 and max_quantity >= remainder:
            odd = remainder + 100 * ((max_quantity - remainder) // 100)
            best = max(best, odd)
        return best
    if rule is QuantityRuleKind.STAR_MIN_200_STEP_1:
        if h < 200:
            return h if max_quantity >= h else 0
        return max_quantity if max_quantity >= 200 else 0
    if rule is QuantityRuleKind.BSE_MIN_100_STEP_1:
        if h < 100:
            return h if max_quantity >= h else 0
        return max_quantity if max_quantity >= 100 else 0
    raise ValueError(f"unknown QuantityRuleKind {rule!r}")


def is_valid_sell_quantity(
    rule: QuantityRuleKind,
    *,
    holding_quantity: int,
    sell_quantity: int,
) -> bool:
    """SELL 申报数量合法性（含零股/不足最小单位余额的全量卖出语义）。

    - ROUND_LOT_100：整手（%100==0）或"完整零股 remainder 一次带出"
      （Q >= remainder 且 (Q-remainder)%100==0）
    - STAR/BSE：正常 >= 最小单位；holding < 最小单位时只能 Q == holding
    - holding_quantity 是申报数量结构输入（T+1 sellable 限制在 M8-03 单独处理）
    """
    h = _strict_int(holding_quantity)
    q = _strict_int(sell_quantity)
    if h is None or q is None:
        return False
    if h <= 0 or q <= 0 or q > h:
        return False
    if rule is QuantityRuleKind.ROUND_LOT_100:
        if q % 100 == 0:
            return True
        remainder = h % 100
        return remainder > 0 and q >= remainder and (q - remainder) % 100 == 0
    if rule is QuantityRuleKind.STAR_MIN_200_STEP_1:
        return q >= 200 or h < 200 and q == h
    if rule is QuantityRuleKind.BSE_MIN_100_STEP_1:
        return q >= 100 or h < 100 and q == h
    return False


# ---------------------------------------------------------------------------
# SecurityQuantityRules domain + resolver
# ---------------------------------------------------------------------------

_RULES_COLUMNS = ["code", "market", "rule"]


@dataclass(frozen=True)
class SecurityQuantityRules:
    """Per-security 申报数量规则（code/market/rule 三列）。

    - code canonical + unique + 稳定排序；rule 可反解 QuantityRuleKind；
      market 非空（provenance——不是业务规则本身）
    - 空 typed rules 合法
    """

    frame: pl.DataFrame

    def __post_init__(self) -> None:
        f = self.frame
        if list(f.columns) != _RULES_COLUMNS:
            raise ValueError(
                f"SecurityQuantityRules.frame 必须严格为 code/market/rule 三列"
                f"（收到 {f.columns}）")
        for col, dtype in (("code", pl.String), ("market", pl.String),
                           ("rule", pl.String)):
            if f.schema[col] != dtype:
                raise ValueError(f"rules.{col} dtype 必须为 {dtype}（收到 {f.schema[col]}）")
        if f.height:
            dup = f.group_by("code").len().filter(pl.col("len") > 1)
            if dup.height:
                raise ValueError(f"rules code 重复 {dup.height} 组")
            bad_code = f.filter(~pl.col("code").map_elements(
                is_canonical_stock_code, return_dtype=pl.Boolean).fill_null(False))
            if bad_code.height:
                raise ValueError(
                    f"rules 含非 canonical code: {bad_code['code'].unique().to_list()}")
            bad_market = f.filter(pl.col("market").is_null()
                                  | (pl.col("market").str.len_chars() == 0))
            if bad_market.height:
                raise ValueError(
                    f"rules.market 必须 non-null non-empty String"
                    f"（{bad_market['code'].to_list()}）")
            for v in f["rule"].unique().to_list():
                try:
                    QuantityRuleKind(v)
                except ValueError as exc:
                    raise ValueError(
                        f"rules.rule 必须可反解 QuantityRuleKind"
                        f"（收到 {v!r}——lot100/star/unknown/null 拒绝）") from exc
            if not f.equals(f.sort("code")):
                raise ValueError("rules 必须按 code 稳定排序——不自动排序")


def resolve_security_quantity_rules(
    db_path: Path,
    codes: list[str],
) -> SecurityQuantityRules:
    """从 stock_basic reference 解析 per-security quantity rules。

    - 分类来源：stock_basic.ts_code + stock_basic.market（read-only）；
      禁止 code-prefix 板块推断；market/suffix 组合显式校验
    - 输入 unique canonical list[str]；输出 rows == len(codes)（skeleton 驱动）
    - 缺失/重复 reference、unknown market、impossible market/suffix 组合 → fail
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path 必须为 Path（收到 {type(db_path).__name__}）")
    if not isinstance(codes, list):
        raise ValueError(f"codes 必须为 list[str]（收到 {type(codes).__name__}）")
    if any(not isinstance(c, str) for c in codes):
        raise ValueError("codes 元素必须为 str")
    if len(set(codes)) != len(codes):
        raise ValueError(f"codes 重复 {len(codes) - len(set(codes))} 个——不 dedup")
    bad = [c for c in codes if not is_canonical_stock_code(c)]
    if bad:
        raise ValueError(f"codes 必须全部 canonical ts_code（收到 {bad}）")
    if not codes:
        return SecurityQuantityRules(frame=pl.DataFrame(
            {"code": pl.Series([], dtype=pl.String),
             "market": pl.Series([], dtype=pl.String),
             "rule": pl.Series([], dtype=pl.String)}))
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT ts_code, market FROM stock_basic "
            "WHERE ts_code IN (SELECT unnest(?)) ORDER BY ts_code",
            [codes]).fetchall()
        found = {r[0] for r in rows}
        missing = [c for c in codes if c not in found]
        if missing:
            raise ValueError(
                f"stock_basic 缺失 {len(missing)} 个 code: {missing[:5]}——fail（不 drop）")
        counts: dict[str, int] = {}
        for r in rows:
            counts[r[0]] = counts.get(r[0], 0) + 1
        dup_ref = [c for c, n in counts.items() if n > 1]
        if dup_ref:
            raise ValueError(
                f"stock_basic 中 ts_code 重复 {dup_ref}——fail（不 first/last）")
        out = []
        for code in sorted(codes):
            market = dict((r[0], r[1]) for r in rows)[code]
            if market is None or (isinstance(market, str) and not market.strip()):
                raise ValueError(
                    f"{code} 的 stock_basic.market 为空——fail（不默认 ROUND_LOT_100）")
            suffix = code[-2:]
            kind = _QUANTITY_RULE_MAP.get((market, suffix))
            if kind is None:
                raise ValueError(
                    f"无法分类 {code}：market={market!r} + suffix={suffix}——"
                    f"unknown market 或 impossible market/suffix 组合（fail，"
                    f"不启发式推断）")
            out.append((code, market, kind.value))
        frame = pl.DataFrame(out, schema=_RULES_COLUMNS, orient="row")
        return SecurityQuantityRules(frame=frame)
    finally:
        con.close()
