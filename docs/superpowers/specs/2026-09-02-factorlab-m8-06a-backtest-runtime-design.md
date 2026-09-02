# M8-06A：Backtest Runtime Contract Design

日期：2026-09-02｜Base: `a9c98b41d27ce8b93709d020681defff8c162f69`（main）

## 1. 背景：已闭合的执行/核算链

M8-01 → M8-05B 已把理想组合到账户状态的完整管道建成（全部 production
smoke 验证、Frozen DATA_CUTOFF=2026-08-14、FORMAL_GATE_START=2015-01-05）：

```
TargetPortfolio
   │ M7
   ▼
resolve_execution_schedule(M8-02)          decision → execution date
   ▼
construct_order_batch(M8-03)               OrderBatch（order intent）
   ▼
assess_open_fillability(M8-04B)            OpenFillAssessment（market eligibility）
   ▼
realize_open_fills(M8-04C)                 FillBatch（cost-aware actual fills）
   ▼
apply_fill_batch(M8-04D)                   POST_EXECUTION PortfolioState
   ▼
summarize_execution_accounting(M8-05B)     ExecutionAccountingSummary
   ▼
advance_to_next_trading_day(M8-04E)        PRE_EXECUTION @ next open（T+1 release）
   ▼
value_portfolio(M8-05B)                    PortfolioValuation（explicit marks）
```

**尚不存在**的是把这些 primitive 按 decision 序列编排的 orchestration 层。
M8-06A 只设计该层的 **contract**——API、artifact schema、NAV series
契约、daily lifecycle——**不实现**。

## 2. 设计目标与非目标

### 目标

```
1. BacktestRuntime API 契约（编排现有 primitive，不新增任何 execution math）
2. ExecutionArtifact schema（per-day 事实记录——字段全部来自已关闭 primitive
   的输出，禁止第二套计算）
3. NAV series 契约（daily point-in-time equity + return 语义 + 有效期 Gate）
4. Daily lifecycle（一天内的精确 phase 状态机与边界情形）
```

### 非目标（实现阶段禁止，设计亦不得依赖）

```
- 接入真实回测循环 / 修改 M6 engine / 修改 strategy runtime
- 写 artifact persistence（文件/DB 落盘——schema 先行，persistence 属实现阶段）
- 引入 strategy logic（runtime 只消费 TargetPortfolio + ExecutionSpec +
  cost spec + DB，同 M8-03 链）
- performance metrics（drawdown/Sharpe/benchmark 属后续指标层）
- NEXT_CLOSE execution（M8 v1 仍 NEXT_OPEN only）
```

## 3. BacktestRuntime API 契约

### 3.1 建议入口

```python
def run_backtest(
    target: TargetPortfolio,
    execution_spec: ExecutionSpec,
    db_path: Path,
    *,
    marks: MarksPolicy,            # §5.2 显式 mark 来源策略（v1 设计占位）
    decision_range: tuple[datetime.date, datetime.date] | None = None,
) -> BacktestResult: ...
```

约束：

- **不接收 StrategySpec/SignalArtifact**——目标权重已冻结在
  TargetPortfolio（M8-03 原则延续）
- **execution_spec 必须显式提供**：M8-05A §76 的 Gate 在此生效——cost
  model 必须显式选择（不允许依赖 `ExecutionSpec()` 的隐式默认；zero-cost
  仅当调用方显式声明时允许，文档记录该 run 是 zero-cost research run）
- **不接收 initial_cash 之外的账户初始化参数**——现金 authority 始终是
  运行期 state.cash（M8-03 §2 原则），initial_cash 只初始化 day-1 PRE state

### 3.2 编排循环（伪代码——只调用已关闭 API）

```
state = PortfolioState(decision_0 前 PRE, initial_cash, positions=[])
for decision_d in target.decision_dates（∩ decision_range）:
    schedule_row = resolve_execution_schedule 结果中该 decision 的行
    exec_date = schedule_row.execution_date
    if exec_date 超出 frozen daily coverage → ExecutionDataQualityError
        （M8-02 calendar ≠ data availability；不 fallback）
    snapshot  = load_market_open_snapshot(db, exec_date, planning codes)
    orders    = construct_order_batch(target, schedule, state, snapshot, rules, decision_d)
    assessment= assess_open_fillability(orders, snapshot)
    fills     = realize_open_fills(orders, assessment, state, snapshot, rules,
                                   execution_spec.cost_model)
    post      = apply_fill_batch(state, fills)
    summary   = summarize_execution_accounting(state, fills, post)
    nav_entry = value_portfolio(post, marks.at(exec_date, post.positions))
    artifact  = ExecutionArtifact(decision_d, exec_date, state, orders, assessment,
                                  fills, post, summary, nav_entry)   # §4
    state     = advance_to_next_trading_day(post, fills, db)          # → next PRE
return BacktestResult(artifacts, nav_series, state)
```

