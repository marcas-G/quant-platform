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
from factorlab.data.calendar import chunk_calendar, fill_suspensions, trading_calendar
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
    """AST 提取公式窗口需求：ts_*/ta_* 窗口算子的窗口参数，**沿变量引用链叠加**。

    嵌套滚动（如 robust_z 的 MAD = ts_median((x - ts_median(y, N)).abs(), N)）时，
    med 的 N 窗被外层 N 窗消费 → 总需求 = 2N。chunked warmup 只覆盖单层 N 时，
    每块嵌套滚动全 null（研究轮 204 根因）。窗口参数非常量时忽略该项；无窗口算子 → 0。
    """
    tree = ast.parse(formula)
    assigns: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            assigns[node.targets[0].id] = node.value

    def _call_window(node: ast.Call) -> int:
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in ("wq", "ta"):
            name = node.func.attr
        if not name or not name.startswith(_WINDOW_PREFIXES):
            return 0
        arg = node.args[1] if len(node.args) >= 2 else None
        if isinstance(arg, ast.Constant) and isinstance(arg.value, int) and not isinstance(arg.value, bool):
            return arg.value
        return 0

    def _need(node: ast.AST) -> int:
        # DSL 公式无循环引用（变量先赋值后使用）——不做 visited 防呆，同一变量
        # 在表达式不同位置分别展开（否则 seen 消耗后嵌套链的窗口叠加丢失）
        if isinstance(node, ast.Call):
            sub = max((_need(a) for a in node.args), default=0)
            if isinstance(node.func, ast.Attribute):
                sub = max(sub, _need(node.func.value))  # 方法链：.abs() 的 BinOp 在 func.value
            return _call_window(node) + sub
        if isinstance(node, ast.Name) and node.id in assigns:
            return _need(assigns[node.id])
        return max((_need(c) for c in ast.iter_child_nodes(node)), default=0)

    needs = [_need(n) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    needs += [_need(expr) for expr in assigns.values()]
    return max(needs) if needs else 0


def fill_suspension_values(panel: pl.DataFrame) -> pl.DataFrame:
    """停牌补全行数值列前值填充（fill 前已算 forward_return，评估样本不变）。

    polars 滚动算子默认 min_samples=window 且 null 计入有效值要求——停牌补全行的
    1 个 null 使其后 d 天窗口统计全 null（传染），长窗因子（如 360 日）因此失效；
    嵌套滚动（MAD 等）进一步放大传染至全 null（研究轮 111/204 根因）。
    前值填充 = 停牌期间价格/成交视为不变（金融惯例），窗口统计不再含 null。
    """
    fill_cols = [c for c in panel.columns
                 if c not in {"date", "code"} and not c.startswith("forward_return")]
    return panel.with_columns(
        [pl.col(c).fill_null(strategy="forward").over("code") for c in fill_cols]
    )


@dataclass
class RunContext:
    """运行上下文。universe_override：6 位代码（如 600519）、universe 引用名或 yaml 文件路径。
    adjustment：复权视图口径兜底（raw|qfq|hfq|pit_qfq；spec.adjustment 声明时以 spec 为准）。
    chunk_days：日期分块（交易日/块；None=单块整段跑）。warmup_days：TS 窗口预热天数
    （None=按公式自动提取窗口最大值 + 20 安全垫）。"""

    db_path: Path = _settings.platform_db
    output_dir: Path = Path("results")
    universe_override: str | None = None
    float32: bool = _settings.use_float32
    adjustment: str = "qfq"
    chunk_days: int | None = None
    warmup_days: int | None = None


@dataclass
class FactorResult:
    spec: FactorSpec
    panel: pl.DataFrame
    summary: dict = field(default_factory=dict)


_WARMUP_SAFETY_PAD = 20  # 自动 warmup 的安全垫：覆盖 ts_delay 等窗口内偏移
# spec 2.5 对齐输出列（分块路径每块算完即裁剪到这些列再累积，避免全列面板堆叠 OOM）
_CHUNK_KEEP = ["date", "code", "signal", "forward_return_5d", "forward_return_20d", "close"]


def _load_base_adj(con: duckdb.DuckDBPyConnection, date_end: str | None) -> pl.DataFrame:
    """全局 qfq 复权基准：每代码在 <= date_end 的最新 adj_factor（与整段跑的组内 latest 语义一致）。

    返回 (code, base_adj) 两列 DataFrame；date_end 为 ISO 'YYYY-MM-DD' 或 'YYYYMMDD'。
    """
    where, params = "", []
    if date_end:
        where, params = " WHERE trade_date <= ?", [date_end.replace("-", "")]
    return con.execute(
        f"SELECT substr(ts_code, 1, 6) AS code, "
        f"last(adj_factor ORDER BY trade_date) AS base_adj "
        f"FROM adj_factor{where} GROUP BY substr(ts_code, 1, 6)",
        params,
    ).pl()


def _compute_panel(
    con: duckdb.DuckDBPyConnection,
    ctx: RunContext,
    spec: FactorSpec,
    formula: str,
    codes: list[str],
    date_start: str,
    date_end: str,
    cal: pl.Series,
    base_adj: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """单块流水线：load（SQL 按段过滤）→ 停牌补全 → 前向收益 → 复权视图 → 因子 → process。

    base_adj 仅在 qfq 时传入（分块路径）：归一 adj_factor 使组内最新=1 → factor=adj/base_adj，
    跨块绝对水平因子与整段跑一致。hfq/pit_qfq 不归一（归一会改变 hfq 结果；pit_qfq 分子分母同消）。
    """
    cols = _formula_columns(formula) + ["close", "adj_factor"]
    raw = load_daily(
        ctx.db_path, codes,
        date_start=date_start, date_end=date_end,
        cols=cols, float32=ctx.float32,
    ).collect()
    panel = fill_suspensions(raw, cal)
    if panel.height == 0:
        raise ValueError("日期段无数据，可运行 data refresh（M3b）")
    adjustment = getattr(spec, "adjustment", None) or ctx.adjustment
    if adjustment == "qfq" and base_adj is not None:
        panel = panel.join(base_adj, on="code", how="left").with_columns(
            (pl.col("adj_factor") / pl.col("base_adj")).alias("adj_factor")
        ).drop("base_adj")
    panel = compute_forward_returns(panel)
    panel = fill_suspension_values(panel)
    asof = None
    if adjustment == "pit_qfq":
        asof = datetime.date.fromisoformat(spec.date.end) if spec.date.end else panel["date"].max()
    panel = view_prices(panel, adjustment, asof=asof)
    panel = panel.join(compute_formula(panel, formula), on=["date", "code"], how="left")
    panel = run_process_chain(panel, spec.process, ctx=con)
    return panel


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
        cal = trading_calendar(ctx.db_path, date_start=spec.date.start, date_end=spec.date.end)
        # trade_cal 含未来公告日（~94 个到 20261231）：补全面板截断到今天，不产生未来 null 行
        today = datetime.date.today()
        cal = cal.filter(cal <= today)
        if ctx.chunk_days is None:
            # 单块整段（现行路径，逐字节不变）：base_adj=None → qfq 组内 latest 基准
            panel = _compute_panel(con, ctx, spec, formula, codes, spec.date.start, spec.date.end, cal)
        else:
            # 日期分块：每块独立跑完整流水线（含 warmup 重叠段），丢弃 warmup 行后拼接。
            # CS 算子（per-date 横截面）块内完整、TS 窗口由 warmup 覆盖 → 与整段逐 cell 一致；
            # qfq 时 adj_factor 按全局基准归一，绝对水平因子跨块一致。
            warmup = ctx.warmup_days if ctx.warmup_days is not None \
                else _ts_window_days(formula) + _WARMUP_SAFETY_PAD
            chunks = chunk_calendar(cal, ctx.chunk_days, warmup)
            base_adj = _load_base_adj(con, spec.date.end)
            panels = []
            for load_start, chunk_start, chunk_end in chunks:
                cal_chunk = cal.filter((cal >= load_start) & (cal <= chunk_end))
                chunk_panel = _compute_panel(
                    con, ctx, spec, formula, codes, load_start.isoformat(), chunk_end.isoformat(),
                    cal_chunk, base_adj)
                # 每块算完即裁剪到对齐输出列：全列面板堆叠会让峰值内存 = 所有块之和（OOM）
                chunk_panel = chunk_panel.filter(pl.col("date") >= chunk_start)
                panels.append(chunk_panel.select([c for c in _CHUNK_KEEP if c in chunk_panel.columns]))
            panel = pl.concat(panels)
            # 立即释放全部块级引用（含循环残留的最后一块全列面板）：评估阶段需要剩余内存
            del panels, chunk_panel, cal_chunk, base_adj
        # spec 2.5 对齐输出：date, code, signal, forward_return_h, close
        panel = panel.select([c for c in _CHUNK_KEEP if c in panel.columns])
    finally:
        con.close()

    adjustment = getattr(spec, "adjustment", None) or ctx.adjustment
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
