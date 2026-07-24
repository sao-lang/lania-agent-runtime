---
name: ai-coding-rules
description: 'Use when: coding, refactoring, fixing bugs, testing, documenting, debugging, code review, code commit, or any file modification. Loads task-specific rule files (rules/*.instructions.md) to enforce project conventions. 使用场景：编码、重构、修复、测试、文档、调试、代码提交等开发任务。'
user-invocable: true
---

# AI 编码规则

> **AI Summary**: 所有开发任务的入口 skill。先读设计文档提取 checklist → 用户确认 → 逐项实现 → 运行验证可用性 → 回溯设计文档核对。自动按语言加载对应规则文件。

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
- 根据任务类型加载对应的规则文件（参考上方"何时加载什么规则文件"）
- 始终加载 `rules/00-base.instructions.md`
- 如果是重构/Git/文档/调试任务，对应加载 `rules/06-refactor.instructions.md` / `rules/02-commit.instructions.md` / `rules/04-doc.instructions.md` / `rules/16-debug-principles.instructions.md`
- 如果是调试任务，额外加载 `debug-tools/SKILL.md`

### 第三步：解析设计文档 → 输出方案（R8）
- **设计文档路径**：项目设计文档统一放在 `docs/design/*.md`；如设计文档中有"关联文档/主文档"引用，**必须顺着引用链阅读所有相关文档**，确保全局理解
- 从设计文档中**逐条提取功能点生成 checklist**：类/方法/字段/数据流/文件清单/编码要求/测试要求
- 方案包含：修改目标、**checklist（逐项列出待实现功能，格式见下）**、涉及文件、变更要点、**潜在影响**（向后兼容性、API 变更、数据库迁移、配置变更等）
- **checklist 需用户确认后方可进入实现**

方案输出格式示例：
```
## 修改方案

### 修改目标
实现 Tool/MCP/Skill 三种原语集成方案

### 功能清单
- [ ] ToolSpec 类（§3.2）：name/description/parameters/handler + to_openai_schema
- [ ] ToolRegistry 类（§3.3）：register/describe/execute
- [ ] MCPToolAdapter 类（§4.4）：tool_spec + _execute
- [ ] ...

### 涉及文件
- `src/tools/_spec.py` — ToolSpec 定义
- `src/tools/_registry.py` — 注册中心

### 变更要点
- 新增 tools 包，创建 3 个核心类
- 修改 runtime.py 集成 ToolDispatcher

### 潜在影响
- 向后兼容：旧 tool_executor 接口保留
- API 变更：无
- 配置变更：无
```

### 第四步：逐项对照实现
- **严格对照 checklist 实现**，每完成一项标记 `[x]`，不得跳过或合并
- 设计文档不清晰处**立即询问用户**，不自行猜测
- 文件清单必须严格匹配，数量/结构不符时报告用户
- **实现中发现遗漏**：如果在实现过程中发现设计文档中某功能点未被提取到 checklist 中：
  - 如果是**原子级遗漏**（如一个字段、一个方法参数）→ 自行补充实现，在 checklist 中追加并注明"实现中发现，已补充"
  - 如果是**模块级遗漏**（如整个类、整个文件）→ **停下来询问用户**，确认是否需要纳入当前实现

### 第五步：代码验证 + 设计文档回溯 + 功能可用性验证 + 真实环境验证（R10 + R10a）
- 修改完成后运行 lint 和类型检查，检查出错立即修复
- **回溯验证**：对照设计文档输出"设计文档 vs 实现"对照表（含章节号、状态、文件），**未实现项先补充再继续**
- **变更范围一致性检查**：确认新增/修改的所有文件是否在设计文档的文件清单预期范围内；如超出范围，需在对照表中说明原因
- **功能可用性验证**：
  - 从 `README.md`、`pyproject.toml`、`package.json` 等文件中找到项目的启动/运行方式
  - **实际运行项目**（或运行新增功能的独立 demo 脚本），确认功能能正常启动和调用
  - 如新增的是 API/工具函数，编写快速调用脚本验证输入输出符合预期
  - 验证通过后报告"✅ 功能可用"；验证失败则修复后重新验证
- **真实环境验证（R10a）**：项目涉及外部服务时，必须额外运行 Smoke Test 和 E2E 测试，按 `03-testing.instructions.md` 的验证报告模板输出结构化结果

### 第六步：**二次检查**
- **再次询问**：所有功能都做完了吗？所有的功能之间是联通的吗？和其他模块是联通的吗？
  如果有问题，重新列清单，用户确认后重新修改代码，直到没有问题

### 第七步：记录与提交
- **README 同步**：按 R9b 检查是否需要同步更新 `README.md` 和 `docs/` 下的相关设计文档
- **追加记录**：按 R9a 要求追加一条记录到 `overview.md`（时间倒序）。注意：多次迭代修改（如修复 → 验证失败 → 再修复）只在**最终完成时追加一条**，不逐次追加
- **提交信息**：按 `commit-rules` skill 执行提交。提交信息格式概要：`<type>: <简短描述>`（如 `feat: 实现 ToolDispatcher 统一调度`、`fix: 修复 MCP 连接超时问题`、`refactor: 重构 StepRunner 接口`）

