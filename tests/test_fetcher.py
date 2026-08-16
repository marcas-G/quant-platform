import polars as pl
import pytest
import requests

from factorlab.data.fetcher import TeaJoinClient, TeaJoinError


def _ok_response(items=None, fields=None):
    return type("R", (), {"status_code": 200, "json": lambda self: {
        "code": 0,
        "data": {"fields": fields or ["ts_code", "trade_date", "close"],
                 "items": [["000001.SZ", "20240102", 10.0], ["000002.SZ", "20240102", 20.0]] if items is None else items},
    }})()


def _empty_response():
    return type("R", (), {"status_code": 200, "json": lambda self: {"code": 0, "data": None}})()


def _err_response(status, body=None):
    return type("R", (), {"status_code": status, "json": lambda self: body or {"code": 4002, "msg": "权限不足"}, "text": "err"})()


def _client(monkeypatch, responder, interval=0.0):
    client = TeaJoinClient(token="t", interval=interval)
    monkeypatch.setattr(client, "_post", responder)
    return client


def test_fetch_parses_items_to_dataframe(monkeypatch):
    calls = []

    def responder(url, json=None, timeout=30):
        calls.append(json)
        return _ok_response()

    client = _client(monkeypatch, responder)
    df = client.fetch("daily", {"trade_date": "20240102"}, fields=["ts_code", "trade_date", "close"])
    assert df.columns == ["ts_code", "trade_date", "close"]
    assert df.height == 2
    assert calls[0]["api_name"] == "daily"
    assert calls[0]["token"] == "t"


def test_fetch_empty_data_returns_empty_frame(monkeypatch):
    client = _client(monkeypatch, lambda url, json=None, timeout=30: _empty_response())
    df = client.fetch("daily", {"trade_date": "20200101"})
    assert df.height == 0


def test_fetch_business_error_raises(monkeypatch):
    client = _client(monkeypatch, lambda url, json=None, timeout=30: _err_response(400))
    with pytest.raises(TeaJoinError, match="daily"):
        client.fetch("daily", {"trade_date": "20240102"})


def test_fetch_retries_on_network_error(monkeypatch):
    attempts = []

    def flaky(url, json=None, timeout=30):
        attempts.append(1)
        if len(attempts) < 3:
            raise requests.exceptions.ConnectionError("boom")
        return _ok_response()

    client = _client(monkeypatch, flaky, interval=0.0)
    df = client.fetch("daily", {"trade_date": "20240102"})
    assert len(attempts) == 3
    assert df.height == 2


def test_fetch_gives_up_after_max_retries(monkeypatch):
    attempts = []

    def always_fail(url, json=None, timeout=30):
        attempts.append(1)
        raise requests.exceptions.ConnectionError("boom")

    client = _client(monkeypatch, always_fail, interval=0.0)
    with pytest.raises(TeaJoinError):
        client.fetch("daily", {"trade_date": "20240102"})
    assert len(attempts) == 3


def test_fetch_throttles_interval(monkeypatch):
    import time
    sleeps = []
    real_sleep = time.sleep
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    def responder(url, json=None, timeout=30):
        return _ok_response()

    client = _client(monkeypatch, responder, interval=0.2)
    client.fetch("daily", {"trade_date": "20240102"})
    client.fetch("daily", {"trade_date": "20240103"})
    assert len(sleeps) >= 1 and sleeps[0] >= 0.19  # 第二次请求前补足间隔


def test_fetch_paged_loops_until_empty(monkeypatch):
    pages = []

    def responder(url, json=None, timeout=30):
        page = json["params"]["offset"]
        pages.append(page)
        if page == 0:
            return _ok_response(items=[["a", "20240102", 1.0]] * 5000)
        return _empty_response()

    client = _client(monkeypatch, responder, interval=0.0)
    df = client.fetch_paged("daily", {"trade_date": "20240102"}, page_size=5000)
    assert pages == [0, 5000]
    assert df.height == 5000


# ---------- 边界 / 错误路径补充 ----------


def test_fetch_empty_items_keeps_columns(monkeypatch):
    """data 存在但 items 为空：返回 0 行且保留字段列（teajoin 无数据时返回空列表）。"""
    client = _client(monkeypatch, lambda url, json=None, timeout=30: _ok_response(items=[]))
    df = client.fetch("daily", {"trade_date": "20200101"})
    assert df.height == 0
    assert df.columns == ["ts_code", "trade_date", "close"]


def test_fetch_business_error_no_retry(monkeypatch):
    """4xx 业务错误立即抛出，不重试。"""
    attempts = []

    def responder(url, json=None, timeout=30):
        attempts.append(1)
        return _err_response(400)

    client = _client(monkeypatch, responder, interval=0.0)
    with pytest.raises(TeaJoinError, match="daily"):
        client.fetch("daily", {"trade_date": "20240102"})
    assert len(attempts) == 1


def test_fetch_retries_on_429(monkeypatch):
    """429 是瞬态错误：重试后成功。"""
    import time
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    attempts = []

    def flaky(url, json=None, timeout=30):
        attempts.append(1)
        if len(attempts) < 3:
            return _err_response(429)
        return _ok_response()

    client = _client(monkeypatch, flaky, interval=0.0)
    df = client.fetch("daily", {"trade_date": "20240102"})
    assert len(attempts) == 3
    assert df.height == 2


