# FactorLab 数据运维手册（Data Ops Playbook）

日期：2026-08-16
来源：M3b 全量重建实战经验（teajoin Tushare 代理，2000-01-04 至今，~46,000 请求）

## 1. 数据链路总览

```
factorlab data rebuild [--start YYYYMMDD] [--resume]   # 全量重建（暂存库 → 稀疏剔除 → 最终库）
factorlab data update                                   # 一键更新（增量 + 指数 + 验证 + 报告）
factorlab data refresh                                  # 仅行情 7 表增量（update 的内部步骤）
factorlab data verify [--compare <ref.duckdb>]          # 完整性自检 + 稀疏摘要 + 抽样对拍
factorlab run <spec.yaml> [--universe U] [--output-dir D]  # 因子计算 + 周频评估 + 分层回测（消费环节）
factorlab list                                          # 已保存因子清单与最近运行摘要
factorlab show <name>                                   # 查看单因子完整摘要（spec/评估/分层回测）
factorlab serve [--port 8000] [--host 127.0.0.1]        # Web 可视化（浏览器查看列表与图表）
```

数据目录（gitignored）：`data/rebuild_staging.duckdb`（全字段暂存）、`data/factorlab.duckdb`（最终库，稀疏剔除后）、`data/manifest.json`（拉取进度 + 剔除清单 + 失败诊断）。因子计算结果（gitignored）落 `results/<name>/`（`FACTORLAB_RESULTS_DIR` 可覆盖根目录）：`panel.parquet`（日频面板）、`weekly.parquet`（周频对齐面板）、`summary.json`（含 `evaluation` 周频评估摘要 + `layered_backtest` 分层回测）。

**运维闭环**：`data update`（拉新数据）→ `factorlab run`（计算 + 评估 + 分层回测）→ `factorlab list`/`show`（查询因子清单与摘要）→ `factorlab serve`（浏览器可视化列表与图表），判断因子有效性（IC/十分位 spread/换手/覆盖/分层回测，见 §6）。

## 2. 全量重建经验（2026-08-16 实战）

### 2.1 时间与规模

- **请求量**：~46,000（行情 7 表 × 6,450 交易日 + 指数）；串行 ~15 小时，**5 路并发 ~3 小时**。
- **token**：teajoin API Key 有到期日（本次 2026-08-22 到期）——重建前先查 `https://teajoin.com/redeem` 确认有效期。
- **断点续传**：manifest 每批落盘，中断后 `--resume` 从 failed/未完成日期继续——**任意时刻可中断恢复**。

### 2.2 并发与限流（关键经验）

- 限流上限 450 次/分钟；客户端默认 0.2s 请求起点间隔（300/min 安全值）。
- **只控制请求起点间隔不够**——必须同时限制 in-flight 并发（`BoundedSemaphore(3)`）：请求耗时 0.8-2.6s 时，仅间隔控制会产生 4-13 个同时连接，服务端对并发敏感接口（如 suspend_d）会批量失败。
- **连接复用**（`requests.Session`）：每次新建连接在长跑（数万请求）下有连接建立竞争。
- **并发 fetch + 串行写入**：duckdb 单写者——worker 只做网络 IO，主线程串行 upsert（复用连接）。
- **表级串行**：服务端对特定接口（suspend_d）的连续访问敏感——`SERIAL_TABLES` 配置强制串行。

### 2.3 数据类型陷阱（6 层，全部由真实数据暴露）

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| 1 | 数值列被空串污染 | tushare 缺失值返回 `""`（非 null） | fetcher 空串→null；非空值全数值才 cast Float64 |
| 2 | 表列被建为 INTEGER | JSON null 全列 → polars Null 类型 → duckdb 建表默认推断 INTEGER | Null 类型列 cast String |
| 3 | polars 构造崩溃 | 默认按**前 100 行**推断类型，混合类型列（前段 null 后段字符串）append 失败 | **统一 String schema 构造**，类型统一处理 |
| 4 | is_open 比较崩溃 | 统一 String 构造后数值比较需 cast | `filter(is_open.cast(Int32) == 1)` |
| 5 | calendar_gaps 误报 | trade_cal 含未来公告日（公告到 2026-12-31） | 规则排除未来日（`cal_date <= today`） |
| 6 | 空串列误 cast | 全空串列被判"全数值" | 非空值（忽略 null）全部可解析才 cast |

**核心原则：tushare 代理数据不做类型假设——统一按字符串接收，按需精确 cast。**

### 2.4 已知数据局限（非平台问题）

- **stk_limit 历史数据**：2007-2014 早期涨跌停价与 close 偏差较大（接口后补历史不精确）；**2024 至今零违规**（实测）。
- **pct_chg 一致性**：极少数历史日（5/17,292,582）与 pre_close 计算有 0.07-1.6 个百分点差异——历史数据源噪声。
- **财报三表**：teajoin 强制 `ts_code` 参数（按报告期拉全市场被拒）；全市场按股 170 万请求不可行——**M3b+ 按 ts_code 分批**（当前不在范围）。
- **指数成分**（index_weight）：按每月最后一个交易日拉取（历史期 ~320 个月）。

## 3. 定期更新（data update）

```bash
factorlab data update
```

一键链路（手动触发）：
1. 行情 7 表增量（从 manifest.last_updated 次日到最新交易日，failed 日期重试）
2. 指数增量（index_daily 到最新交易日；index_weight 补新月份）
3. 自动 verify：完整性自检（6 规则）+ 稀疏摘要
4. 输出报告：各表新增行数、失败日期（含错误原因）、integrity 规则通过情况

