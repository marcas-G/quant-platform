"""M8-02B1R：suspend_timing generalized parser——circular wall-clock interval 模型。

- NULL = timing absent（production absence 表示为 NULL only）；空串/空白严格拒绝
- time token：H:MM / HH:MM / H:MM:SS / HH:MM:SS（分钟/秒必须两位；时钟严格校验）
- interval：segment[,segment]*（不 merge/不排序/不 dedup/gap 保留）
- 三类 interval semantics（start >= end 不再 invalid）：
    start <  end → SAME_SESSION  [start, end)
    start >  end → WRAPPED       circular（second >= start OR second < end）
    start == end → FULL_CYCLE    任意合法 second 均覆盖
- 输出 seconds since midnight；open reference = 09:30:00 = 34200
"""

import pytest

from factorlab.execution.suspension import (interval_contains_second,
                                            parse_suspend_timing,
                                            timing_covers_open)

OPEN = 9 * 3600 + 30 * 60   # 34200


# ---------------- NULL / empty / whitespace ----------------

def test_none_is_absence():
    assert parse_suspend_timing(None) is None


@pytest.mark.parametrize("bad", ["", " ", "   ", "\t", "\n",
                                 " 09:30-10:00", "09:30-10:00 ",
                                 "09:30 - 10:00", "09:30-10:00, 13:00-14:00"])
def test_empty_and_whitespace_rejected(bad):
    with pytest.raises(ValueError):
        parse_suspend_timing(bad)


@pytest.mark.parametrize("bad", [34200, 9.5, b"09:30-10:00", ["09:30-10:00"]])
def test_non_string_rejected(bad):
    with pytest.raises(ValueError):
        parse_suspend_timing(bad)


# ---------------- minute precision ----------------

def test_minute_precision_canonical():
    assert parse_suspend_timing("09:30-10:00") == ((34200, 36000),)


@pytest.mark.parametrize("text,iv", [
    ("9:30-9:40", ((34200, 34800),)),
    ("0:00-0:01", ((0, 60),)),
    ("23:58-23:59", ((86280, 86340),)),
    ("09:03-09:04", ((32580, 32640),)),
])
def test_minute_precision_forms(text, iv):
    assert parse_suspend_timing(text) == iv


# ---------------- second precision ----------------

@pytest.mark.parametrize("text,iv", [
    ("09:31:07-09:41:07", ((34267, 34867),)),
    ("9:31:07-9:41:07", ((34267, 34867),)),
    ("23:59:00-23:59:59", ((86340, 86399),)),
    ("09:30:00-09:30:01", ((34200, 34201),)),
])
def test_second_precision(text, iv):
    assert parse_suspend_timing(text) == iv


# ---------------- mixed precision ----------------

@pytest.mark.parametrize("text,iv", [
    ("09:30-10:00:30", ((34200, 36030),)),
    ("9:30:00-10:00", ((34200, 36000),)),
])
def test_mixed_precision_accepted(text, iv):
    assert parse_suspend_timing(text) == iv


# ---------------- numeric exactness ----------------

def test_numeric_exactness():
    assert parse_suspend_timing("09:30-10:31,10:31-14:57") == \
        ((34200, 37860), (37860, 53820))


# ---------------- multi interval ----------------

def test_two_intervals_preserved_not_merged():
    out = parse_suspend_timing("09:30-10:31,10:31-14:57")
    assert out == ((34200, 37860), (37860, 53820))
    assert len(out) == 2


def test_three_intervals():
    out = parse_suspend_timing("09:30-09:40,09:41-09:51,13:00-13:10")
    assert out == ((34200, 34800), (34860, 35460), (46800, 47400))
    assert len(out) == 3


def test_seconds_plus_comma():
    out = parse_suspend_timing("09:31:07-09:41:07,09:42:28-09:52:28")
    assert out == ((34267, 34867), (34948, 35548))


def test_gap_preserved():
    """09:40→09:41 gap 保留——不自动连续化。"""
    out = parse_suspend_timing("09:30-09:40,09:41-09:51")
    assert out == ((34200, 34800), (34860, 35460))


def test_interval_order_preserved():
    out = parse_suspend_timing("13:00-9:30,09:30-10:00")
    assert out == ((46800, 34200), (34200, 36000))


def test_repeated_intervals_preserved():
    out = parse_suspend_timing("09:30-10:00,09:30-10:00")
    assert out == ((34200, 36000), (34200, 36000))


# ---------------- SAME_SESSION / WRAPPED / FULL_CYCLE parse ----------------

def test_same_session_parse():
    assert parse_suspend_timing("09:30-10:00") == ((34200, 36000),)


def test_wrapped_parse():
    assert parse_suspend_timing("13:00-9:30") == ((46800, 34200),)


def test_full_cycle_parse():
    assert parse_suspend_timing("09:30-09:30") == ((34200, 34200),)


def test_full_cycle_arbitrary_endpoint():
    assert parse_suspend_timing("13:00-13:00") == ((46800, 46800),)
    assert parse_suspend_timing("00:00-00:00") == ((0, 0),)


# ---------------- malformed syntax / clock ----------------

