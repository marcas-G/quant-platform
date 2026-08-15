from __future__ import annotations

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

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)

    def _post(self, url: str, json: dict, timeout: int = 30):
        return requests.post(url, json=json, timeout=timeout)

    def _call(self, api_name: str, params: dict, fields: list[str] | None) -> pl.DataFrame:
        payload = {"api_name": api_name, "token": self.token, "params": params}
        if fields:
            payload["fields"] = ",".join(fields)
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self._post(self.base_url, json=payload)
                self._last_request = time.monotonic()
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
                return pl.DataFrame(data.get("items") or [], schema=data["fields"], orient="row")
            except Exception as exc:
                raise TeaJoinError(api_name, f"返回数据与字段不匹配: {exc}") from exc
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