**失败处理**：单日失败记录 manifest（failed + failed_errors 诊断），下次 update 自动重试；报告醒目提示。

## 4. 验证与健康检查

- `factorlab data verify --compare <ref.duckdb>`：完整性 6 规则 + 抽样对拍（30 只 × 3 段，容差 0.01%）。
- **参考库对拍**：自动检测列结构（平台 `trade_date/ts_code` vs 参考库 `date/code`，日期格式自动转换）。
- **稀疏评估**：全量重建后最终库已物理剔除稀疏字段（null_ratio>20% 或 stock_coverage<80%）；update 不重评估（增量沿用剔除清单）。

## 5. 故障排查速查

| 症状 | 检查 |
|------|------|
| 大量失败 + failed_errors 为 INT32/类型错误 | 数据类型问题（§2.3）——确认 fetcher 版本，清理表后重拉 |
| 单表批量失败（其余正常） | 该表走 `SERIAL_TABLES` 串行重试（如 suspend_d） |
| manifest 无进展 | 任务可能卡在慢请求（timeout 30s × 3 重试）——停掉重跑 `--resume` |
| refresh 死锁（无新日期） | 确认 manifest.last_updated 是最近交易日（非未来公告日） |
| verify 对拍 0 行 | 参考库列结构不兼容——检查自动映射是否生效（见 §4） |
| 数据更新后行数不增 | refresh 的 upsert 列过滤——最终库稀疏剔除后全字段 df 自动裁剪 |
| `run` 报「平台库缺失」 | 检查 cwd 下 `data/factorlab.duckdb` 是否存在（或 `FACTORLAB_PLATFORM_DB` 指向） |
| `run` 报 universe 无有效股票 | 核对代码格式（`daily.code` 纯数字，spec 可用 `.SZ/.SH` 后缀）与库内代码 |

## 6. 因子计算与评估（factorlab run）

数据就绪后跑因子：

```bash
factorlab run factor/demo.yaml --universe 600519 --output-dir out/run1
```

- **数据源**：`settings.platform_db`（`data/factorlab.duckdb`，`FACTORLAB_PLATFORM_DB` 覆盖）——只读消费，不写数据库。
- **链路**：平台库 daily 加载（含 adj_factor）→ 停牌补全 → total_return 前向收益 → 复权视图（spec `adjustment`，默认 qfq）→ 因子公式 → process 链 → 周频对齐 → `quant_core` 评估 → **分层回测**（默认）。
- **落盘**：`results/<name>/panel.parquet`、`weekly.parquet`、`summary.json`（run_factor 摘要 + `evaluation` 字段）。`--output-dir` 缺省 `results/<name>/`（`FACTORLAB_RESULTS_DIR` 覆盖根目录——`list`/`show` 扫描同一目录）。
- **评估摘要字段**（`summary.json.evaluation`）：`n_weeks`、`ic`（mean/std/t_stat/ir）、`decile_returns`（含十分位 spread）、`turnover`、`coverage`（pct_valid/total_rows/valid_rows）、`layered_backtest`（分层回测：`n_groups`/`periods`/`net_values`/`summary`/`dates`——`periods` = 评估 `n_weeks`，无效周不计）。
- **分层回测默认产出**：`--backtest`（默认）在评估后追加分层回测；`--no-backtest` 关闭（快速评估，weekly 落盘不受影响）；`--groups N` 调整档数（默认 10）。
- **常用参数**：`--universe U`（覆盖 spec；缺省回落 `FACTORLAB_DEFAULT_UNIVERSE`）、`--max-memory M`（默认 4GB）、`--output-dir DIR`、`--no-float32`、`--backtest/--no-backtest`、`--groups N`。
- 失败以非 0 退出并打印原因（spec 不存在、平台库缺失、universe 无有效股票等）；同批次因子固定同一 universe 再比较（同池计算、同池比较）。

### 因子清单查询（list / show）

run 后的查询闭环（同 `results_dir` 锚定，扫描 `*/summary.json`）：

```bash
factorlab list        # 全部已保存因子：name | category | dir | ic_mean | spread | run_at（按运行时间倒序）
factorlab show demo   # 单因子完整摘要：spec 原文 / evaluation.ic / 分层回测各档 + long-short 摘要
```

- 无结果时 `list` 提示「暂无因子结果（先运行 factorlab run）」；`show` 对不存在的
  因子或损坏的 summary.json 以非 0 退出并打印原因。
- 判断因子有效性的快速路径：`list` 看 IC/spread 横向比较 → `show` 看分层回测
  （D1 年化/夏普、long-short 单调性与盈亏）→ 决定是否值得进一步研究。

### Web 可视化（serve）

```bash
factorlab serve [--port 8000] [--host 127.0.0.1]   # 默认 http://127.0.0.1:8000/
```

run 后运维闭环的浏览器环节（只读 `results_dir`，不依赖平台库）：列表页
（name/ic_mean/spread/run_at）+ 详情页（周度 RankIC 曲线/十分位收益/分层回测
净值，Plotly 内嵌）。旧结果（缺 evaluation/weekly.parquet）降级展示不崩溃；
损坏 summary 列表页跳过、详情页 404（与 `list`/`show` 缺失兼容一致）。
浏览器打开 `http://127.0.0.1:8000/` 即可查看。
