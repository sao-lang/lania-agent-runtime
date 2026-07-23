# Copilot 指令

## Skill 加载要求

进行**任何开发任务**（编码、重构、修复、测试、文档、调试、代码提交等）时，**必须优先加载 `ai-coding-rules` skill**：

> `.github/skills/ai-coding-rules/SKILL.md`

该 skill 会根据任务类型自动选择对应的规则文件（如 Python 规则、TypeScript 规则、重构规则等），确保行为与项目约定一致。

如果要进行debug，**必须优先加载 `debug-tools` skill**：

> `.github/skills/debug-tools/SKILL.md`