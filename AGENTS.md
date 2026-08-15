# Superpowers 工作流

本目录使用 Superpowers 技能框架进行软件开发。技能位于 `.agents/skills/`，由 Codex 自动发现。

## 核心规则

- 任何行动之前，先检查是否有技能适用；只要有 1% 可能适用就必须调用对应技能。
- 优先级：用户指令 > 技能 > 默认行为。

## 标准工作流

1. `brainstorming` — 写代码前先厘清需求、探索方案、分块确认设计。
2. `writing-plans` — 把设计拆成 2-5 分钟可完成的小任务。
3. `test-driven-development` — 红-绿-重构，先写失败测试。
4. `executing-plans` / `subagent-driven-development` — 逐任务执行。
5. `requesting-code-review` — 任务之间做审查。
6. `finishing-a-development-branch` — 收尾、合并、清理。

## 调试与验证

- 修复 bug 用 `systematic-debugging`（四阶段根因分析）。
- 完成前用 `verification-before-completion` 确认问题真的解决。
