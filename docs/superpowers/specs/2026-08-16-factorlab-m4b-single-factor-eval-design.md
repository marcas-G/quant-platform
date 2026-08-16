# FactorLab M4b 单因子评估深化设计文档

日期：2026-08-16
状态：待评审
依赖主设计：`docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md`
前置：M4a（引擎接入与评估——run 命令/quant_core 桥接/复权消费）

## 1. 背景与目标

M4b 聚焦**单因子**评估深化（用户决策：多因子——compare/composite/spec 内 factors/combine——全部后置）：

1. **分层回测**（eval/layered.py）：十分位组合累计净值 + long-short + 摘要指标——run 产出完整单因子评估。
2. **CLI list/show**：已保存因子列表与单因子摘要。
3. **M4a 遗留接线**：pit_qfq 消费、weekly.parquet 落盘优化（周频对齐面板）、路径锚定。

## 2. 分层回测（eval/layered.py）

### 2.1 输入与语义

```python
def layered_backtest(panel: pl.DataFrame, direction: int,
                     n_groups: int = 10, cost: float = 0.0) -> dict
```

- 输入：**周频面板**（date/code/signal/forward_return_5d——M4a 评估输入同源）。
- **期数口径**：signal/forward_return_5d 为 null 的行不参与分档与收益；某周**全部**行
  无效（头部 ts 窗口未满/尾部无未来收益）则该周不计入 `periods`——与 quant_core 周频
  评估的 `n_weeks` 一致（集成断言 `bt["periods"] == evaluation["n_weeks"]`，实测 2 年
  104 个对齐周中 98 个有效周）。周内部分行 null 仍计入（组内等权平均忽略 null）。
- 每期（周）按 signal 排序分 `n_groups` 档（默认十分位）。
- **方向感知**：`direction=1`（越高越好）时 D1 = signal 最高档；`direction=-1` 时
  D1 = signal 最低档（两者都是"最佳档"）。排序后按方向映射档位编号。
- 各档组合：当周该档股票的 `forward_return_5d` **等权平均** → 周收益 → 净值累积（连乘）。
- **long-short**：D1（最佳档）净值 − D10（最差档）净值。
- **成本**：`cost` 参数（默认 0）——无调仓成本建模（主 spec 分层回测为等权组合，
  成本建模不在 v1 范围；参数预留）。

### 2.2 输出结构

```python
{
  "n_groups": 10,
  "periods": 98,                      # 回测期数（周）
  "net_values": {                     # 各档净值序列（含 D1_D10 long-short）
    "D1": [1.0, 1.01, ...], "D2": [...], ..., "D10": [...],
    "long_short": [1.0, 1.02, ...],
  },
  "summary": {                        # 每档 + long-short 的摘要指标
    "D1": {"annual_return": 0.12, "annual_vol": 0.18, "sharpe": 0.67,
           "max_drawdown": -0.15, "win_rate": 0.55},
    ...,
    "long_short": {...},
  },
  "dates": ["2024-01-05", ...],       # 净值序列对应日期
}
```

- 年化：周收益均值 × 52；年化波动：周收益 std × √52；夏普 = 年化收益/年化波动。
- 最大回撤：净值峰值到谷值的最大跌幅。
- 胜率：周收益 > 0 的比例。

### 2.3 边界

- 面板为空/单期 → 返回空结构与 0 指标（不崩溃）。
- 某期某档无股票 → 该期该档收益 null（净值保持前值，不跳变）。
- signal 全 null（或过滤后无有效行）→ 空回测（`periods=0`、`net_values={}`，不产出
  平值 1.0 假净值）。
- n_groups 超过股票数 → 每档可能空（null 处理同上）。

## 3. run 命令扩展与 M4a 遗留

### 3.1 `--backtest/--no-backtest`（默认产出）

```python
factorlab run <spec> [--backtest/--no-backtest] [--groups 10] ...
```

- 默认 `--backtest`：run 完成后追加 `layered_backtest` 到 summary.json 的 evaluation。
- `--no-backtest`：跳过分层回测（快速评估——只需 IC/十分位/换手/覆盖）。

### 3.2 weekly.parquet 落盘优化

- 改为落盘**周频对齐后**的面板（评估与回测的实际输入）——不再冗余日频数据
  （原落盘 result.panel 日频，与 panel.parquet 重复）。
- 保留 panel.parquet（日频面板——因子值明细）。

### 3.3 pit_qfq 消费

- `spec.adjustment="pit_qfq"`：`view_prices(panel, "pit_qfq", asof=spec.date.end)`
  ——研究日视角（asof 之后无信息）。M4a 的 view_prices 已支持 asof 参数；run_factor
  装配中传 `asof=spec.date.end`（spec.date.end 为空时默认数据末端日期）。

### 3.4 路径锚定

- `settings.results_dir: Path = Path("results")`——`FACTORLAB_RESULTS_DIR` 可覆盖；
  run 的 `--output-dir` 缺省 `results_dir / <name>`（相对 cwd 的依赖消除：results_dir
  显式配置或 env）。

## 4. CLI list / show

### 4.1 `factorlab list`

- 扫描 `results_dir/*/summary.json`。
- 输出：名称/类别/方向/最近运行时间（summary 时间戳）/IC mean/十分位 spread。
- 按最近运行时间排序；无 results 目录时提示。

### 4.2 `factorlab show <name>`

- 读 `results_dir/<name>/summary.json` + panel.parquet 元信息。
- 输出：spec 原文、计算摘要（universe/日期/行数/null 比例）、评估
  （IC/PearsonIC/十分位/换手/覆盖）、分层回测摘要（如存在）。

## 5. 测试策略

- **layered 单测**：构造周频面板（已知 signal 排序与 forward）验证：档位划分、
  方向映射（direction ±1 的 D1 互换）、净值累积数学、long-short 差、摘要指标
  （手工推演）、边界（空面板/单期/档空/null）。
- **run 参数**：`--backtest/--no-backtest` 行为（summary 有无 layered_backtest）、
  `--groups` 传递。
- **weekly 落盘**：weekly.parquet 是周频面板（行数 = 周数 × 股票数）。
- **pit_qfq**：run_factor 装配 asof 传递（view_prices 调用参数）。
- **list/show**：tmp results 目录构造多个 summary → 列表/摘要正确；无 results 提示。
- **集成**（真实平台库）：run → layered_backtest 产出合理（净值序列长度 = 周数、
  摘要指标有限值）。

## 6. 明确不做（M4b）

- 多因子：compare（因子对比）、composite（组合合成）、spec 内 factors/combine。
- 调仓成本建模（cost 参数预留，默认 0）。
- Web 可视化（M5）。
- 指数基准对比/超额收益（净值相对指标已够，基准留 M5 可视化）。
