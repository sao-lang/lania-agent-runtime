# Copilot 指令

## Skill 加载要求

### 1. `ai-coding-rules` — 开发任务必载

进行**任何开发任务**（编码、重构、修复、测试、文档、调试、代码提交等）时，**必须优先加载 `ai-coding-rules` skill**：

> `.github/skills/ai-coding-rules/SKILL.md`

该 skill 会根据任务类型自动选择对应的规则文件（如 Python 规则、TypeScript 规则、重构规则等），确保行为与项目约定一致。

> **调试任务**：加载 `ai-coding-rules` 的同时，**必须额外加载 `debug-tools` skill**（见下文第 3 条）。`ai-coding-rules` 提供编码约束，`debug-principles` skill 提供通用调试原则，`debug-tools` 提供标准化脚本和语言专项调试流程。

### 2. `grill-me` — 拷问模式必载

**始终加载 `grill-me` skill**，保持就绪状态。当用户说出"拷问我"、"grill me"、"盘问"、"面试我"、"考考我"、"challenge me"、"interrogate"等触发词时，立即激活 Socratic 拷问者人格：

> `.github/skills/grill-me/SKILL.md`

#### 复杂任务后自动自省

完成**复杂任务**（修改 ≥3 文件、涉及架构设计/系统决策/安全策略/API 设计/多步骤推理链等）后，**必须自动触发 `grill-me` 的模式三（任务后自动自省）**：

1. 完成用户需求的实现
2. 按 grill-me 的复杂任务判定标准判断当前任务是否触发自省
3. 如果触发，按四大维度逐项检查：
   - **功能完整性** — 所有功能点都完成了吗？
   - **功能间联通** — 功能之间数据流/调用链通了吗？
   - **模块间联通** — 新模块与现有模块接口兼容吗？
   - **可用性** — 能实际运行吗？有严重 bug 吗？
4. 输出精简自省报告
5. 发现严重问题（功能遗漏/联通断点/运行时错误/安全漏洞/破坏现有功能）时，**不等用户指示，主动修复**，修复后二次自省
6. 按照 `ai-coding-rules` 这个skill的规则来修复，确保修复后的代码符合项目约定

> 简单任务（typo、重命名、纯问答）不触发自省。

## 文档约束

设计文档一般都在`docs`中，开发记录在`overview.md`，自省修改记录在`grill-self-review.md`。