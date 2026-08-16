from __future__ import annotations

import threading
import time

import polars as pl
import requests


class TeaJoinError(Exception):
    """teajoin 业务错误（4xx、响应异常或重试耗尽）。"""

    def __init__(self, api_name: str, message: str) -> None:
        super().__init__(f"teajoin[{api_name}]: {message}")
        self.api_name = api_name


class TeaJoinClient:
    """teajoin Tushare 兼容代理客户端：全局限流 + 指数退避重试 + 分页。"""

    def __init__(
        self,
        token: str,
        base_url: str = "https://teajoin.com",
        interval: float = 0.2,
        max_retries: int = 3,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries 至少为 1")
        self.token = token
        self.base_url = base_url
        self.interval = interval
        self.max_retries = max_retries
        self._last_request = 0.0
        self._lock = threading.Lock()  # 并发拉取时限流状态线程安全
        self._inflight = threading.BoundedSemaphore(3)  # 最大 in-flight 请求数（服务端并发敏感）
        self._session = requests.Session()  # 连接复用（避免每次新建连接）

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self._last_request = time.monotonic()  # 预留请求起点（并发下同样成立）

    def _post(self, url: str, json: dict, timeout: int = 30):
        return self._session.post(url, json=json, timeout=timeout)

    def _request_once(self, payload: dict, timeout: int = 30):
        """单次请求：信号量限制 in-flight（并发下服务端连接压力可控）+ 限流 + 发送。"""
        with self._inflight:
            self._throttle()
            return self._post(self.base_url, json=payload, timeout=timeout)

    def _call(self, api_name: str, params: dict, fields: list[str] | None) -> pl.DataFrame:
        payload = {"api_name": api_name, "token": self.token, "params": params}
        if fields:
            payload["fields"] = ",".join(fields)
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._request_once(payload)
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 500 or resp.status_code == 429:
                last_exc = TeaJoinError(api_name, f"HTTP {resp.status_code}: {resp.text[:200]}")
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise TeaJoinError(api_name, f"HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                body = resp.json()
            except ValueError as exc:
                last_exc = TeaJoinError(api_name, f"响应 JSON 解析失败: {exc}")
                time.sleep(2 ** attempt)
                continue
            if body.get("code", 0) != 0:
                raise TeaJoinError(api_name, f"code={body.get('code')} msg={body.get('msg', '')}")
            data = body.get("data")
            if not data:
                return pl.DataFrame()
            try:
                frame = pl.DataFrame(data.get("items") or [], schema=data["fields"], orient="row")
            except Exception as exc:
                raise TeaJoinError(api_name, f"返回数据与字段不匹配: {exc}") from exc
            if frame.height:
                for c in frame.columns:
                    if frame.schema[c] == pl.Null:
                        # JSON null 全列：duckdb 建表默认推断 INTEGER，后续字符串值 INSERT 崩溃
                        frame = frame.with_columns(frame[c].cast(pl.String).alias(c))
                        continue
                    if frame.schema[c] != pl.String:
                        continue
                    replaced = frame[c].replace("", None)
                    if replaced.null_count() == frame[c].null_count():
                        continue  # 无空串，原样保留（避免把 trade_date/symbol 等标识列转成数值）
                    non_null = replaced.drop_nulls()
                    if non_null.len() > 0 and non_null.cast(pl.Float64, strict=False).null_count() == 0:
                        frame = frame.with_columns(replaced.cast(pl.Float64).alias(c))  # 非空值全数值 → Float64
                    else:
                        frame = frame.with_columns(replaced.alias(c))  # 真字符串/全空串 → 保留 String（空串转 null）
            return frame
        raise TeaJoinError(api_name, f"重试 {self.max_retries} 次仍失败: {last_exc}")

    def fetch(self, api_name: str, params: dict, fields: list[str] | None = None) -> pl.DataFrame:
        """单次拉取（tushare 标准协议）。"""
        return self._call(api_name, params, fields)

    def fetch_paged(
        self,
        api_name: str,
        params: dict,
        page_size: int = 5000,
        max_pages: int = 50,
        fields: list[str] | None = None,
    ) -> pl.DataFrame:
        """通用分页：params 注入 limit/offset 循环直到空页。"""
        frames: list[pl.DataFrame] = []
        page = pl.DataFrame()
        for offset in range(0, page_size * max_pages, page_size):
            page_params = {**params, "limit": page_size, "offset": offset}
            page = self._call(api_name, page_params, fields)
            if page.height == 0:
                break
            frames.append(page)
        if page.height == page_size:
            raise TeaJoinError(api_name, "数据超过 max_pages*page_size 行，请增大 max_pages")
        return pl.concat(frames) if frames else pl.DataFrame()
