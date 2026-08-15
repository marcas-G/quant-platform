from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import polars as pl


OperatorKind = Literal["el", "ts", "cs", "gp", "ta"]


@dataclass(frozen=True)
class OperatorDef:
    name: str
    kind: OperatorKind
    version: str
    func: Callable[..., pl.Expr]
    doc: str = ""


_REGISTRY: dict[str, OperatorDef] = {}
_ALIASES: dict[str, str] = {}


def reset_registry() -> None:
    _REGISTRY.clear()
    _ALIASES.clear()


def factor_op(
    name: str,
    kind: OperatorKind,
    version: str,
    aliases: tuple[str, ...] = (),
) -> Callable:
    def decorator(func: Callable[..., pl.Expr]) -> Callable[..., pl.Expr]:
        op = OperatorDef(
            name=name,
            kind=kind,
            version=version,
            func=func,
            doc=func.__doc__ or "",
        )
        _REGISTRY[name] = op
        for alias in aliases:
            _ALIASES[alias] = name
        return func

    return decorator


def canonical_name(name: str, kind: OperatorKind) -> str:
    prefix = {"ts": "ts_", "cs": "cs_", "gp": "gp_", "ta": "ta_"}.get(kind, "")
    return name if not prefix or name.startswith(prefix) else f"{prefix}{name}"


def get_op(name: str) -> OperatorDef:
    target = _ALIASES.get(name, name)
    try:
        return _REGISTRY[target]
    except KeyError as exc:
        raise KeyError(f"未知算子: {name}") from exc


def has_op(name: str) -> bool:
    return name in _REGISTRY or name in _ALIASES


def list_ops() -> list[OperatorDef]:
    return sorted(_REGISTRY.values(), key=lambda op: op.name)
