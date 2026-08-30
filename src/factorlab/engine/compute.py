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
from factorlab.data.universe import align_to_listing, resolve_candidate_codes, resolve_universe_frame
from factorlab.domain.frames import LabelArtifact, SignalArtifact, SignalMeta
from factorlab.domain.timing import DEFAULT_EOD_SIGNAL_TIMING
from factorlab.engine.forward import DEFAULT_FORWARD_HORIZONS, compute_forward_returns
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
from factorlab.ops.universe_masking import (apply_universe_masking,
                                            validate_reserved_bindings)
from factorlab.process.registry import run_process_chain
from factorlab.spec import FactorSpec

# M6-03：formula 显式引用 future/label 字段 → fail fast（不等到 load_daily unknown column）
_FUTURE_COL_PREFIXES = ("forward_", "future_")
_FUTURE_COL_EXACT = {"target", "label"}


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


def _check_future_inputs(formula: str) -> None:
    """M6-03：factor formula 显式引用 forward_*/future_*/target/label → fail fast。"""
    for col in _formula_columns(formula):
        if col in _FUTURE_COL_EXACT or col.startswith(_FUTURE_COL_PREFIXES):
            raise ValueError(
                f"future/label inputs are forbidden in factor formula: {col!r}")


def compute_formula(
    df: pl.DataFrame,
    formula: str,
    asset: str = "code",
    date: str = "date",
    universe_mask: str | None = None,
) -> pl.DataFrame:
    validate_formula(formula)
    formula = inline_defs(formula)  # def 内联（幂等：无 def 原样返回）——窗口算子合法化为顶层 ts_ 调用
    formula = rewrite_expr_methods(formula)  # 元素级方法链 → 函数调用（expr_codegen 不支持属性调用）
    formula = expand_platform_macros(formula)  # 薄封装 → ts_ 表达式，保证按 asset 分区
    if universe_mask is not None:
        # M6-03：CS/GP 算子的数据参数包 if_else(mask, arg, None)——TS 仍见完整
        # listed history，CS 只见当日 active universe。mask 列必须已存在于 df。
        if universe_mask not in df.columns:
            raise ValueError(f"universe mask 列 {universe_mask!r} 不在输入数据中（内部保留列）")
        # M6-03A：mask 变换前校验保留名绑定（用户公式 + macro/def 展开后——
        # __factorlab_* 前缀禁止用户定义/绑定）
        validate_reserved_bindings(formula)
        formula = apply_universe_masking(formula, universe_mask)
    register_polars_ta_ops()  # 幂等；保证分区校验能识别 ts_/cs_/ta_ 算子
    register_platform_ops()
    _check_future_inputs(formula)
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
    """M6-03：signal/label runtime 分离产物 + legacy panel 兼容视图。"""
    spec: FactorSpec
    signal_artifact: SignalArtifact
    label_artifact: LabelArtifact
    panel: pl.DataFrame
    summary: dict = field(default_factory=dict)


_WARMUP_SAFETY_PAD = 20  # 自动 warmup 的安全垫：覆盖 ts_delay 等窗口内偏移
# spec 2.5 对齐输出列（分块路径每块算完即裁剪到这些列再累积，避免全列面板堆叠 OOM）
_CHUNK_KEEP = ["date", "code", "signal", "forward_return_5d", "forward_return_20d", "close"]


def _build_legacy_panel(
    signal_df: pl.DataFrame,
    labels_df: pl.DataFrame,
    signal_artifact: SignalArtifact,
    label_artifact: LabelArtifact,
) -> pl.DataFrame:
    """Legacy panel 兼容视图（M6-07C2B）：**不做 key join**。

    Signal/Label 的 (date, code) 键对齐（行数/键/顺序）由正式
    validate_signal_label_alignment() 证明后，仅位置化附加 labels 值列
    （forward_return_5d/20d）——避免 1,155 万行 × 2 侧的 hash join 峰值
    分配在无页面文件机器上撞 commit 空间（C2A 定位的 0xC0000005）。

    职责窄：alignment validation + positional attach + legacy schema select；
    不含 persistence（write_factor_artifacts 是独立的 persistence boundary
    guard，重复 alignment 验证属正常）。禁止任何 join——本步的数学关系
    已由 alignment contract 证明。
    """
    from factorlab.artifacts import validate_signal_label_alignment
    validate_signal_label_alignment(signal_artifact, label_artifact)
    label_values = labels_df.select(["forward_return_5d", "forward_return_20d"])
    panel = signal_df.hstack(label_values)
    return panel.select([c for c in _CHUNK_KEEP if c in panel.columns])


