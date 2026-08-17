# FactorLab 相关性指标 + 经典因子种子 设计文档

日期：2026-08-18
状态：待评审
前置：M1-M5 + 挖因子 skill（批次 3 完成，140+ 因子）

## 1. 背景与目标

批次 3 挖掘验证：反转家族内部因子相关性 0.71-0.92（高），symrun/偏度与反转
家族近正交（0.07-0.23）——因子库多样性不足，~90% 是反转家族变体。

**核心目标**：
1. **相关性指标**：平台内置因子两两相关度量（CLI + Web 热力图），量化
   多样性、支持组合分析。
2. **经典因子种子扩充**：加入经典 A 股因子（价值/波动/彩票/流动性/规模/技术）
   作为新种子家族——多样性来源，表现差也可（正交性优先）。

**边界**（用户确认）：四组经典因子全做（重叠性低、花样多优先）；corr CLI + Web
热力图都做；不改评估语义。

## 2. 数据与平台改动

### 2.1 _DAILY_BASIC_MAP 扩展

daily_basic 现 join 字段：turnover/total_mv/circ_mv。新增映射（3 行）：

```python
_DAILY_BASIC_MAP = {
    "turnover": "turnover_rate", "total_mv": "total_mv", "circ_mv": "circ_mv",
    "pe_ttm": "pe_ttm", "pb": "pb", "dv_ratio": "dv_ratio",
}
```

公式引用 pe_ttm/pb/dv_ratio 自动加载。**注意**：这些字段历史覆盖不全
（早期缺失 → null 传播），因子档案记录缺失率。

### 2.2 相关性计算（corr 命令）

`factorlab corr <name1> <name2> [<name3>...]`（≥2）：

- 读 `results/<name>/panel.parquet` 的 date/code/signal，按 date+code inner join
- 输出两两矩阵，两种口径：
  - **周度横截面秩相关均值**（主指标，与 IC 同口径）：每周对横截面
    Spearman（rank 后 Pearson 等价），跨周平均
  - **全局 Pearson**（辅助）
- 任一因子无 results → 报错列出缺失
- 内存护栏：join 后行数 > 2000 万 → 提示并降采样（每周最多 5000 股）

### 2.3 Web 热力图

- charts.py 新增 `correlation_heatmap_figure(names, matrix)`（plotly
  heatmap，dataviz diverging 色板：正蓝负红、0 白）
- 因子详情页新增"相关因子"区块：该因子与库内其他因子的相关性
  （默认与全部已入库因子算，页面展示 top 相关；数据来自 corr 逻辑复用）

## 3. 经典因子种子（10 个新家族）

每个 = factor/*.yaml + docs/factors/*.md 档案（成为挖因子新种子池）。
direction 依据经典文献预设，跑出结果后档案记录实际表现（差也可）。

| # | 因子 | 公式（polars_ta 表达） | direction | 维度 |
|---|------|----------------------|-----------|------|
| 1 | `value_ep` | `1 / pe_ttm` | 1（低 PE 高收益） | 价值 |
| 2 | `value_bp` | `1 / pb` | 1 | 价值 |
| 3 | `dividend_yield` | `dv_ratio` | 1（高股息高收益） | 价值 |
| 4 | `low_vol_20d` | `-ts_std_dev(returns(close), 20)` | 1（低波动高收益，负号翻正） | 波动 |
| 5 | `max_effect_20d` | `ts_max(returns(close), 20)` | -1（大彩票股低收益） | 彩票 |
| 6 | `amihud_illiq_20d` | `ts_mean(abs(returns(close)) / amount, 20)` | 1（非流动性溢价） | 流动性 |
| 7 | `small_cap` | `-log(circ_mv)` | 1（小市值溢价） | 规模 |
| 8 | `rsi_reversal_14` | `tdx.ts_RSI(close, 14)` | -1（超买反转） | 技术 |
| 9 | `volume_ratio` | `volume_ratio`（量比字段） | -1（高量比低收益） | 技术 |
| 10 | `turnover_level` | `turnover` | -1（高换手低收益） | 流动性 |

说明：
- pe_ttm/pb/dv_ratio/volume_ratio 来自 daily_basic 扩展（§2.1）
- tdx.ts_RSI 已注册（wq/ta/tdx 477 算子）
- 缺失率高的因子（value 早期缺数据）档案记录 signal_null_ratio，判定按实际

## 4. 测试策略（TDD）

- **corr 命令**：两因子（已知相关 ~0.9 对 vs 近正交对）、三因子矩阵、
  缺 results 报错、单因子参数报错、周度秩相关 vs 全局 Pearson 口径正确性
  （用构造面板验证 spearman 值）
- **_DAILY_BASIC_MAP 扩展**：公式引用 pe_ttm 加载成功、缺失行为（null 传播）
- **10 个经典因子**：每个 e2e（run 成功、summary 字段齐全、档案生成）；
  至少 1 个价值因子 + 1 个技术因子跑通验证字段映射
- **Web 热力图**：详情页含相关区块（mock 数据）；无结果因子降级不崩溃
- 全量 `python -m pytest -q` 通过

## 5. 明确不做

- 不做因子聚类/分组（相关性矩阵先行）。
- 不做相关性阈值自动建议。
- 不引入财务三表（数据未建）。
- 不改评估语义（target/方向）。
