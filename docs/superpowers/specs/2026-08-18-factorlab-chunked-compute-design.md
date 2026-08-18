# 分块计算（Chunked Compute）设计

日期：2026-08-18

## 1. 背景与动机

实测确认平台内存硬边界：16GB 无页面文件机器上，fill_suspensions 全网格
（date × code 笛卡尔积）在 ~574 万行（3.5 年）可跑，扩展到 2020 起（6.5 年）
即段错误——**轻量因子同样爆**（对照实验证实），与公式复杂度无关，是数据规模
本身触顶。这阻止了样本扩展（2015 股灾/2018 熊市不可达），股灾抄底策略只能
看到 14 个触发周。

## 2. 方案：按日期分块 + warmup 重叠

### 2.1 分块维度选择

| 维度 | CS 算子（cs_rank/winsorize/standardize，per-date） | TS 算子（ts_*，per-code 窗口） | 结论 |
|------|------|------|------|
| 按代码分块 | ✗ 在子集上排名，语义错误；需 AST 级表达式拆分（脆弱） | ✓ 天然可分 | 否决 |
| **按日期分块** | ✓ 块内每日期横截面完整（同日期全市场股票都在块内） | ✓ warmup 重叠提供窗口历史 | **采用** |

关键事实（已核实源码）：`processors.py` 的 winsorize/standardize/rank 全部是
`.over("date")` 横截面；`cs_rank` 同类。因此**分日期块后每个日期内的计算与
整段跑完全一致**。

### 2.2 流水线形态

```
[chunk_0][chunk_1]...[chunk_N]     ← 日历切块（chunk_days 交易日/块）
   每块独立跑完整流水线：
   load_daily(date_start=load_start, date_end=chunk_end)   ← SQL 层按块过滤，内存最小
   → fill_suspensions(块内日历)                            ← 全网格限于块内
   → compute_forward_returns                                ← 块尾 5/20 天 null（真实"无未来"语义）
   → view_prices                                            ← qfq 时 adj_factor 先按全局基准归一
   → compute_formula                                        ← TS 窗口由 warmup 覆盖
   → run_process_chain                                      ← per-date，块内横截面完整
   → 丢弃 warmup 段行（date < chunk_start）
最后 pl.concat(块结果) → 现行落盘路径（panel.parquet / summary.json）
```

- 块间无数据依赖（warmup 段独立重新 load），任何块失败可单独重跑。
- `chunk_days=None`（默认）→ 现行单块路径，行为逐字节不变（向后兼容）。
- warmup 天数：**AST 自动提取**公式中所有 `ts_*`/`ta_*` 调用的窗口参数最大值
  + 20 天安全垫（覆盖 ts_delay 等偏移）；公式无窗口算子 → warmup=0
  （纯 CS 因子不需要历史）；可用 `--warmup-days` 手动覆盖。

### 2.3 qfq 复权基准对齐（唯一需要特殊处理处）

`view_prices(qfq)` 的因子 = `adj / 组内最新 adj`（面板内）。分块后每块的
"面板内"不同 → 绝对水平类因子（直接用 close 值，如 `close`、`log(close)`、
`ts_mean(close, 20)` 单独作输入）跨块有常数断层。比率类因子（returns、mom、
比值）常数缩放不变，天然安全。

解决（不改 adjust.py）：分块循环前一条轻量 SQL 取全局基准：

```sql
SELECT substr(ts_code,1,6) AS code,
       last(adj_factor ORDER BY trade_date) AS base_adj
FROM adj_factor WHERE trade_date <= ?
GROUP BY substr(ts_code,1,6)
```

块内 `adj_factor = adj_factor / base_adj` 后走现行 view_prices：
归一后组内最新 adj = 1 → factor = adj/base_adj，与整段跑（基准=全局最新）
**逐字节一致**。归一仅对 qfq 做：
- hfq（factor=adj）归一会改变结果 → 不做；
- pit_qfq（factor=adj/asof_adj）归一后分子分母同消，不变 → 不必要；
- raw 无 adj 使用 → 不必要。

### 2.4 已知限制（文档注明，不做）

1. **forward 边界 null**：每块尾 forward_5d/20d 为 null（整段跑只有样本末）。
   评估周对齐时该周缺行跳过，损失 <1%（~500 天/块丢约 1 周）。
2. **process fillna(method="forward")**：per-code 时序前向填充，块首重新开始，
   块边界前几行与整段略异。低频使用，接受。
3. **分块不改变单块容量**：块大小 + warmup ≤ 当前验证过的 ~850 交易日量级，
   默认 `--chunk-days 500`（warmup ≤ ~400 时安全）。

## 3. 接口

| 层 | 变更 |
|----|------|
| `RunContext` | 新增 `chunk_days: int \| None = None`（None=不分块） |
| CLI `factorlab run` | 新增 `--chunk-days N`、`--warmup-days N`（0=自动提取） |
| `calendar.py` | 新增 `chunk_calendar(cal, chunk_days, warmup_days) -> list[tuple[date, date, date]]`（load_start, chunk_start, chunk_end） |
| `engine/compute.py` | 新增 `_ts_window_days(formula) -> int`（AST 提取）；`run_factor` 分块循环分支 |

## 4. 测试计划（TDD）

| 测试 | 内容 |
|------|------|
| `test_chunk_calendar` | 正常（含不足一块的尾块）、warmup 越界（块首不足 warmup 截断）、chunk 精确整除、warmup=0 |
| `test_chunked_consistency`（关键回归） | 小样本（~6 个月）× 强制小 chunk（~60 天）分块 vs 不分块，**逐 cell 对比 signal**（公式含 ts_ 窗口 + cs_rank + 绝对水平 close 输入，qfq 视图）相等；forward 除块边界 null 外相等 |
| `test_chunked_pure_cs` | 纯 CS 公式（无窗口）warmup=0 时分块一致性 |
| `test_ts_window_extraction` | 提取窗口最大值：多窗口取 max、无窗口=0、变量窗口（参数化后已内联为字面量）、错误路径（窗口非 int 忽略） |
| `test_chunked_error` | chunk_days<1、warmup_days<0 报错 |
| 文档 | `docs/interface.md`：run 参数表 + "分块计算"章节（语义保证、限制、用法示例） |

## 5. 验收

1. 全量测试通过（`python -m pytest -q`）。
2. 分块一致性回归：小样本强制分块 vs 不分块 signal 逐 cell 相等。
3. 2015-2026 扩样 `crash_bottom_leader_timed` 可跑通（目标 ~6-7 块），
   触发周显著多于 14，策略档案更新。
4. 文档同步（interface.md）。

## 6. 非目标

- 不做按代码分块（CS 语义错误）。
- 不做块间 forward 重叠补偿（损失 <1%，接受）。
- 不改 fill_suspensions 本身（分块在更高层，calendar.py 只新增切块函数）。
- 不引入磁盘 spill / 内存上限自动调参。
