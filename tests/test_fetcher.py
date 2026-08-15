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
