from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import polars as pl
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from factorlab.eval.ic_series import weekly_ic
from factorlab.web import charts

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _safe_name(name: str) -> str:
    """拒绝路径穿越（CWE-22）：因子名只允许普通名称段。

    空名、`.`、`..`、路径分隔符 `/` 与 `\\`、盘符标记 `:`（Windows 盘相对
    路径可逃逸 results_dir）一律 404——与"因子不存在"同语义，不泄露路径信息。
    """
    if not name or name in (".", "..") or any(c in name for c in "/\\:"):
        raise HTTPException(status_code=404, detail=f"因子 {name} 不存在")
    return name


def _load_summary(results_dir: Path, name: str) -> dict:
    """读取因子 summary.json；缺失/损坏 → 404。入口先校验 name（防御纵深）。"""
    name = _safe_name(name)
    path = results_dir / name / "summary.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"因子 {name} 不存在")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=404, detail=f"因子 {name} 的 summary 损坏") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=404, detail=f"因子 {name} 的 summary 损坏")
    return data


def _group(d: dict, key: str) -> dict:
    """安全取嵌套分组：缺失或非 dict → 空 dict（模板链式访问降级不崩）。"""
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


def _display(v):
    """模板展示用：None → 空串（避免表格/卡片渲染 'None'）。"""
    return "" if v is None else v



def _num(value) -> float | None:
    """仅返回 float；None/非数字 → None（模板显示为 —）。"""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _safe_summary(summary: dict) -> dict:
    """归一化模板访问的字段：缺省 None（旧结果/字段缺失不崩溃）。"""
    ev = summary.get("evaluation")
    if not isinstance(ev, dict):
        ev = {}
    ic = ev.get("ic")
    if not isinstance(ic, dict):
        ic = {}
    ev["ic"] = {"mean": _num(ic.get("mean")), "t_stat": _num(ic.get("t_stat"))}
    dr = ev.get("decile_returns")
    if not isinstance(dr, dict):
        dr = {}
    spread = dr.get("spread")
    if not isinstance(spread, dict):
        spread = {}
    ev["decile_returns"] = {"spread": {"ret": _num(spread.get("ret"))},
                            "groups": dr.get("groups") if isinstance(dr.get("groups"), list) else []}
    to = ev.get("turnover")
    ev["turnover"] = {"monthly": _num(to.get("monthly")) if isinstance(to, dict) else None}
    cov = ev.get("coverage")
    ev["coverage"] = {"pct_valid": _num(cov.get("pct_valid")) if isinstance(cov, dict) else None}
    summary["evaluation"] = ev
    for k in ("universe_count", "date_start", "date_end", "panel_rows",
              "signal_null_ratio", "spec_yaml", "category", "direction"):
        summary.setdefault(k, None)
    return summary


def create_app(results_dir: Path) -> FastAPI:
    """构建只读 Web 可视化应用（因子列表 + 详情）。results_dir 显式传入（可测性）。"""
    app = FastAPI(title="FactorLab")
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        factors = []
        if results_dir.exists():
            for summary_path in sorted(results_dir.glob("*/summary.json")):
                try:
                    s = json.loads(summary_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue  # 损坏/不可读的 summary 跳过，不中断列表
                ev = _group(s, "evaluation")
                ic = _group(ev, "ic")
                decile = _group(ev, "decile_returns")
                factors.append({
                    "name": s.get("name") or summary_path.parent.name,
                    "category": _display(s.get("category")),
                    "direction": _display(s.get("direction")),
                    "ic_mean": _num(ic.get("mean")),       # None/非数字 → None（模板显示 —）
                    "spread": _num(_group(decile, "spread").get("ret")),
                    "run_at": datetime.fromtimestamp(summary_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
        return templates.TemplateResponse(request, "index.html", {"factors": factors})

    @app.get("/factor/{name}", response_class=HTMLResponse)
    def factor_detail(request: Request, name: str):
        name = _safe_name(name)  # 路由入口校验（_load_summary 内部再校验，双保险）
        summary = _safe_summary(_load_summary(results_dir, name))
        # 归一化 evaluation 各分组：缺失 → 空 dict，模板链式访问渲染空串而非崩溃
        ev = _group(summary, "evaluation")
        decile = _group(ev, "decile_returns")
        summary = {**summary, "evaluation": {
            "ic": _group(ev, "ic"),
            "decile_returns": {
                "spread": _group(decile, "spread"),
                "groups": decile.get("groups") if isinstance(decile.get("groups"), list) else [],
            },
            "turnover": _group(ev, "turnover"),
            "coverage": _group(ev, "coverage"),
            "layered_backtest": _group(ev, "layered_backtest"),
        }}
        charts_data = {}
        weekly_path = results_dir / name / "weekly.parquet"
        has_weekly = False
        if weekly_path.exists():
            try:
                panel = pl.read_parquet(weekly_path)
                charts_data["ic"] = charts.ic_curve_figure(weekly_ic(panel))
                has_weekly = True
            except (OSError, ValueError, pl.exceptions.PolarsError):
                pass  # 损坏/缺列的 weekly.parquet → IC 曲线区域降级（其余图表照常）
        groups = summary["evaluation"]["decile_returns"]["groups"]
        if groups:
            charts_data["decile"] = charts.decile_bar_figure(groups)
        layered = summary["evaluation"]["layered_backtest"]
        if isinstance(layered.get("net_values"), dict) and layered["net_values"]:
            charts_data["layered"] = charts.layered_net_value_figure(
                layered["net_values"], layered.get("dates", []))
        return templates.TemplateResponse(request, "factor.html", {
            "name": name, "summary": summary, "charts": charts_data,
            "has_weekly": has_weekly,
        })

    return app
