---
name: factor-mine
description: 挖因子循环。随机选一个已入库因子为种子，分析其隐含假设（每个实现选择背后的"为什么"）、审核假设（语义矛盾/数据可实现）、在种子假设集合上变异/精确化（可多个，不引入无关新假设）、实现新因子、subagent 审核代码、跑结果、按模板入库。调用方式 /factor-mine [N轮数，默认1]。
---

# 挖因子（Factor Mining）

以因子库中现有因子的**隐含假设**为挖点，循环产出更精确的因子表达。
参照设计：`docs/superpowers/specs/2026-08-17-factorlab-factor-mine-skill-design.md`。

## 输入

- `/factor-mine` — 跑 1 轮
- `/factor-mine 5` — 连续 5 轮（轮间不停顿，用户可中断）

## 前置检查

1. 因子库非空：`ls docs/factors/*.md`（排除 `_template.md`），空则报错并停止。
2. 平台数据可用：CLI 不报错（平台库在 `data/factorlab.duckdb`）。
3. 每轮开工前向用户播报：`第 k/N 轮：种子=<seed>`，然后继续（不等待）。

## CLI 调用方式（重要）

`factorlab` 不在 bash PATH 中。用以下任一方式（本 skill 内所有 `factorlab`
命令均代换为 `$FLAB`）：

```bash
FLAB=/c/Users/ThinkPad/AppData/Roaming/Python/Python313/Scripts/factorlab.exe
# 或先验证：where factorlab / pip show factorlab 找到 console script 路径
```

前置检查用：`$FLAB list`。

## 每轮流程（8 步）

### 1. 种子选择

```bash
python - <<'EOF'
import random, pathlib
files = [p.stem for p in pathlib.Path('docs/factors').glob('*.md')
         if p.name != '_template.md' and p.stem not in USED]
print(random.choice(files))
EOF
```

- 同一批连续轮次内种子互不重复（`USED` 为已用种子列表，逐轮累加；
  执行时把占位符替换成 Python 集合字面量，如 `USED = {'reversal_20d'}`）；
  所有种子都轮过一遍后循环回来（忽略 USED）。
- 读 `docs/factors/<seed>.md` 全文 + `factor/<seed>.yaml`。

### 2. 假设分析（用 assumption-review.md 模板）

自由分析（不分类框、创造力为主）：**枚举种子因子每个实现选择背后的隐含假设**——
窗口长度、数据字段口径、权重/聚合方式、对股票的同质性假设、调仓/持有期、
处理链（winsorize/standardize）、符号方向、缺失处理……每个"为什么"都是一条
隐含假设。重点找**通常没人显式关注的**假设——那里是挖点。

### 3. 假设审核（每条判定：成立 / 可疑 / 证伪 / 可精确化）

- **语义矛盾**：假设间互斥？与平台语义冲突？（TS/CS 分区、防未来、方向语义——
  见 `docs/interface.md` §DSL 语义与防未来、`docs/factor-mining-playbook.md` §3.3）
- **数据可实现**：字段存在性（`docs/interface.md` §数据字段；可查库
  `python -c "import duckdb;print(duckdb.connect('data/factorlab.duckdb').execute('select column_name from information_schema.columns where table_name=\'daily\'').fetchall())"`）、
  窗口长度 vs 历史（数据自 2000-01-04）、缺失率预估（种子档案 signal_null_ratio 参照）。
- **证据**：种子档案 §4 验证数据（IC/t/近 26 周/分层）+ 已知市场异象知识。

### 4. 变异设计

- 在种子假设集合上变异/组合，**可一次变异多个**；不引入与种子无关的全新假设。
- 目标是**隐含假设的显式化与精确化**——更详细准确的因子表达，
  **不追求表达式深度**（不加复杂度）。
- 记录：保留哪些假设、精确化/变异哪些（变异成什么、为什么）、
  变异后假设集合的语义一致性（重新过 §3 矛盾检查）。
- 新因子名 `<seed>_<variant>`（小写蛇形，如 `reversal_20d_lowturn`）。
- 变异点清单写入一个临时记录（`results/_mine_round_<n>.md`），
  供实现与代码审核使用——它是对照物，之后不入库。

### 5. 实现

- 写 `factor/<name>.yaml`，结构变异 = 新 spec（**不用 `--set`**；
  `--set` 仅用于同结构参数扫描）。
- 语义↔代码映射表：每条变异语义 → 公式行（写在变异点记录里）。
- 沿用平台自由代码公式（def/参数化，见 `docs/interface.md` §formula 与
  `factor/vol_run_energy.yaml` 范例）。direction 语义要与变异后假设一致。

### 6. 代码审核（独立 subagent）

按 `.claude/skills/factor-mine/code-review.md` 提示词 dispatch 一个
general-purpose subagent，输入：变异点记录 + `factor/<name>.yaml` +
`factor/<seed>.yaml`。审核不通过则修复后重审（修复后必须再次审核）。

### 7. 运行

```bash
factorlab run factor/<name>.yaml
```

- 失败：读报错修复重跑（DSL 错误、内存限制、空面板等）。
- 成功：记录 `results/<name>/summary.json` 关键指标。

### 8. 入库

1. 对照 `docs/factor-mining-playbook.md` §4.1 阈值判定（显著/边际/无效）。
2. 复制 `docs/factors/_template.md` → `docs/factors/<name>.md`，逐节填写：
   验证数据快照自 `results/<name>/summary.json`（注明快照日期）；
   状态按判定（候选/观察中/无效）；§2 逻辑写变异后的假设表达。
3. 种子档案 `docs/factors/<seed>.md` §5 迭代历史加一行（日期/新因子/变异点/结果/结论）。
4. 互链：新档案 §6 备注链接 `[<seed>.md](<seed>.md)`；种子档案对应行注明新档案。
5. `git add factor/<name>.yaml docs/factors/<name>.md docs/factors/<seed>.md`
   → `git commit -m "feat(factor): <name> — <变异点一句话>"`。

## 全局规则

| 规则 | 内容 |
|------|------|
| 隐含假设优先 | 挖点是"没被关注到的隐含假设"——改进表达精度，不加深公式复杂度 |
| 聚焦变异 | 变异限于种子假设集合；可多个；不引入无关新假设 |
| 可归因 | 变异点逐一记录，结果优劣回溯到具体假设 |
| 负结果入库 | 不显著也建档案（判定"无效/证伪"），种子档案同样记录 |
| 审核分工 | 假设审核主 agent 做；代码审核独立 subagent（code-review.md） |
| 轮间状态 | 种子互异列表、轮数计数仅当批内有效；批次结束归档 |
| 资源 | 每轮 ~1 次全市场 run（30-60s）+ 1 个 subagent 审核；results/ 每轮数十 MB；16GB 内存护栏（SQL-first）不变 |

## 明确不做

- 不引入种子无关的全新假设方向。
- 不自动参数扫描（那是手动 `--set` 研究）。
- 不改平台代码（若演练暴露平台缺口，另开 spec）。
- 不做多因子组合。

## 模板文件

- `assumption-review.md` — §2/§3 假设分析与审核工作模板（本 skill 目录内）
- `code-review.md` — §6 subagent 代码审核提示词（本 skill 目录内）
- `docs/factors/_template.md` — 入库档案模板
- `docs/factor-mining-playbook.md` — 评估阈值与方法论
