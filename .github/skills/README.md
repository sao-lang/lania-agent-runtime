# Copilot 指令

## Skill 加载要求

### 1. `ai-coding-rules` — 开发任务必载

进行**任何开发任务**（编码、重构、修复、测试、文档、调试、代码提交等）时，**必须优先加载 `ai-coding-rules` skill**：

> `.github/skills/ai-coding-rules/SKILL.md`

该 skill 会根据任务类型自动选择对应的规则文件（如 Python 规则、TypeScript 规则、重构规则等），确保行为与项目约定一致。

> **调试任务**：加载 `ai-coding-rules` 的同时，**必须额外加载 `debug-tools` skill**（见下文第 3 条）。`ai-coding-rules` 提供编码约束，`debug-principles` skill 提供通用调试原则，`debug-tools` 提供标准化脚本和语言专项调试流程。

### 2. `grill-me` — 拷问与自省

> `.github/skills/grill-me/SKILL.md`

**始终加载 `grill-me` skill**，保持就绪状态。两种激活方式：

| 模式 | 触发词 |
|------|--------|
| **拷问用户** | "拷问我"、"grill me"、"拷打"、"盘问"、"面试我"、"考考我"、"challenge me"、"interrogate" |
| **自省**（主动/自动） | "自省"、"self-review"、"拷问自己"（主动）；复杂任务完成后自动触发 |

### 3. `code-review` — 代码审查

> `.github/skills/code-review/SKILL.md`

用户要求**代码审查、评审、审计**时加载。自动加载 `ai-coding-rules` 的对应规则文件作为审查标准。

### 4. `simplify` — 代码简化

> `.github/skills/simplify/SKILL.md`

用户要求**简化代码、去重、降低复杂度**时加载。自动加载 `ai-coding-rules/rules/06-refactor.instructions.md` 确保行为不变原则。

## 文档约束

设计文档一般都在`docs`中，开发记录在`overview.md`，自省修改记录在`grill-self-review.md`。