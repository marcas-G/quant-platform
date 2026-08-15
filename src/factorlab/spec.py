from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
PROCESS_PATTERN = r"^[a-z_][a-z0-9_]*(\(.*\))?$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class UniverseSpec(BaseModel):
    ref: str | None = None          # 命名引用或文件路径（查 universes_dir）
    codes: list[str] | None = None
    rules: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"ref": value}
        return value

    @model_validator(mode="after")
    def _exactly_one_universe(self) -> "UniverseSpec":
        chosen = sum(x is not None for x in (self.ref, self.codes, self.rules))
        if chosen != 1:
            raise ValueError("universe 必须且只能提供 ref / codes / rules 之一")
        return self


class DateRange(BaseModel):
    start: str | None = None
    end: str | None = None

    @model_validator(mode="after")
    def _valid_dates(self) -> "DateRange":
        for field in ("start", "end"):
            value = getattr(self, field)
            if value is not None and not re.match(DATE_PATTERN, value):
                raise ValueError(f"{field} 必须为 YYYY-MM-DD 格式")
        return self


class OperatorMacro(BaseModel):
    params: list[str] = Field(default_factory=list)
    formula: str


class SubFactorSpec(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)
    formula: str
    process: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_process_names(self) -> "SubFactorSpec":
        for item in self.process:
            if not re.match(PROCESS_PATTERN, item):
                raise ValueError(f"非法 process 项: {item}")
        return self


class CombineSpec(BaseModel):
    method: Literal["ic_weight", "equal_weight", "weight_sum"]
    weights: list[float] | None = None

    @model_validator(mode="after")
    def _valid_weights(self) -> "CombineSpec":
        if self.method == "weight_sum" and not self.weights:
            raise ValueError("weight_sum 必须提供非空 weights")
        return self


class FactorSpec(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)
    category: Literal["ohlcv_core", "ohlcv_retail", "valuation", "custom"]
    direction: Literal[1, -1]
    description: str = ""
    universe: UniverseSpec
    date: DateRange = Field(default_factory=DateRange)
    target: Literal["forward_return_5d", "forward_return_20d"] = "forward_return_5d"
    process: list[str] = Field(default_factory=list)
    operators: dict[str, OperatorMacro] = Field(default_factory=dict)
    formula: str | None = None
    factors: list[SubFactorSpec] | None = None
    combine: CombineSpec | None = None

    @model_validator(mode="after")
    def _validate_script(self) -> "FactorSpec":
        if (self.formula is None) == (self.factors is None):
            raise ValueError("formula 与 factors 必须二选一")
        if self.factors is not None and self.combine is None:
            raise ValueError("使用 factors 时必须提供 combine")
        if self.factors is not None and self.combine is not None:
            if self.combine.method == "weight_sum":
                if self.combine.weights is None or len(self.combine.weights) != len(self.factors):
                    raise ValueError("weight_sum 的 weights 数量必须等于 factors 数量")
        for item in self.process:
            if not re.match(PROCESS_PATTERN, item):
                raise ValueError(f"非法 process 项: {item}")
        return self


def load_spec(path: str | Path) -> FactorSpec:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return FactorSpec.model_validate(data)