@pytest.mark.parametrize("bad", [
    "foo", "09:30", "09:30-", "-10:00", "09:30--10:00",
    "09:30:00", "09:30-10:00-11:00",
])
def test_malformed_syntax_rejected(bad):
    with pytest.raises(ValueError):
        parse_suspend_timing(bad)


@pytest.mark.parametrize("bad", [
    "24:00-10:00", "99:00-10:00",
    "09:60-10:00", "09:30-10:60",
    "09:30:60-10:00", "09:30-10:00:60",
    "9:3-10:00", "09:30-10:3",
    "09:03:7-10:00",
])
def test_invalid_clock_rejected(bad):
    with pytest.raises(ValueError):
        parse_suspend_timing(bad)


def test_whitespace_inside_interval_rejected():
    with pytest.raises(ValueError):
        parse_suspend_timing("09:30 - 10:00")
    with pytest.raises(ValueError):
        parse_suspend_timing("09:30 -10:00")


# ---------------- interval_contains_second ----------------

def test_containment_same_session():
    assert interval_contains_second((34200, 36000), 34200)      # start inclusive
    assert interval_contains_second((34200, 36000), 35999)
    assert not interval_contains_second((34200, 36000), 36000)  # end exclusive
    assert not interval_contains_second((34200, 36000), 34199)


def test_containment_wrapped():
    iv = (46800, 34200)   # 13:00-09:30
    assert interval_contains_second(iv, 46800)     # >= start
    assert interval_contains_second(iv, 86399)     # 23:59:59
    assert interval_contains_second(iv, 0)         # 00:00:00 < end
    assert interval_contains_second(iv, 34199)     # 09:29:59 < end
    assert not interval_contains_second(iv, 34200)  # == end exclusive
    assert not interval_contains_second(iv, 46799)  # 12:59:59


def test_containment_full_cycle():
    assert interval_contains_second((34200, 34200), 0)
    assert interval_contains_second((34200, 34200), 34200)
    assert interval_contains_second((34200, 34200), 86399)
    assert interval_contains_second((46800, 46800), 34200)   # 任意 equal endpoint


def test_containment_second_resolution():
    assert interval_contains_second((34199, 34201), 34200)
    assert not interval_contains_second((34199, 34200), 34200)
    assert interval_contains_second((34200, 34201), 34200)


@pytest.mark.parametrize("bad", [-1, 86400, 100000])
def test_containment_second_range(bad):
    with pytest.raises(ValueError):
        interval_contains_second((34200, 36000), bad)


# ---------------- timing_covers_open goldens ----------------

@pytest.mark.parametrize("text,expected", [
    # same-session
    ("09:30-10:00", True),
    ("09:25-09:31", True),
    ("09:25-09:30", False),
    ("10:00-10:30", False),
    ("00:00-09:29", False),
    ("09:30:01-10:00", False),
    # wrapped
    ("13:00-9:30", False),
    ("13:00-10:00", True),
    ("13:00:00-09:30:00", False),
    ("13:00:00-09:30:01", True),
    ("09:31-09:30", False),    # wrapped end=09:30 end-exclusive → 不覆盖
    ("09:31-09:29", False),    # 09:30:00 不在 [09:31..24:00) ∪ [00:00, 09:29)
    # full cycle
    ("09:30-09:30", True),
    ("13:00-13:00", True),
    ("00:00-00:00", True),
    ("23:59-23:59", True),
    # seconds precision
    ("09:29:59-09:30:01", True),
    ("09:29:59-09:30:00", False),
    ("09:30:00-09:30:01", True),
    # multi interval any()
    ("10:00-10:30,13:00-14:00", False),
    ("10:00-10:30,09:30-09:31", True),
    ("09:30-10:31,10:31-14:57", True),
    ("09:31:07-09:41:07,09:42:28-09:52:28", False),
])
def test_timing_covers_open(text, expected):
    assert timing_covers_open(parse_suspend_timing(text)) is expected


def test_timing_covers_open_custom_reference():
    """open_second 可参数化——默认 34200 = 09:30:00。"""
    assert timing_covers_open(((34200, 36000),), open_second=34200)
    assert not timing_covers_open(((34200, 36000),), open_second=36000)


# ---------------- production golden rows（原两条 blocker） ----------------

def test_688766_source_full_cycle():
    """20251126 688766.SH S '09:30-09:30' → FULL_CYCLE → open covered。"""
    iv = parse_suspend_timing("09:30-09:30")
    assert iv == ((34200, 34200),)
    assert timing_covers_open(iv) is True


def test_603056_source_wrapped():
    """20260109 603056.SH S '13:00-9:30' → WRAPPED → current-day open NOT covered。"""
    iv = parse_suspend_timing("13:00-9:30")
    assert iv == ((46800, 34200),)
    assert timing_covers_open(iv) is False


def test_no_code_or_date_special_case():
    """helper 完全不接收 code/date——无白名单入口。"""
    import inspect
    assert "code" not in inspect.signature(parse_suspend_timing).parameters
    assert "date" not in inspect.signature(parse_suspend_timing).parameters
    assert "code" not in inspect.signature(timing_covers_open).parameters
