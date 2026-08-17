# 挖因子 Skill 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建 `/factor-mine` 项目级 skill——以因子库种子因子的隐含假设为变异点，自动循环"分析→审核→变异→实现→审核→跑→入库"，一次调用连续 N 轮。

**Architecture:** 纯流程/提示词文档（不改平台代码）：`.claude/skills/factor-mine/` 下 SKILL.md（主指令 8 步流程 + 规则）+ assumption-review.md（假设分析审核模板）+ code-review.md（subagent 审核提示词）。验证 = 端到端演练一轮真实挖因子。

**Tech Stack:** Markdown skill（SKILL.md frontmatter）+ python random 选种子 + factorlab CLI + subagent 审核。

**依据 spec：** `docs/superpowers/specs/2026-08-17-factorlab-factor-mine-skill-design.md`

---

### Task 1: SKILL.md 主指令

**Files:**
- Create: `.claude/skills/factor-mine/SKILL.md`

- [ ] **Step 1: 写 SKILL.md**

```markdown
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
2. 平台数据可用：`factorlab list` 不报错（平台库在 `data/factorlab.duckdb`）。
3. 每轮开工前向用户播报：`第 k/N 轮：种子=<seed>`，然后继续（不等待）。

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

- 同一批连续轮次内种子互不重复（`USED` 为已用种子列表，逐轮累加）；
  用完后所有种子都轮过一遍则循环回来（忽略 USED）。
- 读 `docs/factors/<seed>.md` 全文 + `factor/<seed>.yaml`（若档案内 YAML 非全文）。

### 2. 假设分析（用 assumption-review.md 模板）

自由分析（不分类框、创造力为主）：**枚举种子因子每个实现选择背后的隐含假设**——
窗口长度、数据字段口径、权重/聚合方式、对股票的同质性假设、调仓/持有期、
处理链（winsorize/standardize）、符号方向、缺失处理……每个"为什么"都是一条
隐含假设。重点找**通常没人显式关注的**假设——那里是挖点。

### 3. 假设审核（每条判定：成立 / 可疑 / 证伪 / 可精确化）

- **语义矛盾**：假设间互斥？与平台语义冲突？（TS/CS 分区、防未来、方向语义——
  见 `docs/interface.md` §DSL 语义与防未来、`docs/factor-mining-playbook.md` §3.3）
- **数据可实现**：字段存在性（`docs/interface.md` §数据字段；可查库
  `python -c "import duckdb;print(duckdb.connect('data/factorlab.duckdb').execute('select column_name,data_type from information_schema.columns where table_name=\'daily\'').fetchall())"`）、
  窗口长度 vs 历史（数据自 2000-01-04）、缺失率预估（种子档案 signal_null_ratio 参照）。
- **证据**：种子档案 §4 验证数据（IC/t/近 26 周/分层）+ 已知市场异象知识。

### 4. 变异设计

- 在种子假设集合上变异/组合，**可一次变异多个**；不引入与种子无关的全新假设。
- 目标是**隐含假设的显式化与精确化**——更详细准确的因子表达，
  **不追求表达式深度**（不加复杂度）。
- 记录：保留哪些假设、精确化/变异哪些（变异成什么、为什么）、
  变异后假设集合的语义一致性（重新过 §3 矛盾检查）。
- 新因子名 `<seed>_<variant>`（小写蛇形，如 `reversal_20d_lowturn`）。
- 变异点清单写入一个临时记录（`results/_mine_round_<n>.md` 或工作区说明），
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
`factor/<seed>.yaml`。审核不通过则修复后重审（变异的 subagent 或直接修复，
修复后必须再次审核）。

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
```

- [ ] **Step 2: 校验 frontmatter 与目录**

```bash
ls .claude/skills/factor-mine/
```

Expected: `SKILL.md` 存在；目录无其他文件（Task 2/3 填充）。

- [ ] **Step 3: 提交**

```bash
git add .claude/skills/factor-mine/SKILL.md
git commit -m "feat(skill): factor-mine 主指令（8 步流程 + 规则）"
```

### Task 2: assumption-review.md 假设分析审核模板

**Files:**
- Create: `.claude/skills/factor-mine/assumption-review.md`

- [ ] **Step 1: 写模板**

```markdown
# 假设分析与审核工作模板

配 `.claude/skills/factor-mine/SKILL.md` §2/§3 使用。自由使用：不强制分类、
不要求穷尽；目标是找出**没被关注到的隐含假设**。以下问题清单是引导，不是限制。

## A. 种子因子重述

一句话：<种子> 认为 ____，通过 ____ 捕捉。

## B. 隐含假设枚举

对种子因子的每个实现选择，回答"它隐含相信什么？"：

- **窗口/参数**：为什么这个窗口长度？更长/更短会改变什么？（20 日 vs 60 日；
  500 日冷启动意味着什么）
- **数据字段**：为什么用 close 而非 vwap/open？量用什么口径？复权视图选择
  隐含了什么？
- **权重/聚合**：等权 vs 加权？横截面 rank 还是原始值？相乘/相加的结构选择？
- **股票同质性**：对所有股票一视同仁吗？有没有隐含"反转在低换手/大盘/高流动
  样本同样成立"？
- **时间**：周频调仓？5 日持有期？这些隐含了什么市场微观结构？
- **处理链**：winsorize/standardize 之前之后信号语义怎么变？缺失怎么处理？
- **符号/方向**：direction 隐含了什么？负号背后是什么关系？
- **市场结构**：它相信市场存在什么可重复的结构（反转持续、量能延续……）？

## C. 每条假设的判定

| 假设 | 类型（成立/可疑/证伪/可精确化） | 证据（档案数据/平台事实/知识） | 精确化方向 |
|------|--------------------------------|-------------------------------|-----------|
|      |                                |                               |           |

## D. 语义矛盾检查

- 假设之间互斥吗？
- 与平台语义冲突吗：TS/CS 分区正确？无未来函数？direction 语义？
- 精确化后假设集合内部自洽吗？

## E. 数据可实现检查

- 字段在平台库存在（`docs/interface.md` 字段表 / information_schema 核对）？
- 窗口长度 < 可用历史（数据自 2000-01-04）？
- 缺失率预估（对照种子 signal_null_ratio）可接受？

## F. 变异设计

- **保留**：____（这些假设证据充分，不动）
- **精确化/变异**（可多个）：假设 X → 变异为 X'：____，理由：____
- **变异后假设集合一致性**：重新过 D 检查
- **新因子名**：`<seed>_<variant>`
- **预期**：若 X' 成立，结果应比种子 ____（更显著/更稳定/覆盖更广……）
```

