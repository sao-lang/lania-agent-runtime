---
name: debug-tools
description: '通用的调试工具 skill，提供标准化的脚本工具、调试规则和排查流程，适用于前端/后端/全栈项目的运行时与静态分析调试。Triggers: "调试", "debug", "bug", "排查", "异常", "报错", "error", "crash", "性能问题", "测试失败", "构建失败". 与 ai-coding-rules 搭配使用。'
---

# Debug Tools

> **AI Summary**: 调试入口 skill。静态分析优先→运行时兜底。按语言加载对应调试规则，提供标准化脚本和七步调试流程。

## 作用

当需要进行 **问题排查、Bug 定位、性能分析、异常诊断** 时，使用本 skill。它提供一套标准化的调试工具（脚本命令）、调试规则和排查流程，确保调试行为高效、可复现、不引入新问题。

## 何时使用

适用于以下场景：

- 运行时异常 / 崩溃排查
- 渲染问题 / UI 异常
- 网络请求 / API 调用异常
- 状态管理 / 数据流问题
- 类型错误 / 编译错误
- 性能问题（卡顿、重渲染过多、内存泄漏）
- 异步时序 / 竞态条件
- 构建 / 打包问题
- 测试失败分析

## 何时加载什么规则文件

执行调试任务前，按需加载对应的规则文件：

| 任务类型               | 加载文件                                                              |
| ---------------------- | --------------------------------------------------------------------- |
| 需要运行调试脚本/命令  | `rules/00-scripts.instructions.md`                                    |
| 需要调试规范与禁止事项 | `rules/01-rules.instructions.md`                                      |
| TypeScript/TSX 调试    | `rules/02-ts-debug.instructions.md`                                   |
| Dart/Flutter 调试      | `rules/03-dart-debug.instructions.md`                                 |
| Rust 调试              | `rules/04-rust-debug.instructions.md`                                 |
| Go 调试                | `rules/05-go-debug.instructions.md`                                   |
| Python 调试            | `rules/06-python-debug.instructions.md`                               |
| React 组件调试         | `rules/00-scripts.instructions.md` + `rules/01-rules.instructions.md` |
| 构建/打包调试          | 优先加载 `rules/00-scripts.instructions.md`                           |

## 使用原则

1. **静态分析优先**：先阅读源码、追踪数据流、分析类型，再使用运行时工具验证
2. **脚本工具辅助**：使用标准化脚本快速收集证据，避免手工重复操作
3. **规则约束兜底**：遵守调试规则，不盲改、不掩盖、不留调试代码
4. **根因修复**：定位根本原因而非表面症状，修复后补充测试用例

## 与其他 skill 的关系

- `ai-coding-rules`：通用编码约束始终适用
- `debug-principles` skill（`../debug-principles/SKILL.md`）：通用调试原则（5 步流程/日志规范/禁止事项），与本 skill 互补
- 当调试涉及测试时，同时加载 `ai-coding-rules/rules/03-testing.instructions.md`
- `grill-me`（模式三：任务后自动自省）：调试修复完成后，自动触发自省（功能完整性/联通性/代码风格/可用性），确保修复不引入新问题
