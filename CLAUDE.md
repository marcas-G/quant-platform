# FactorLab 项目指南

个人因子 DSL 计算平台（`expr_codegen` + `polars_ta` 内核，Rust `quant_core` 评估，
平台自有 DuckDB 数据层）。工作流与技能约定见 `AGENTS.md`（Superpowers 框架）。

## 硬性要求

### 文档和测试必须做好、写全面（最高优先级）

任何代码改动，验收时同时检查文档与测试是否同步、全面，不满足不算完成：

**测试**：
- 所有功能遵循 TDD：先写失败测试，再写最小实现，测试转绿才提交。
- 测试必须覆盖**正常路径、边界条件、错误路径**三类场景，禁止只测 happy path。
- 测试验证真实行为（真实数据/真实计算），不用 mock 糊弄；依赖外部资源的
  集成测试用 `@pytest.mark.integration` 标记，环境缺失时 skip 而非假实现。
- 涉及数据窗口/分组/对齐语义（TS/CS/GP 分区、周频对齐、停牌补全等）必须有
  能捕获跨资产泄漏、未来函数、错位这类错误的回归测试（多资产/多日期面板）。
- 提交前运行全量测试套件并确认全部通过（`python -m pytest -q`）。

**文档**：
- 代码提交必须同步更新相应文档：新增/变更的 Python API、CLI 命令、DSL 语法
  写入 `docs/interface.md`；设计决策与里程碑写入 `docs/superpowers/specs/` 与
  `docs/superpowers/plans/`。
- 新模块、新接口必须有使用说明（签名、行为、错误语义），不允许"代码即文档"。
- 文档与实现冲突时，文档必须修订到与实现一致，并在 `docs/interface.md` 注明。
- 实现中发现的设计缺口（计划/规格与实现不符）必须记录到对应设计/计划文档。

## 环境事实

- Python 3.13；editable 安装指向当前工作树（切换分支/工作树后需
  `python -m pip install -e .` 重新指向）。
- 平台库 `data/factorlab.duckdb`（`settings.platform_db`，`FACTORLAB_PLATFORM_DB`
  可覆盖）为**唯一数据源**：因子计算只读消费；写入仅经
  `factorlab data rebuild/update/refresh`。
- `daily.code` 为纯数字（`000001`），`stock_basic_tushare.ts_code` 带后缀
  （`000001.SZ`）；`symbol` 列是两者桥梁。
- 目标机器约 16GB 内存且无页面文件：SQL-first、float32、DuckDB `memory_limit`
  等内存护栏是运行时硬约束（主 spec 6.1）。
