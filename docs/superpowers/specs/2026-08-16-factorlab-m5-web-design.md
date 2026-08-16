# FactorLab M5 Web 可视化设计文档

日期：2026-08-16
状态：待评审
依赖主设计：`docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md`（§10）
前置：M1-M4b（引擎/评估/分层回测全链路）

## 1. 背景与目标

单因子平台的 Web 可视化：从 `results_dir` 只读展示已运行因子的评估结果。
**单因子定位**（多因子范围外——无 /compare 页面）。

1. `/`：因子列表（名称/类别/方向/最近运行/IC 摘要）。
2. `/factor/<name>`：因子详情——IC 曲线、十分位柱状图、分层回测净值曲线、覆盖/换手摘要、spec 原文。
3. **IC 时序曲线**为 Web 现算（quant_core 只给汇总；从 weekly.parquet 每期 Spearman 秩相关）。

## 2. 架构

```
src/factorlab/web/
├── app.py          # FastAPI：/ 与 /factor/<name>
├── charts.py       # Plotly 图表构建（fig.to_json() → 模板内嵌）
└── templates/      # Jinja2（index.html / factor.html）
    └── static/     # plotly.min.js（本地 vendored，离线可用）
```

- **数据源**：`results_dir` 只读（summary.json + weekly.parquet）；不碰平台库。
- **图表**：Plotly JSON 内嵌模板，plotly.js 本地渲染（离线）。
- **运行**：`factorlab serve [--port 8000]`（CLI 命令，uvicorn 启动）。

## 3. 页面

### 3.1 `/` 因子列表

- 复用 `cli/main.py` 的 list 逻辑（扫描 `results_dir/*/summary.json`）。
- 表格：名称/类别/方向/最近运行（mtime）/IC mean/十分位 spread。
- 每行链接到 `/factor/<name>`。
- results_dir 缺失/空 → 空列表提示。

### 3.2 `/factor/<name>` 详情

- **IC 曲线**（`weekly_ic`，Web 现算）：周度 Spearman 秩相关折线图（含 0 参考线）。
- **十分位收益柱状图**：`decile_returns.groups`（group/mean_ret）柱状。
- **分层回测净值曲线**：`layered_backtest.net_values` 的 D1-D10 + long-short 折线。
- **摘要卡片**：IC mean/t_stat、十分位 spread、换手、覆盖、universe/日期/行数/null 比例。
- **spec 原文**（`spec_yaml` 渲染为 pre 块）。
- 缺失兼容：
  - summary 缺失/损坏 → 404 + 提示。
  - weekly.parquet 缺失 → IC 曲线区域隐藏（"无周频数据"），其余照常。
  - 无 layered_backtest（旧结果）→ 净值曲线区域隐藏。

## 4. 新功能：eval 层 weekly_ic

```python
def weekly_ic(panel: pl.DataFrame, target: str = "forward_return_5d") -> pl.DataFrame
```

- 输入：周频面板（date/code/signal/target——weekly.parquet）。
- 输出：(date, ic) 序列——每期 signal 与 target 的 **Spearman 秩相关**（rank 相关，
  与 quant_core 的 RankIC 同源定义）。
- 每期有效股票 < 3 → 该期 ic = null（秩相关不稳健）。
- signal/target null 行排除（复用 rust_ic 的过滤语义）。

## 5. CLI

```python
factorlab serve [--port 8000] [--host 127.0.0.1]
```

- uvicorn 启动 `web.app.app`；`--reload` 可选（开发）。
- 服务本机只读展示（无写路径）。

## 6. 测试策略

- **weekly_ic 单测**：构造面板验证 Spearman 数学（与 scipy/pandas 对照或手工推演）、
  有效股票不足的周 → null、null 行排除。
- **路由测试**（fastapi TestClient）：
  - `/` 200 且含因子名（tmp results 目录）。
  - `/factor/<name>` 200 且含图表 JSON（ic/decile/net_values 数据）。
  - 缺失因子 → 404。
  - 损坏 summary → 404 或降级展示。
- **集成**：真实 results 目录（3 个因子）serve 冒烟——两页面 200。

## 7. 明确不做（M5）

- /compare 页面（多因子范围外）。
- DSL 在线编辑/实时预览（v2 候选）。
- 因子库管理后台（v2 候选）。
- 图表交互深度（缩放/下载为 PNG 等 plotly 默认能力除外）。