def _load_base_adj(con: duckdb.DuckDBPyConnection, date_end: str | None) -> pl.DataFrame:
    """全局 qfq 固定 base（M6-07C2E）：每代码在 <= effective_end 的**最新非 null**
    adj_factor。base 与 chunk 划分/warmup 无关；列名用内部保留前缀
    （__factorlab_），不进入用户公式（_compute_signal 在 compute_formula 前 drop）。

    返回 (code, __factorlab_qfq_base_adj) 两列 DataFrame；date_end 为 ISO
    'YYYY-MM-DD' 或 'YYYYMMDD'。FULL/CHUNK 使用完全相同 base。
    """
    where, params = "", []
    if date_end:
        where, params = " WHERE trade_date <= ?", [date_end.replace("-", "")]
    return con.execute(
        "SELECT substr(ts_code, 1, 6) AS code, "
        "last(adj_factor ORDER BY trade_date) "
        "FILTER (WHERE adj_factor IS NOT NULL) AS __factorlab_qfq_base_adj "
        f"FROM adj_factor{where} GROUP BY substr(ts_code, 1, 6)",
        params,
    ).pl()


def _compute_signal(
    con: duckdb.DuckDBPyConnection,
    ctx: RunContext,
    spec: FactorSpec,
    formula: str,
    codes: list[str],
    uf: pl.DataFrame,
    date_start: str,
    date_end: str,
    cal: pl.Series,
    base_adj: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Signal Runtime（M6-03）：listed market skeleton → fill → 复权视图 →
    universe-aware formula → filter(active) → process。

    - TS/TA 使用 is_listed=true 的完整历史（含 in_universe=false 期间——listing 先行）
    - CS/GP 经 __factorlab_universe_active mask 只看到当日 active 横截面
    - 最终 rows 只保留 in_universe=true（process chain 只见 active）
    - **本路径绝不计算 forward returns**
    """
    cols = _formula_columns(formula) + ["close", "adj_factor"]
    raw = load_daily(
        ctx.db_path, codes,
        date_start=date_start, date_end=date_end,
        cols=cols, float32=ctx.float32,
    ).collect()
    panel = align_to_listing(raw, uf)   # is_listed skeleton（停牌日保留 null 行）
    if panel.height == 0:
        raise ValueError("日期段无数据，可运行 data refresh（M3b）")
    adjustment = getattr(spec, "adjustment", None) or ctx.adjustment
    qfq_base_col = None
    if adjustment == "qfq" and base_adj is not None:
        # M6-07C2E：固定 sample base 列（**不覆盖 raw adj_factor**——字段保持
        # 市场语义，formula=adj_factor 在 FULL/CHUNK 下看到同一 raw 值）。
        # base 与 chunk 划分无关：FULL/CHUNK 共用 run_factor 传入的同一 base。
        panel = panel.join(base_adj, on="code", how="left")
        qfq_base_col = "__factorlab_qfq_base_adj"
    panel = fill_suspension_values(panel)
    asof = None
    if adjustment == "pit_qfq":
        asof = datetime.date.fromisoformat(spec.date.end) if spec.date.end else panel["date"].max()
    panel = view_prices(panel, adjustment, asof=asof, qfq_base_col=qfq_base_col)
    if qfq_base_col is not None:
        # internal base 不进用户公式（compute_formula 前 drop）与 artifact
        panel = panel.drop(qfq_base_col)
    # universe mask 列：来源必须是 PIT in_universe（内部保留列，用户不得定义）
    panel = panel.join(uf.select(["date", "code", "in_universe"]), on=["date", "code"], how="left")
    panel = panel.with_columns(pl.col("in_universe").fill_null(False).alias("__factorlab_universe_active"))
    result = compute_formula(panel, formula, universe_mask="__factorlab_universe_active")
    sig = panel.select(["date", "code", "in_universe", "close"]).join(
        result, on=["date", "code"], how="left")
    sig = sig.filter(pl.col("in_universe")).drop("in_universe")
    sig = run_process_chain(sig, spec.process, ctx=con)
    return sig.sort(["date", "code"])


def label_lookahead_end(cal: pl.Series, chunk_end: datetime.date, horizon: int) -> datetime.date:
    """M6-04：chunk_end 向后 horizon 个交易日的 label_end（right lookahead）。

    截断到研究 calendar 最后一天（**label lookahead 可跨内部 chunk boundary，
    不可跨研究 sample boundary**）。chunk_end 不在 calendar / horizon<0 /
    calendar 为空 → fail fast。
    """
    if horizon < 0:
        raise ValueError(f"horizon 不能为负: {horizon}")
    if cal.len() == 0:
        raise ValueError("calendar 为空——无法计算 label lookahead")
    idx = int(cal.search_sorted(chunk_end))
    if idx >= cal.len() or cal[idx] != chunk_end:
        raise ValueError(f"chunk_end {chunk_end} 不在研究 calendar 中")
    return cal[min(idx + horizon, cal.len() - 1)]


def _compute_labels(
    con: duckdb.DuckDBPyConnection,
    ctx: RunContext,
    spec: FactorSpec,
    codes: list[str],
    uf: pl.DataFrame,
    date_start: str,
    date_end: str,
    cal: pl.Series,
) -> pl.DataFrame:
    """Label Runtime（M6-03）：listed market history → compute_forward_returns →
    active-at-t keys → LabelArtifact frame。

    - 是否生成 t 的 label 取决于 t 是否 active（t+h 的未来 membership 不参与 censoring）
    - forward endpoint 无真实价格 → label null（sample 尾/停牌/退市——真 null 保持）
    - M6-04：date_start=chunk_start（label 不需要左侧 signal warmup——forward 只
      需要 t 与 t+h，无过去窗口）；date_end=label_end（right lookahead，仅 label）
    """
    raw = load_daily(
        ctx.db_path, codes,
        date_start=date_start, date_end=date_end,
        cols=["close", "adj_factor"], float32=ctx.float32,
    ).collect()
    panel = align_to_listing(raw, uf)
    if panel.height == 0:
        raise ValueError("日期段无数据，可运行 data refresh（M3b）")
    panel = compute_forward_returns(panel)   # fill 之前（现有顺序——停牌 endpoint null 合法）
    panel = fill_suspension_values(panel)
    panel = panel.join(uf.select(["date", "code", "in_universe"]), on=["date", "code"], how="left")
    panel = panel.filter(pl.col("in_universe"))
    return panel.select(["date", "code", "forward_return_5d", "forward_return_20d"]).sort(["date", "code"])


def run_factor(spec: FactorSpec, ctx: RunContext) -> FactorResult:
    """M6-03 装配链路：两条独立 runtime——

        Listed Market History → Signal Runtime → SignalArtifact
        Listed Market History → Label Runtime → LabelArtifact
        （PIT UniverseFrame 在两条路径的入口：listed skeleton + active mask/keys）

    Signal 路径绝不计算 forward returns；Label 路径独立调用 compute_forward_returns。
    legacy panel = signal LEFT JOIN labels（CLI/eval 兼容视图）。"""
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
    _check_future_inputs(formula)  # future/label 显式引用 → fail fast（AC-09）
    try:
        con = duckdb.connect(str(ctx.db_path), read_only=True)
    except duckdb.IOException as exc:
        raise FileNotFoundError(f"数据库不存在: {ctx.db_path}（可运行 data refresh 或检查路径）") from exc
    try:
        codes = resolve_candidate_codes(spec, con, override=ctx.universe_override)
        cal = trading_calendar(ctx.db_path, date_start=spec.date.start, date_end=spec.date.end)
        # trade_cal 含未来公告日（~94 个到 20261231）：补全面板截断到今天，不产生未来 null 行
        today = datetime.date.today()
        cal = cal.filter(cal <= today)
        if cal.len() == 0:
            raise ValueError("日期段无数据，可运行 data refresh（M3b）")
        warmup = ctx.warmup_days if ctx.warmup_days is not None \
            else _ts_window_days(formula) + _WARMUP_SAFETY_PAD
        # M6-07C2E：qfq 固定 sample base 与执行模式无关——FULL/CHUNK 同一 base。
        # effective_end：spec.date.end（非交易日合法，取 <= end 最后 adj）或
        # 研究 calendar 最后一天（无 end 时不读库中未来 adj_factor）。
        adjustment = getattr(spec, "adjustment", None) or ctx.adjustment
        if adjustment == "qfq":
            effective_end = spec.date.end if spec.date.end \
                else (cal[-1].isoformat() if cal.len() else None)
            base_adj = _load_base_adj(con, effective_end)
        else:
            base_adj = None
        if ctx.chunk_days is None:
            start_d = datetime.date.fromisoformat(spec.date.start) if spec.date.start else None
            end_d = datetime.date.fromisoformat(spec.date.end) if spec.date.end else None
            chunks = [(start_d, start_d, end_d)]
        else:
            chunks = chunk_calendar(cal, ctx.chunk_days, warmup)
        sig_parts, lab_parts = [], []
        for load_start, chunk_start, chunk_end in chunks:
            if ctx.chunk_days is None:
                # 单块全历史：signal/label 同窗口，无 lookahead——
                # label_end = sample end（截断后 cal 最后一天；spec.date.end 可能
                # 是非交易日，不在 cal——不能做额外 lookahead）
                signal_cal = label_cal = cal
                label_end = cal[-1] if cal.len() else None
            else:
                # M6-04 双窗口：
                #   Signal: [left warmup | output chunk]——结束于 chunk_end
                #   Label:  [output chunk | right lookahead]——结束于 label_end
                signal_cal = cal.filter((cal >= load_start) & (cal <= chunk_end))
                label_end = label_lookahead_end(cal, chunk_end,
                                                max(DEFAULT_FORWARD_HORIZONS))
                label_cal = cal.filter((cal >= chunk_start) & (cal <= label_end))
            signal_uf = resolve_universe_frame(spec, con, dates=signal_cal.to_list(),
                                               candidate_codes=codes)
            label_uf = resolve_universe_frame(spec, con, dates=label_cal.to_list(),
                                              candidate_codes=codes)
            sig = _compute_signal(con, ctx, spec, formula, codes, signal_uf,
                                  load_start.isoformat() if load_start else None,
                                  chunk_end.isoformat() if chunk_end else None,
                                  signal_cal, base_adj)
            lab = _compute_labels(con, ctx, spec, codes, label_uf,
                                  chunk_start.isoformat() if chunk_start else None,
                                  label_end.isoformat() if label_end else None,
                                  label_cal)
            if ctx.chunk_days is not None:
                # 双边裁剪 [chunk_start, chunk_end]：right-lookahead rows 不得
                # 进入任何输出（signal/label/panel）；每块算完即裁剪到对齐输出列
                # （全列面板堆叠会让峰值内存 = 所有块之和，OOM）
                sig = sig.filter((pl.col("date") >= chunk_start) & (pl.col("date") <= chunk_end))
                lab = lab.filter((pl.col("date") >= chunk_start) & (pl.col("date") <= chunk_end))
            sig_parts.append(sig.select([c for c in _CHUNK_KEEP if c in sig.columns]))
            lab_parts.append(lab)
        signal_df = pl.concat(sig_parts)
        labels_df = pl.concat(lab_parts)
        if ctx.chunk_days is not None:
            del sig_parts, lab_parts, signal_cal, label_cal, base_adj  # 立即释放块级引用（评估阶段省内存）
        # M6-01 domain contract 接线
        adjustment = getattr(spec, "adjustment", None) or ctx.adjustment
        meta = SignalMeta(name=spec.name, frequency="1d",
                          timing=DEFAULT_EOD_SIGNAL_TIMING, adjustment=adjustment)
        signal_artifact = SignalArtifact(
            frame=signal_df.select(["date", "code", "signal"]), meta=meta)
        label_artifact = LabelArtifact(
            frame=labels_df.select(["date", "code", "forward_return_5d", "forward_return_20d"]))
        # legacy panel：Signal/Label key 对齐已证明 → 位置化附加 label 值列
        # （M6-07C2B：不做 hash join——1,155 万行 × 2 侧的 join 峰值分配在
        # 无页面文件机器上撞 commit 空间 → 0xC0000005）
        panel = _build_legacy_panel(signal_df, labels_df, signal_artifact, label_artifact)
    finally:
        con.close()

    summary = {
        "name": spec.name,
        "category": spec.category,
        "direction": spec.direction,
        "universe_count": len(codes),   # 兼容字段（legacy 语义——候选集规模）
        "candidate_count": len(codes),
        "codes": codes,
        "date_start": str(panel["date"].min()),  # panel.height == 0 已在链路中 raise，无需兜底
        "date_end": str(panel["date"].max()),
        "panel_rows": panel.height,
        "signal_rows": signal_artifact.frame.height,
        "label_rows": label_artifact.frame.height,
        "signal_null_ratio": round(panel["signal"].null_count() / panel.height, 4),
        "runtime_semantics": "pit_universe_signal_label_v1",
        "process": spec.process,
        "adjustment": adjustment,
        "float32": ctx.float32,
        "spec_yaml": yaml.safe_dump(spec.model_dump(), allow_unicode=True),
    }
    # M6-05：统一 artifact persistence——signal → labels → panel → summary（最后 = 完成标记）
    from factorlab.artifacts import write_factor_artifacts
    summary = write_factor_artifacts(ctx.output_dir, signal_artifact, label_artifact,
                                     panel, summary)
    return FactorResult(spec=spec, signal_artifact=signal_artifact, label_artifact=label_artifact,
                        panel=panel, summary=summary)
