# 因子档案模板

> 本文件是因子档案的标准模板。**新建因子档案**：复制本文件为
> `docs/factors/<name>.md`，删除本说明块，按各章节填写。
> **可执行定义**：`factor/<name>.yaml`（机器执行）与本文档（人读档案）并行存放；
> 两者必须一致，改 yaml 后同步本档案。

<!-- 元信息块：参考项目惯例（自包含、标签化）。status 取值：探索中 / 候选 / 观察中 / 已废弃 -->
---
xname: <因子名>              <!-- 与 factor/<name>.yaml 的 name 一致 -->
formula: |                   <!-- 一行核心公式摘要（完整公式见 §参数与实现） -->
  <signal = ...>
tags: [<标签1>, <标签2>]     <!-- 挖掘方向、迭代阶段、相关文档 -->
params: {<p1>: <默认值>, <p2>: <默认值>}
status: 探索中
created_ts: <YYYY-MM-DD>
updated_ts: <YYYY-MM-DD>
---

# <因子名> 因子档案

## 1. 元信息

| 项 | 值 |
|----|----|
| 名称 | `<name>`（= `factor/<name>.yaml`） |
| 类别 | `<category>`（custom / 平台内置） |
| 方向 | `<1 | -1>`（正 = 值越大预期收益越高） |
| 状态 | `<status>` |
| 标签 | `<tags>` |
| 创建 | `<created_ts>` |
| 最近更新 | `<updated_ts>` |

## 2. 逻辑

**动机**：为什么做这个因子？（观察到的市场现象 / 对某个已知因子的改进 / 数据可用性驱动）

**核心逻辑**：一段话讲清楚信号想捕捉什么、怎么捕捉。

**数学表达**：

```
<公式，含参数符号>
```

**输入数据**：`<所用字段，如 close/volume/amount>`

## 3. 参数与实现

### 参数表

| 参数 | 默认值 | 含义 | 有效范围 |
|------|--------|------|----------|
| `<p1>` | `<v1>` | <含义> | <范围> |

### 处理链

```
universe: <规则>
date: <期间>
process: <winsorize/standardize 等>
target: <forward_return_5d 等>
adjustment: <qfq 等>
```

### 实现（YAML 全文）

```yaml
<factor/<name>.yaml 全文，与文件保持逐字一致>
```

## 4. 验证结果

> 数据快照自 `results/<name>/summary.json`（运行 `factorlab run` 后更新）。
> 本表为某次快照；重跑后如需更新，用新的 summary.json 数值替换并刷新
> `updated_ts` 与下方判定。

### 样本

| 项 | 值 |
|----|----|
| 区间 | `<date_start> ~ <date_end>` |
| 周数（有效） | `<n_weeks>` |
| 平均股票数 | `<n_stocks_avg>` |
| 复权 | `<adjustment>` |
| 信号缺失率 | `<signal_null_ratio>` |

### IC

| 指标 | 值 |
|------|----|
| RankIC mean | `<mean>` |
| t 值 | `<t_stat>` |
| IR | `<ir>` |
| 近 26 周 mean | `<recent_26w_mean>` |
| 近 26 周 t | `<recent_26w_t>` |
| PearsonIC mean | `<pearson mean>`（rank 与 pearson 符号不一致时说明原因） |

### 分层（十分位等权）

| 项 | 值 |
|----|----|
| spread（D1−D10 周均收益） | `<spread>` |
| 单调性 | `<monotonic>` |
| D1 mean_ret | `<g0>` |
| D10 mean_ret | `<g9>` |

### 判定

对照 `docs/factor-mining-playbook.md` 的评估阈值：

- <结论：如 "IC t=3.47 显著（\|t\|>2），IR 0.26，全期有效；近 26 周衰减（t≈0）→ 观察中">
- <下一个动作：如 "参数扫描 / 换样本期复验 / 弃用">

## 5. 迭代历史

每次改动一个条目（倒序，最新在上）。变体（`run --set`）记录在这里，不单独建档案。

| 日期 | 变体/版本 | 改动 | IC mean | t | 结论 |
|------|-----------|------|---------|---|------|
| `<YYYY-MM-DD>` | `<name>`（初始） | <做了什么> | `<mean>` | `<t>` | <有效/无效/衰减> |

## 6. 风险与备注

- <失效风险：逻辑依赖的市场环境、过拟合信号、近 26 周衰减观察>
- <数据风险：缺失率、停牌、复权方式影响>
- <其他备注：与相关因子的相关性、组合使用注意、已知 bug/限制>

---
*档案规范见本模板；因子挖掘方法论见 `docs/factor-mining-playbook.md`。*
