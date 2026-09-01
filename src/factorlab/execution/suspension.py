"""M8-02B1R：suspend_timing generalized parser——circular wall-clock interval 模型。

只做纯解析与 time-of-day coverage 判定（不接入 MarketOpenSnapshot——M8-02B
integration 属下一任务；不解析"下一交易日是哪天"，trade_cal 不参与）。

Source grammar（production frozen DB 实测：absence = NULL only；non-null
2,636 行）：
- time token：H:MM / HH:MM / H:MM:SS / HH:MM:SS（分钟/秒必须两位；
  hour 0..23 / minute 0..59 / second 0..59）
- interval：<time>-<time>，恰一个 "-"；完整值 segment[,segment]*
- 空白严格拒绝（不 strip）；''/非 str 拒绝（NULL 是唯一 absent 表示）

Interval 三类语义（**start >= end 不是 invalid**——source 修正后）：
    start <  end → SAME_SESSION  [start, end)
    start >  end → WRAPPED       circular：second >= start OR second < end
                                 （跨 session/day boundary 的 time-of-day
                                  coverage，不是"回当日早上"、不是 invalid）
    start == end → FULL_CYCLE    任意合法 second 均覆盖（如开盘起的持续停牌
                                  source 形式；不是 [start,start)=empty）

Parser 不 merge/不排序/不 dedup intervals、不补 gap、不重写 source 文本——
只把 raw string 转换为内存 seconds-since-midnight 表示。malformed value
（无法按 grammar 解析）一律 ValueError——**不解释为 absence、不猜测**，
属 source QA failure。

仅使用标准库（re）；不 import duckdb/polars/domain objects。
"""

from __future__ import annotations

import re

# 时间 token：H:MM / HH:MM / H:MM:SS / HH:MM:SS（分钟/秒两位，秒可选）
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
# 单个 interval segment：<time>-<time>（恰一个 "-"；token 本身不含 "-"）
_SEGMENT_RE = re.compile(
    r"^(\d{1,2}:\d{2}(?::\d{2})?)-(\d{1,2}:\d{2}(?::\d{2})?)$")


def _to_seconds(token: str) -> int:
    """'HH:MM[:SS]' → seconds since midnight（时钟范围严格校验）。"""
    parts = token.split(":")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(
            f"invalid clock {token!r}（hour 0..23 / minute 0..59 / second 0..59）")
    return hour * 3600 + minute * 60 + second


def parse_suspend_timing(
    value: str | None,
) -> tuple[tuple[int, int], ...] | None:
    """解析 suspend_timing raw string → (start, end) seconds-since-midnight 元组。

    - None → None（production absence = NULL only；'' 与空白均拒绝）
    - 多 interval 保留 source 顺序；start>=end 合法（WRAPPED/FULL_CYCLE）
    - 任何 grammar 外形式 → ValueError（不静默降级为 absence）
    """
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise ValueError(
            f"suspend_timing 必须为非空 str（''/非 str 均拒绝——absence 仅由 "
            f"NULL 表示，收到 {value!r}）")
    intervals: list[tuple[int, int]] = []
    for segment in value.split(","):
        m = _SEGMENT_RE.match(segment)
        if m is None:
            raise ValueError(
                f"invalid suspend_timing segment {segment!r}（期望 "
                f"H:MM[:SS]-H:MM[:SS]，无空白；不 strip/不猜测）")
        start = _to_seconds(m.group(1))
        end = _to_seconds(m.group(2))
        intervals.append((start, end))
    return tuple(intervals)


def interval_contains_second(
    interval: tuple[int, int],
    second: int,
) -> bool:
    """单个 interval 是否覆盖给定 wall-clock second（circular 模型）。

    - SAME_SESSION（start < end）：start <= second < end
    - WRAPPED（start > end）：second >= start OR second < end
    - FULL_CYCLE（start == end）：任意合法 second 均 True
    """
    if not isinstance(second, int) or isinstance(second, bool) \
            or not 0 <= second < 86400:
        raise ValueError(
            f"second 必须为 0 <= int < 86400（收到 {second!r}）")
    start, end = interval
    if start < end:
        return start <= second < end
    if start > end:
        return second >= start or second < end
    return True   # start == end → FULL_CYCLE


def timing_covers_open(
    intervals: tuple[tuple[int, int], ...],
    *,
    open_second: int = 9 * 3600 + 30 * 60,
) -> bool:
    """intervals 中任一 interval 覆盖 open reference（默认 09:30:00 = 34200）。

    与 source interval 顺序无关（any 语义）。
    """
    if not isinstance(open_second, int) or isinstance(open_second, bool) \
            or not 0 <= open_second < 86400:
        raise ValueError(
            f"open_second 必须为 0 <= int < 86400（收到 {open_second!r}）")
    return any(interval_contains_second(iv, open_second) for iv in intervals)