### 3.3 错误语义

```
- 任何 ExecutionDataQualityError / ValueError / NotImplementedError
  → 整个 run fail fast（不 per-day skip、不降级、不改成交结果）
  （M8-04A Gate：READY_WITH_EXPLICIT_DATA_ERROR_GATE——数据坏即 run 坏）
- calendar transition 成功 ≠ market data 存在（M8-04E 边界）
- 单日 empty event（无订单/全 blocked）是合法 execution event，
  产生 artifact 行与 NAV 行（0 fills、0 cash delta）
```

### 3.4 确定性

- 相同输入（target/spec/db/range）→ 相同 artifact 序列（bitwise）；
  各 primitive 已保证，编排层不得引入 dict/set 无序迭代
- BacktestResult 为 frozen/immutable 值对象

## 4. ExecutionArtifact schema

### 4.1 定位

ExecutionArtifact 是**一天的事实记录**（decision → 该 execution event 的
全部实际输出引用），不是新计算。字段必须与已关闭 primitive 输出**逐字一致**
（同一 dtype/同一 Float64 路径），禁止：重新 net、重新聚合、重新估值。

### 4.2 Schema（frozen dataclass；persistence 格式属实现阶段）

```
ExecutionArtifact:
    decision_date      Date
    execution_date     Date（> decision）
    pre_state          PortfolioState（该日 PRE——决策/资金输入时点）
    orders             OrderBatch
    assessment         OpenFillAssessment
    fills              FillBatch（可能 typed empty）
    post_state         PortfolioState（POST_EXECUTION）
    accounting         ExecutionAccountingSummary
    nav                PortfolioValuation（post + 该日 marks）
    disposition_counts 诊断 ints：{fillable, blocked_suspension,
                        blocked_limit_up, blocked_limit_down}（派生计数，
                        只读不改变语义）
```

不变式（validator 或 runtime 断言）：

```
artifact.post_state.cash == pre_state.cash + Σ fills.effective_cash_delta
                          == accounting.cash_after
artifact.pre_state 为前一 artifact 的 advance_to_next_trading_day 输出
  （首日除外——由 initial_cash 初始化）
每个字段的 domain validator 已被各自 primitive 保证——artifact 只引用，
不复制计算
```

### 4.3 BacktestResult

```
BacktestResult:
    artifacts       tuple[ExecutionArtifact, ...]（decision 有序）
    nav_series      NavSeries（§5）
    final_state     PortfolioState（最后一个 execution event 的
                    advance_to_next_trading_day 输出——PRE @ next open）
```

## 5. NAV series 契约

### 5.1 NAV 语义（沿用 M8-05B）

```
NAV_t = cash_t + Σ(quantity_t × mark_price_t)     # 货币金额
```

- 每个 execution event 产生一个 NAV 条目（POST state + 该日 marks）
- **不是 normalized index**；normalized/unit_nav/returns 属指标层

### 5.2 Mark 来源策略（MarksPolicy——v1 设计占位，实现前关闭）

M8-05B 明确 marks 由 caller 提供、kernel 不做 price sourcing。Runtime
设计需要把该策略显式化（否则 NAV series 无定义）：

```
候选 v1：explicit marks = 当日 raw open（execution price basis）
   - POST state 的持仓以当日 execution open 估值（与成交同基准，
     天然支持 §5.4 value-neutrality sanity）
   - 停牌/无 open 的持仓 → 需要 stale-mark 或 suspended-mark 政策
     （未实现——见 §8 开放问题 1）
候选 v2：caller 提供的 marks frame per date（完全显式，kernel 零 sourcing）
```

设计决定：**MarksPolicy 是 runtime 输入**（显式 marks 或 open-based），
默认不允许隐式 close/qfq 定价（M8-05B 禁令延续：actual shares × qfq
无账户语义）。

### 5.3 Return 契约

```
simple return（validity window 内）：
R_t = NAV_t / NAV_{t-1} - 1
仅在同一 marks basis 的连续条目间定义（basis 变化 → series 断开）
```

实现阶段才产生 return 序列；drawdown/Sharpe/benchmark 明确不在 M8-06。

### 5.4 Value-neutrality sanity（每日不变量）

每个 execution event：

```
ZERO_COST_ZERO_SLIPPAGE 下（runtime 可检测：fills.total_fees==0 且
execution_price==reference_price 全行）：
  POST NAV（execution-open marks）== PRE NAV（同 basis）== 1,112,200 式
  （M8-05B production 已证明；runtime 将其作为每日常规 sanity assert）
```

fee>0 时：POST NAV == PRE NAV - total_fees（同 basis、同 marks）。

### 5.5 Corporate-action Gate（跨期 NAV 的硬边界）

