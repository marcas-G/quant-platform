from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import polars as pl
import yaml
from expr_codegen import codegen_exec

from factorlab.config import settings as _settings
from factorlab.data.calendar import fill_suspensions, trading_calendar
from factorlab.data.source import load_daily
from factorlab.data.universe import resolve_codes
from factorlab.engine.forward import align_weekly, compute_forward_returns
from factorlab.engine.partitions import reject_future_shifts, validate_partition_calls
from factorlab.factor.ast_gate import validate_formula
from factorlab.ops.platform_ops import expand_platform_macros, register_platform_ops
from factorlab.ops.polars_ta_wrappers import register_polars_ta_ops
from factorlab.process.registry import run_process_chain
from factorlab.spec import FactorSpec


def compute_formula(
    df: pl.DataFrame,
    formula: str,
    asset: str = "code",
    date: str = "date",
) -> pl.DataFrame:
    validate_formula(formula)
    formula = expand_platform_macros(formula)  # 薄封装 → ts_ 表达式，保证按 asset 分区
    register_polars_ta_ops()  # 幂等；保证分区校验能识别 ts_/cs_/ta_ 算子
    register_platform_ops()
    validate_partition_calls(formula)
    reject_future_shifts(formula)
    result = codegen_exec(
        df.lazy(),
        formula,
        over_null="partition_by",
        style="polars",
        date=date,
        asset=asset,
    ).collect()
    if "signal" not in result.columns:
        raise ValueError("因子脚本必须定义输出列 signal")
    return result.select([date, asset, "signal"]).sort([date, asset])


# ---- M3a run_factor 装配 ----

# 元素级函数名（按名称调用时非数据列；Call 形式已由 called 集合排除，此处兜底）
_ELEMENTWISE_COLS = {"abs", "log", "log1p", "sqrt", "exp", "sign", "floor", "if_else"}


def _formula_columns(formula: str) -> list[str]:
    """提取公式实际引用的数据列（排除算子名/函数参数/import 名/中间变量）。"""
    tree = ast.parse(formula)
    # ast.arg 在 Python 3.13 的属性是 .arg（.name 为 3.14+ 别名）
    defined = {n.name if isinstance(n, ast.FunctionDef) else n.arg
               for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.arg))}
    # 赋值中间变量（非下划线）也是 defined：Assign 的 targets 是列表、AnnAssign 的 target 是单个。
    # 注意：Python 3.13 内联 comprehension 的 if 条件里用三元表达式会误报 NameError，故拆成两个集合
    defined |= {n.targets[0].id for n in ast.walk(tree)
                if isinstance(n, ast.Assign) and n.targets and isinstance(n.targets[0], ast.Name)}
    defined |= {n.target.id for n in ast.walk(tree)
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    # AnnAssign 注解名（如 ret: float = ... 的 float）也不是数据列
    annotated = {sub.id for n in ast.walk(tree) if isinstance(n, ast.AnnAssign)
                 for sub in ast.walk(n.annotation) if isinstance(sub, ast.Name)}
    imported = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    cols = names - defined - imported - called - annotated - _ELEMENTWISE_COLS - {"signal"}
    return sorted(c for c in cols if not c.startswith("_") and c not in {"date", "code"})


@dataclass
class RunContext:
    """运行上下文。universe_override：6 位代码（如 600519）、universe 引用名或 yaml 文件路径。"""

    db_path: Path = _settings.quant_db
    output_dir: Path = Path("results")
    universe_override: str | None = None
    float32: bool = _settings.use_float32


@dataclass
class FactorResult:
    spec: FactorSpec
    panel: pl.DataFrame
    summary: dict = field(default_factory=dict)


def run_factor(spec: FactorSpec, ctx: RunContext) -> FactorResult:
    """装配链路：universe → 加载 → 停牌补全 → 因子 → process → forward → 周频对齐 → 落盘。"""
    if spec.factors is not None:
        raise NotImplementedError("多因子 factors/combine 组合尚未支持（M3a 仅支持单公式因子）")
    validate_formula(spec.formula)  # 提前校验：语法/禁止调用错误在打开数据库前抛出
    try:
        con = duckdb.connect(str(ctx.db_path), read_only=True)
    except duckdb.IOException as exc:
        raise FileNotFoundError(f"数据库不存在: {ctx.db_path}（可运行 data refresh 或检查路径）") from exc
    try:
        codes = resolve_codes(spec, con, override=ctx.universe_override)
        cols = _formula_columns(spec.formula)
        raw = load_daily(
            ctx.db_path, codes,
            date_start=spec.date.start, date_end=spec.date.end,
            cols=cols, float32=ctx.float32,
        ).collect()
        cal = trading_calendar(ctx.db_path, date_start=spec.date.start, date_end=spec.date.end)
        panel = fill_suspensions(raw, cal)
        if panel.height == 0:
            raise ValueError("日期段无数据，可运行 data refresh（M3b）")
        if "close" not in panel.columns:
            raise ValueError("因子公式必须引用 close 列（前向收益依赖 close[t+h]）")
        # compute_formula 仅输出 date/code/signal（M2 约定），把 signal 接回完整面板，
        # 供 process 链与 compute_forward_returns（依赖 close）使用
        panel = panel.join(compute_formula(panel, spec.formula), on=["date", "code"], how="left")
        panel = run_process_chain(panel, spec.process, ctx=con)
        panel = compute_forward_returns(panel)
        panel = align_weekly(panel)
        # spec 2.5 对齐输出：date, code, signal, forward_return_h, close
        keep = ["date", "code", "signal", "forward_return_5d", "forward_return_20d", "close"]
        panel = panel.select([c for c in keep if c in panel.columns])
    finally:
        con.close()

    summary = {
        "name": spec.name,
        "category": spec.category,
        "direction": spec.direction,
        "universe_count": len(codes),
        "codes": codes,
        "date_start": str(panel["date"].min()),  # panel.height == 0 已在链路中 raise，无需兜底
        "date_end": str(panel["date"].max()),
        "panel_rows": panel.height,
        "signal_null_ratio": round(panel["signal"].null_count() / panel.height, 4),
        "process": spec.process,
        "float32": ctx.float32,
        "spec_yaml": yaml.safe_dump(spec.model_dump(), allow_unicode=True),
    }
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(ctx.output_dir / "panel.parquet")
    (ctx.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return FactorResult(spec=spec, panel=panel, summary=summary)
