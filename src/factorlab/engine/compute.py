from __future__ import annotations

import ast
import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import yaml
from expr_codegen import codegen_exec

from factorlab.config import settings as _settings
from factorlab.data.adjust import view_prices
from factorlab.data.calendar import fill_suspensions, trading_calendar
from factorlab.data.source import load_daily
from factorlab.data.universe import resolve_codes
from factorlab.engine.forward import compute_forward_returns
from factorlab.engine.partitions import reject_future_shifts, validate_partition_calls
from factorlab.factor.ast_gate import validate_formula
from factorlab.ops.platform_ops import (
    expand_platform_macros,
    expand_user_macros,
    inline_defs,
    register_platform_ops,
    rewrite_expr_methods,
)
from factorlab.ops.polars_ta_wrappers import register_polars_ta_ops
from factorlab.process.registry import run_process_chain
from factorlab.spec import FactorSpec


_PARAM_PATTERN = re.compile(r"\$\{(\w+)\}")


def _substitute_params(formula: str, params: dict[str, Any]) -> str:
    """顶层参数替换：formula 内 ${name} 文本引用 → 字面量（str(params[name])）。

    文本替换（非 AST）：宏体/def 体内的 ${} 同样可见——宏体由调用方对 operators
    副本替换，def 体在 formula 文本内一并命中。未知参数名 → ValueError。
    """
    def _repl(match: re.Match) -> str:
        name = match.group(1)
        if name not in params:
            raise ValueError(f"未知参数: {name}（spec.params 未声明）")
        return str(params[name])

    return _PARAM_PATTERN.sub(_repl, formula)


def compute_formula(
    df: pl.DataFrame,
    formula: str,
    asset: str = "code",
    date: str = "date",
) -> pl.DataFrame:
    validate_formula(formula)
    formula = inline_defs(formula)  # def 内联（幂等：无 def 原样返回）——窗口算子合法化为顶层 ts_ 调用
    formula = rewrite_expr_methods(formula)  # 元素级方法链 → 函数调用（expr_codegen 不支持属性调用）
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


_WINDOW_PREFIXES = ("ts_", "ta_")  # 窗口参数在第二位置的算子族（tdx_* 参数语义不同，不提取）


def _ts_window_days(formula: str) -> int:
    """AST 提取公式中所有 ts_*/ta_* 窗口算子的窗口参数最大值（第二位置参数，int 字面量）；
    无窗口算子 → 0（纯 CS/元素级公式不需要 warmup）。窗口参数非常量时忽略该项。"""
    tree = ast.parse(formula)
    windows = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in ("wq", "ta"):
            name = node.func.attr
        else:
            continue
        if not name.startswith(_WINDOW_PREFIXES):
            continue
        arg = node.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, int) and not isinstance(arg.value, bool):
            windows.append(arg.value)
    return max(windows) if windows else 0


@dataclass
class RunContext:
    """运行上下文。universe_override：6 位代码（如 600519）、universe 引用名或 yaml 文件路径。
    adjustment：复权视图口径兜底（raw|qfq|hfq|pit_qfq；spec.adjustment 声明时以 spec 为准）。"""

    db_path: Path = _settings.platform_db
    output_dir: Path = Path("results")
    universe_override: str | None = None
    float32: bool = _settings.use_float32
    adjustment: str = "qfq"


@dataclass
class FactorResult:
    spec: FactorSpec
    panel: pl.DataFrame
    summary: dict = field(default_factory=dict)


def run_factor(spec: FactorSpec, ctx: RunContext) -> FactorResult:
    """装配链路：universe → 加载（含 adj_factor）→ 停牌补全 → 前向收益（total_return，
    raw close×adj，必须先于复权视图）→ 复权视图（因子计算口径）→ 因子 → process → 落盘。"""
    if spec.factors is not None:
        raise NotImplementedError("多因子 factors/combine 组合不在平台范围（平台定位单因子计算与评估）")
    # 展开链（打开数据库前全部完成，语法/参数错误先暴露）：
    # spec.params 顶层参数先替换（宏体经 operators 副本、def 体在 formula 文本内一并命中）
    # → spec.operators 内联宏展开（用户宏公式可引用平台薄封装与 ${}）
    # → 校验 → def 内联（窗口算子合法化为顶层 ts_ 调用）→ 平台薄封装展开
    formula = _substitute_params(spec.formula or "", spec.params)
    operators = {
        name: op.model_copy(update={"formula": _substitute_params(op.formula, spec.params)})
        for name, op in spec.operators.items()
    }
    formula = expand_user_macros(formula, operators)
    validate_formula(formula)
    formula = inline_defs(formula)
    formula = rewrite_expr_methods(formula)
    formula = expand_platform_macros(formula)  # 薄封装 → ts_ 表达式（compute_formula 内部再展开幂等无害）
    try:
        con = duckdb.connect(str(ctx.db_path), read_only=True)
    except duckdb.IOException as exc:
        raise FileNotFoundError(f"数据库不存在: {ctx.db_path}（可运行 data refresh 或检查路径）") from exc
    try:
        codes = resolve_codes(spec, con, override=ctx.universe_override)
        formula_cols = _formula_columns(formula)  # 展开后提取：宏公式内引用的数据列也纳入加载
        # close/adj_factor 恒加载（forward 依赖 close 列而非公式引用——纯量价因子允许）
        cols = formula_cols + ["close", "adj_factor"]
        raw = load_daily(
            ctx.db_path, codes,
            date_start=spec.date.start, date_end=spec.date.end,
            cols=cols, float32=ctx.float32,
        ).collect()
        cal = trading_calendar(ctx.db_path, date_start=spec.date.start, date_end=spec.date.end)
        # trade_cal 含未来公告日（~94 个到 20261231）：补全面板截断到今天，不产生未来 null 行
        today = datetime.date.today()
        cal = cal.filter(cal <= today)
        panel = fill_suspensions(raw, cal)
        if panel.height == 0:
            raise ValueError("日期段无数据，可运行 data refresh（M3b）")
        # 前向收益必须在 view_prices 之前计算：total_return = raw close×adj（复权视图已
        # 缩放 close，再乘 adj 会二次复权——HFQ/QFQ 收益应一致）
        panel = compute_forward_returns(panel)
        adjustment = getattr(spec, "adjustment", None) or ctx.adjustment
        asof = None
        if adjustment == "pit_qfq":
            # view_prices 的 asof 是 datetime.date（pit_qfq 分支 filter pl.Date <= asof）——
            # spec.date.end 是 str，需转 date 对象（str 与 pl.Date 比较会报错）
            asof = datetime.date.fromisoformat(spec.date.end) if spec.date.end else panel["date"].max()
        panel = view_prices(panel, adjustment, asof=asof)
        # compute_formula 仅输出 date/code/signal（M2 约定），把 signal 接回完整面板，
        # 供 process 链使用；公式引用的 close 等在 view_prices 后为复权值
        panel = panel.join(compute_formula(panel, formula), on=["date", "code"], how="left")
        panel = run_process_chain(panel, spec.process, ctx=con)
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
        "adjustment": adjustment,
        "float32": ctx.float32,
        "spec_yaml": yaml.safe_dump(spec.model_dump(), allow_unicode=True),
    }
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(ctx.output_dir / "panel.parquet")
    (ctx.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return FactorResult(spec=spec, panel=panel, summary=summary)