**M8-06A 设计声明**：PortfolioState 尚无 corporate-action share
transition（split/stock dividend/consolidation/rights issue）——
**禁止**在无法证明 share-unit continuity 的情况下产出跨 CA 的连续
NAV/return 序列：

```
- 单 run 内 NAV series 的有效期 = 持仓 share-unit basis 不变的窗口
- runtime 必须具备检测能力（候选：adj_factor 跳跃 / stock_basic
  事件）或显式 Gate（run 覆盖 CA 事件日 → fail fast，附原因）
- 在 CA handling 落地前：跨年度/full-history NAV series 不得宣称
  production-ready（M8-05B §107 的 Gate 在此落实为 runtime 契约）
```

## 6. Daily lifecycle

### 6.1 状态机（一天内）

```
PRE_EXECUTION(d) ──construct_order_batch──▶ OrderBatch
      ▲                                        │
      │ advance_to_next_trading_day            ▼
      │ (fills, trade_cal)            OpenFillAssessment
      │                                        │
      │                                        ▼
      │                               realize_open_fills
      │                                        │
      │                                        ▼
      │                               POST_EXECUTION(d)
      │                                        │
      │                              apply_fill_batch
      │                                        ▼
      │                               FillBatch ──▶ accounting ──▶ NAV entry
      └───────────────────────────────────┘
```

### 6.2 Phase 规则

```
- 每 execution date 恰产生：PRE(入) → POST(出)；POST 是必须可审计的真实
  状态（M8-04D §65）
- 隔夜 transition（POST(d) → PRE(next open)）只发生一次（M8-04E；
  对 PRE 输出再调用 → ValueError——run 循环自然防重）
- same-day BUY 在 POST 中 sellable=0（T+1）；PRE(next) 才释放
```

### 6.3 边界情形（均为合法 execution event，产生 artifact 行）

```
- decision 日 target all-cash / 0 orders → empty OrderBatch/assessment/fills
  → POST == PRE（cash/positions 不变，phase 变）、accounting 全 0、
  NAV 同 basis 不变
- 全 blocked（suspension/limit）→ empty FillBatch → cash 不变
- 无下一开放日（frozen cutoff 前最后一个 execution）→
  advance_to_next_trading_day ValueError → run 在该点终止
  （trailing unresolved 属合法终止，不 drop 中间结果）
- decision 序列要求 execution_date 严格递增（schedule domain 已保证）
```

## 7. Data & 环境 gates（runtime 必须遵守的既有契约）

```
- FORMAL_GATE_START=2015-01-05 / DATA_CUTOFF=2026-08-14（frozen）
- M8_04_OPEN_LIMIT_DATA_GATE = READY_WITH_EXPLICIT_DATA_ERROR_GATE
  （异常 evidence → ExecutionDataQualityError → run fail fast）
- M8-02：trade_cal ≠ daily coverage；M8-04E：calendar transition ≠ market
  availability（run 触及 cutoff 后开放日 → 明确的 coverage 错误）
- ExecutionCostSpec 显式配置 Gate（§3.1）
- NEXT_OPEN only（NEXT_CLOSE 全链未实现——run 不得生成 NEXT_CLOSE 事件）
```

## 8. 依赖边界 / 零修改承诺（设计约束，实现阶段同样适用）

```
编排层新增（实现阶段）：
    execution/backtest.py（run_backtest + BacktestResult）
    domain/backtest.py（ExecutionArtifact / NavSeries 契约——若需要）

零修改：
    orders / fillability / fills / state / overnight / costs / spec /
    rules / calendar / market / suspension / accounting / valuation
    domain/execution.py / domain/accounting.py
    M6 engine / strategy runtime / data 层 / DB
```

## 9. 开放问题（实现 M8-06 前必须关闭）

```
1. Mark 来源策略定稿：open-based v1 vs caller-explicit marks；
   停牌/无 open 持仓的估值政策（suspension mark policy 未实现）
2. Corporate-action Gate 实现路径：adj_factor 跳跃检测 vs 显式事件表；
   决定"跨 CA 日 fail fast"还是"按窗口分段 series"
3. Artifact persistence 格式：parquet 目录 vs 单 DB 表；与 results/
   research 分支边界（回测输出属 research 内容——分支约定待定）
4. Run 范围控制：decision_range / universe 过滤是否进 v1（当前倾向不进）
5. Performance 指标层（drawdown/Sharpe）明确隔离在 M8-06 之后
```

## 10. 验收基线（设计完成即满足）

```
- §3 API 契约明确（输入/输出/错误/确定性）
- §4 ExecutionArtifact schema 全字段可溯源到已关闭 primitive（零新计算）
- §5 NAV series 契约含 basis/return/corporate-action Gate 语义
- §6 daily lifecycle 状态机 + 边界情形完整
- 零实现承诺记录（§8）；开放问题清单（§9）
```