def test_fetch_paged_exceeds_max_pages_raises(monkeypatch):
    """所有页都满时静默截断是丢数据：超过 max_pages 抛 TeaJoinError。"""
    pages = []

    def responder(url, json=None, timeout=30):
        offset = json["params"]["offset"]
        pages.append(offset)
        return _ok_response(items=[["a", "20240102", 1.0], ["b", "20240102", 2.0]])

    client = _client(monkeypatch, responder, interval=0.0)
    with pytest.raises(TeaJoinError, match="max_pages"):
        client.fetch_paged("daily", {"trade_date": "20240102"}, page_size=2, max_pages=2)
    assert pages == [0, 2]


def test_max_retries_must_be_positive():
    with pytest.raises(ValueError, match="max_retries"):
        TeaJoinClient(token="t", max_retries=0)


def test_fetch_retries_on_5xx(monkeypatch):
    import time
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    attempts = []

    def flaky(url, json=None, timeout=30):
        attempts.append(1)
        if len(attempts) == 1:
            return _err_response(500)
        return _ok_response()

    client = _client(monkeypatch, flaky, interval=0.0)
    df = client.fetch("daily", {"trade_date": "20240102"})
    assert len(attempts) == 2
    assert len(sleeps) == 1 and sleeps[0] == 1  # 指数退避 2**0
    assert df.height == 2


def test_fetch_invalid_json_retries_then_raises(monkeypatch):
    import time
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    attempts = []

    def raise_bad_json(self):
        raise ValueError("no json")

    def bad_json(url, json=None, timeout=30):
        attempts.append(1)
        return type("R", (), {"status_code": 200, "json": raise_bad_json})()

    client = _client(monkeypatch, bad_json, interval=0.0)
    with pytest.raises(TeaJoinError, match="daily"):
        client.fetch("daily", {"trade_date": "20240102"})
    assert len(attempts) == 3
    assert len(sleeps) == 3  # 每次失败都退避


def test_fetch_business_code_error_raises(monkeypatch):
    """HTTP 200 但业务 code != 0：按业务错误抛出，不重试。"""
    client = _client(monkeypatch, lambda url, json=None, timeout=30: _err_response(200))
    with pytest.raises(TeaJoinError, match="权限不足"):
        client.fetch("daily", {"trade_date": "20240102"})


def test_fetch_fields_mismatch_raises(monkeypatch):
    """行宽与字段数不一致：包装为带 api_name 的 TeaJoinError，不静默丢数据。"""
    client = _client(monkeypatch, lambda url, json=None, timeout=30: _ok_response(items=[["x", 1.0]]))
    with pytest.raises(TeaJoinError, match="daily"):
        client.fetch("daily", {"trade_date": "20240102"})


def test_fetch_paged_empty_first_page(monkeypatch):
    pages = []

    def responder(url, json=None, timeout=30):
        pages.append(json["params"]["offset"])
        return _empty_response()

    client = _client(monkeypatch, responder, interval=0.0)
    df = client.fetch_paged("daily", {"trade_date": "20200101"}, page_size=5000)
    assert pages == [0]
    assert df.height == 0


def test_fetch_normalizes_empty_strings_to_null(monkeypatch):
    """tushare 缺失数值返回 \"\"：空串转 null，全数值列推断为 Float64。"""
    client = _client(monkeypatch, lambda url, json=None, timeout=30: _ok_response(
        items=[["000001.SZ", "20240102", "10.0", "1.0"], ["000002.SZ", "20240102", "", ""]],
        fields=["ts_code", "trade_date", "close", "turnover"],
    ))
    df = client.fetch("daily", {"trade_date": "20240102"})
    assert df.schema["close"] == pl.Float64
    assert df["close"].to_list() == [10.0, None]
    assert df["turnover"].to_list() == [1.0, None]
    assert df["trade_date"].to_list() == ["20240102", "20240102"]  # 无空串的标识列保持字符串


def test_fetch_keeps_real_string_columns(monkeypatch):
    """含非数值文本的列保持 String（空串仍转 null），不误伤真实字符串字段。"""
    client = _client(monkeypatch, lambda url, json=None, timeout=30: _ok_response(
        items=[["000001.SZ", "平安银行", "银行", ""], ["000002.SZ", "万科A", "", ""]],
        fields=["ts_code", "name", "industry", "list_date"],
    ))
    df = client.fetch("stock_basic", {"list_status": "L"})
    assert df.schema["name"] == pl.String
    assert df["name"].to_list() == ["平安银行", "万科A"]
    assert df["industry"].to_list() == ["银行", None]


def test_fetch_all_empty_string_column_stays_string(monkeypatch):
    """全空串列不得被 cast 数值（如 suspend_timing 早期全空、后期为字符串）。"""
    items = [["000001.SZ", "20240102", ""], ["000002.SZ", "20240102", ""]]
    fields = ["ts_code", "trade_date", "suspend_timing"]

    def responder(url, json=None, timeout=30):
        return _ok_response(items=items, fields=fields)

    client = _client(monkeypatch, responder)
    df = client.fetch("suspend_d", {"trade_date": "20240102"})
    assert df.schema["suspend_timing"] == pl.String
    assert df["suspend_timing"].null_count() == 2  # 空串 → null，类型保持 String


def test_fetch_mixed_numeric_and_empty_strings_cast_to_float(monkeypatch):
    """数值与空串混合列：非空值全数值 → cast Float64（空串转 null）。"""
    items = [["000001.SZ", "20240102", "10.5"], ["000002.SZ", "20240102", ""]]
    fields = ["ts_code", "trade_date", "amount"]

    def responder(url, json=None, timeout=30):
        return _ok_response(items=items, fields=fields)

    client = _client(monkeypatch, responder)
    df = client.fetch("daily", {"trade_date": "20240102"})
    assert df.schema["amount"] == pl.Float64
    assert df["amount"].to_list() == [10.5, None]
