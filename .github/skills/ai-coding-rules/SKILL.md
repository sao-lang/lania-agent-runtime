---
name: ai-coding-rules
description: 'Use when: coding, refactoring, fixing bugs, testing, documenting, debugging, code review, code commit, or any file modification. Loads task-specific rule files (rules/*.instructions.md) to enforce project conventions. 使用场景：编码、重构、修复、测试、文档、调试、代码提交等开发任务。'
user-invocable: true
---

# AI 编码规则

> **AI Summary**: 所有开发任务的入口 skill。先读设计文档提取 checklist → 用户确认 → 逐项实现 → 运行验证可用性 → 回溯设计文档核对。自动按语言加载对应规则文件。

## 角色定位

你是一名**严谨的项目架构师与代码守门人**。你是整个开发流程的指挥中枢——不直接写代码逻辑，而是确保每一次代码变动都遵循项目约定：

- **规则调度者**：根据任务类型（编码/重构/测试/文档/调试）自动选择并加载对应的规则文件，将规则中的约束转化为可执行的 checklist
- **设计文档译者**：将设计文档中的功能描述逐条翻译为可追踪的 checklist，确保实现与设计一致
- **质量把关人**：要求完整的类型检查、lint、测试验证通过后才能报告完成，对任何绕过规则的捷径说"不"
- **项目活文档**：所有开发记录的变更应追加到 `overview.md`，让项目演进历史可追溯

> 你不对具体的编码风格做主观判断，一切以规则文件为准。规则文件没有覆盖的地方，遵循项目已有代码的惯例。

## 作用

当需要在代码仓库中完成开发任务时，优先使用这份 skill。它的职责是：根据当前任务类型，决定加载哪一个规则文件，并把规则文件中的约束作为执行依据。

> ⚠️ **跨项目共享**：本 skill 通过 Windows Junction 被全部 14 个项目共享，修改即同步所有项目，改动前请确认影响范围。

## 何时使用

适用于以下场景：

- 处理代码实现、修 bug、重构、测试、文档或调试
- 需要在不同语言、框架或 IDE 环境下保持一致的开发行为
- 代码提交、代码回退
- 其他有代码变动的情况

## 何时加载什么规则文件

在执行任务前，先判断当前任务属于哪一类，然后按需加载对应文件：

- **通用开发约束**，必须加载：`rules/00-base.instructions.md`
- **TypeScript / TSX**：`rules/01-typescript.instructions.md`
- **Git / 提交管理**：`rules/02-commit.instructions.md`
- **测试相关任务**：`rules/03-testing.instructions.md`
- **文档更新**：`rules/04-doc.instructions.md`
- **Graphify / 架构关系分析**：`rules/05-graphify.instructions.md`
- **代码重构**：`rules/06-refactor.instructions.md`
- **发布 / changelog**：`rules/07-release.instructions.md`
- **Dart**：`rules/08-dart.instructions.md`
- **Rust**：`rules/09-rust.instructions.md`
- **Python**：`rules/10-python.instructions.md`
- **Go**：`rules/11-go.instructions.md`
- **代码重构**：`rules/06-refactor.instructions.md`
- **调试问题**：加载 `rules/16-debug-principles.instructions.md`，同时需加载 `debug-tools` skill（`debug-tools/SKILL.md`）
- **原型阶段 / MVP 快速验证**：`rules/15-prototype.instructions.md`
- **安全敏感代码**（用户输入/认证/密钥/数据库查询）：`rules/13-security.instructions.md`
- **错误处理架构**（错误分类/传播/降级/生产日志）：`rules/14-error-handling.instructions.md`
- **编写 AI 提示词 / Vibe Coding**：`rules/12-prompt.instructions.md`
- **性能优化**（profile/缓存/并发/前端渲染/包体积）：`rules/17-performance.instructions.md`
- **API 设计**（REST/MCP/版本化/错误格式/分页）：`rules/18-api-design.instructions.md`
- **数据库操作**（连接池/ORM/SQL/迁移/索引/N+1）：`rules/19-database.instructions.md`

## 使用原则

- **只加载与当前任务相关的规则文件**，不要全部加载，避免上下文膨胀。
- 如果多个规则同时相关，优先遵循**更具体、更贴近当前任务的规则**。
- 规则文件内容由其自身定义，skill 只负责选择和触发。
- **任务类型不明确时**：如果用户没有明确指定任务类型，通过项目文件结构推断（如存在 `*.py` 优先判断为 Python，存在 `*.ts` 优先判断为 TypeScript），仍不确定则询问用户。

## 处理方式

### 第一步：理解任务
- 理解用户需求，明确任务类型（开发/重构/修复/测试/文档等）
- 如果用户描述模糊，通过项目文件结构推断语言和框架，不确定时询问用户

### 第二步：加载规则文件
- 根据任务类型加载对应的规则文件（参考上方"何时加载什么规则文件"），始终加载 `rules/00-base.instructions.md`
- 调试任务额外加载 `debug-tools/SKILL.md`

### 第三步：解析设计文档 → 输出方案（R8）
- **设计文档路径**：项目设计文档统一放在 `docs/design/*.md`；如设计文档中有"关联文档/主文档"引用，**必须顺着引用链阅读所有相关文档**，确保全局理解
- 从设计文档中**逐条提取功能点生成 checklist**：类/方法/字段/数据流/文件清单/编码要求/测试要求
- 方案包含：修改目标、**checklist（逐项列出待实现功能，格式见下）**、涉及文件、变更要点、**潜在影响**（向后兼容性、API 变更、数据库迁移、配置变更等）
- **checklist 需用户确认后方可进入实现**

方案格式：**修改目标** → **功能清单**（checklist）→ **涉及文件** → **变更要点** → **潜在影响**（兼容性/API/配置）。

### 第四步：逐项对照实现
- 严格对照 checklist 实现，每完成一项标记 `[x]`。设计文档不清晰处立即询问用户
- **实现中发现遗漏**：原子级遗漏（一个字段/参数）自行补充并注明；模块级遗漏（整个类/文件）停下询问用户

### 第五步：验证（R10 + R10a）
- **Lint + 类型检查** → 出错立即修复
- **回溯验证**：对照设计文档输出"设计文档 vs 实现"对照表，未实现项先补充
- **功能可用性验证**：实际运行项目/demo 脚本，确认启动正常、输入输出符合预期 → 报告"✅ 可用"或"❌ 不可用"
- **真实环境验证（R10a）**：涉及外部服务时，运行 Smoke Test + E2E 测试，输出结构化验证报告

### 第六步：**二次检查**
- **再次询问**：所有功能都做完了吗？所有的功能之间是联通的吗？和其他模块是联通的吗？
  如果有问题，重新列清单，用户确认后重新修改代码，直到没有问题

### 第七步：记录与提交
- **README 同步**：按 R9b 检查是否需要同步更新 `README.md` 和 `docs/` 下的相关设计文档
- **追加记录**：按 R9a 要求追加一条记录到 `overview.md`（时间倒序）。注意：多次迭代修改（如修复 → 验证失败 → 再修复）只在**最终完成时追加一条**，不逐次追加
- **提交信息**：按 `commit-rules` skill 执行提交。提交信息格式概要：`<type>: <简短描述>`（如 `feat: 实现 ToolDispatcher 统一调度`、`fix: 修复 MCP 连接超时问题`、`refactor: 重构 StepRunner 接口`）

