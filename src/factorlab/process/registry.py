from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import duckdb
import polars as pl

_ITEM_RE = re.compile(r"^([a-z_][a-z0-9_]*)(?:\((.*)\))?$")
_KEY_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_POSITIONAL_NAMES = ("lower", "upper", "value")


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def parse_chain_item(item: str) -> tuple[str, dict[str, Any]]:
    """'winsorize(quantile=0.99)' -> ('winsorize', {'quantile': 0.99})；
    'neutralize(by: industry)' -> ('neutralize', {'by': 'industry'})（key 支持 = 与 : 分隔）；
    'clip(-3, 3)' -> ('clip', {'lower': -3.0, 'upper': 3.0})（位置参数按序命名）；
    关键字参数后不允许位置参数（防止静默覆盖）。"""
    match = _ITEM_RE.match(item.strip())
    if not match:
        raise ValueError(f"非法 process 项: {item}")
    name, args_raw = match.group(1), match.group(2)
    kwargs: dict[str, Any] = {}
    if args_raw:
        seen_keyword = False
        for i, part in enumerate(args_raw.split(",")):
            part = part.strip()
            if not part:
                raise ValueError(f"非法 process 参数: {item}")
            if "=" in part:
                key, _, value = part.partition("=")
                key = key.strip()
                if not _KEY_RE.match(key):
                    raise ValueError(f"非法 process 参数 key: {key}（{item}）")
                kwargs[key] = _parse_value(value)
                seen_keyword = True
            elif ":" in part:
                key, _, value = part.partition(":")
                key = key.strip()
                if not _KEY_RE.match(key):
                    raise ValueError(f"非法 process 参数 key: {key}（{item}）")
                kwargs[key] = _parse_value(value)
                seen_keyword = True
            else:
                if seen_keyword:
                    raise ValueError(f"关键字参数后不允许位置参数: {item}")
                kwargs[_POSITIONAL_NAMES[i] if i < 3 else f"arg{i}"] = _parse_value(part)
    return name, kwargs


@dataclass(frozen=True)
class ProcessorDef:
    name: str
    func: Callable[..., pl.DataFrame]


@dataclass
class ProcessCtx:
    """处理器上下文：db 为只读 duckdb 连接（neutralize/fillna 取行业/市值用）。"""
    db: duckdb.DuckDBPyConnection | None = None


_PROCESSORS: dict[str, ProcessorDef] = {}


def register_processor(name: str | None = None) -> Callable:
    """注册处理器装饰器。两种用法：
    - `@register_processor`：裸装饰器，以函数名注册；
    - `@register_processor(name="别名")`：显式指定名称（如 zscore 别名）。
    """
    def decorator(func: Callable[..., pl.DataFrame]) -> Callable[..., pl.DataFrame]:
        key = name or func.__name__
        _PROCESSORS[key] = ProcessorDef(name=key, func=func)
        return func

    if callable(name):
        # 裸装饰器用法：name 实为被装饰函数本身
        func, name = name, None
        return decorator(func)
    return decorator


def get_processor(name: str) -> ProcessorDef:
    try:
        return _PROCESSORS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_PROCESSORS))
        raise KeyError(f"未知处理器: {name}（可用: {known}）") from exc


def run_process_chain(df: pl.DataFrame, chain: list[str], ctx=None) -> pl.DataFrame:
    """顺序执行 process 链；处理对象为 signal 列。ctx 为 ProcessCtx 或裸 duckdb 连接。"""
    if "signal" not in df.columns:
        raise ValueError("process 链需要 signal 列，请先计算因子")
    pctx = ctx if isinstance(ctx, ProcessCtx) else ProcessCtx(db=ctx)
    result = df
    for item in chain:
        name, kwargs = parse_chain_item(item)
        result = get_processor(name).func(result, ctx=pctx, **kwargs)
    return result