- [ ] **Step 2: 提交**

```bash
git add .claude/skills/factor-mine/assumption-review.md
git commit -m "feat(skill): factor-mine 假设分析审核模板"
```

### Task 3: code-review.md subagent 审核提示词

**Files:**
- Create: `.claude/skills/factor-mine/code-review.md`

- [ ] **Step 1: 写提示词**

```markdown
# 挖因子代码审核（subagent 提示词）

你是 FactorLab 平台的独立代码审核员。审核新因子的实现是否与其变异设计语义对齐。

## 输入材料（由调度者提供）

1. 变异点记录：种子因子 <seed>、变异假设清单（保留/精确化/变异）、新因子名 <name>。
2. 新因子实现：`factor/<name>.yaml` 全文。
3. 种子因子实现：`factor/<seed>.yaml` 全文（对照物）。
4. 平台事实：数据字段（docs/interface.md §数据字段）、DSL 语义与防未来（§DSL 语义）、
   评估方向语义（direction）。

## 检查清单

1. **语义↔代码对齐**：变异点记录里的每条变异语义都能对应到公式的某行/某段；
   找不到对应的变异 → 缺失实现；有公式行为但变异记录没提 → 多余改动。
2. **变异点之外一致**：与种子因子逐行对比，非变异部分逻辑应一致
   （窗口、处理链、universe、date 可合理微调但须注明）。
3. **防未来**：无未来函数（ts_delay 负数、shift(-) 等只用于合法前向目标）；
   TS 算子按 asset 分区、只用历史窗口。
4. **分区正确**：TS/CS 算子前缀与语义匹配（wq.ts_* 时序、CS 横截面）。
5. **方向语义**：direction 与变异后假设一致（信号高 ↔ 预期收益方向）。
6. **平台规范**：name 合法（`^[A-Za-z_][A-Za-z0-9_]{0,63}$`）、字段必填齐全、
   自由代码公式语法（def/params）符合 docs/interface.md。

## 输出格式

```
结论: 通过 / 不通过
问题清单（不通过时）:
- [严重|一般] <问题> <位置> <为什么>
修复建议: ...
```

严重问题（语义错位/防未来/分区错误）必须修复后才可运行；一般问题（命名/规范）
记录并修复。审核不通过 → 调度者修复 → 重新审核 → 通过后才能跑结果。
```

- [ ] **Step 2: 提交**

```bash
git add .claude/skills/factor-mine/code-review.md
git commit -m "feat(skill): factor-mine 代码审核提示词"
```

### Task 4: 文档同步

**Files:**
- Modify: `docs/factor-mining-playbook.md`（§7 因子入库与管理 末尾追加一节）

- [ ] **Step 1: 追加挖因子 skill 说明**

在 `docs/factor-mining-playbook.md` §7"因子档案（md）"小节之后（"## 8. 数据刷新提醒"之前）插入：

```markdown
**挖因子循环（skill）**：`/factor-mine [N]` 自动挖掘——随机选种子因子 →
分析其隐含假设 → 审核（语义/数据可实现）→ 在种子假设集合上变异/精确化 →
实现新因子 → subagent 审核代码 → 跑结果 → 按本文档阈值判定 → 按档案模板入库
（含负结果），连续 N 轮。流程与规则见 `.claude/skills/factor-mine/SKILL.md`。
```

- [ ] **Step 2: 提交**

```bash
git add docs/factor-mining-playbook.md
git commit -m "docs: playbook 增加挖因子 skill 说明"
```

### Task 5: 端到端演练一轮（验收）

主 agent（调度者）直接执行，不走 subagent 实现——验证 skill 指令本身可用。
执行 `/factor-mine 1` 的完整一轮：

- [ ] **Step 1: 种子选择**（命令见 SKILL.md §1），随机选一个种子因子。
- [ ] **Step 2-4: 假设分析/审核/变异设计**——按 assumption-review.md 产出
      变异点记录（保留/精确化/变异 + 理由 + 一致性检查）。
- [ ] **Step 5: 实现**——写 `factor/<name>.yaml` + 语义↔代码映射。
- [ ] **Step 6: subagent 代码审核**——按 code-review.md dispatch；不通过则修复重审。
- [ ] **Step 7: 运行**——`factorlab run factor/<name>.yaml` 成功，记录 summary 指标。
- [ ] **Step 8: 入库**——写 `docs/factors/<name>.md`（模板）、种子档案迭代历史加行、
      互链、git 提交。

**验收标准**：
- 8 步全部走通，产出：新因子 yaml + 档案 + 种子档案更新 + 提交。
- 演练中发现的 SKILL.md/模板缺口当场修订并提交（skill 是迭代物）。
- 平台测试不因演练而破坏（演练只加因子文件/文档；如动了平台代码则全量
  `python -m pytest -q` 必须通过——预期不需要）。
- 演练完成向用户汇报：种子、变异点、结果指标、判定、档案链接。
