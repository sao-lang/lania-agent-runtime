# 公共 API 面与扩展 SDK 设计方案（v0.1）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的
> **Hook 原语**、**Plugin / PluggableComponent** 与 **Builder 接线**。
>
> 关联文档：
> - [`governance-component-design.md`](governance-component-design.md) — 组件封装范式（扩展 SDK 的直接对象）
> - [`gateway-design.md`](gateway-design.md) — 网关协议（可替换点示例）
> - [`session-component-design.md`](session-component-design.md) — 组件内部分层（config/protocols/models/hooks）

## 0. 背景与目标

当前 `src/runtime/__init__.py` 的导出就是"公共 API 面"，但缺少：
- **稳定性承诺**：哪些符号稳定、哪些实验、哪些内部，没有分级；
- **版本化策略**：`0.1.0` 无 semver 约定，无废弃流程；
- **扩展 SDK**：外部开发者写 Hook / Plugin / 协议后端 / 组件时靠读源码，
  没有规范、契约校验与脚手架。

本文档定义**公共 API 面与扩展 SDK 设计方案**，让"可插拔"对框架作者之外的人也成立。

## 1. 现状盘点

| 项 | 状态 |
|----|------|
| 公共导出（`src/runtime/__init__.py`） | ✅ 已实现（未分级） |
| 组件封装范式（config / protocols / models / hooks） | ✅ 已确立 |
| Plugin / PluggableComponent | ✅ 已实现 |
| 版本号 | ⚠️ 0.1.0，无 semver 约定 |
| 废弃机制（`@deprecated` 注释约定） | ⚠️ 仅有注释约定（memory v2 用过） |
| 扩展开发指南 / 脚手架 / 契约校验 | ❌ 缺失 |

## 2. 设计原则

### R1 API 三级分级

| 级别 | 定义 | 变更承诺 |
|------|------|---------|
| **stable** | `src.runtime` 顶层导出中成熟、被组件依赖的符号 | 仅 major 版本破坏 |
| **experimental** | 新能力（如 governance / gateway 首版） | 可小版本调整，须标注 |
| **internal** | `_` 前缀模块 / 类 / 函数 | 不承诺，随时可改 |

分级表维护在 `docs/api-surface.md`（自动生成 + 手工标注）。

### R2 版本化（semver）

- `MAJOR.MINOR.PATCH`：破坏性变更 → major；新能力（实验转稳定）→ minor；修复 → patch；
- 破坏性变更必须走废弃流程，禁止直接删除 stable 符号；
- 废弃流程：`@deprecated since X.Y` 标注 → 保留 ≥2 个 minor 版本 → 移除（记入 CHANGELOG）。

### R3 扩展四类 + 契约校验

| 扩展类型 | 写法 | 契约校验 |
|---------|------|---------|
| Hook | 实现 Observer / Transformer / Interceptor | 注册时类型检查 |
| Plugin | 继承 `Plugin`，声明 `_declare_hooks()` | 挂载时校验签名 |
| 协议后端 | 实现 `*Protocol`（runtime_checkable） | `isinstance(impl, Protocol)` 校验工具 |
| 组件 | 按组件范式建 `src/<component>/` + Builder 方法 | 结构校验（配置/协议/hooks 齐全） |

提供 `src/extensions/`（或 `src/testing` 内）契约校验工具：

```python
def assert_implements(impl: Any, protocol: type) -> None:
    """运行时校验协议实现完整性（方法存在 + 签名兼容）。"""
```

## 3. 目录结构

```text
src/extensions/
  __init__.py            # 惰性导出
  _checks.py             # assert_implements / 签名校验
  _scaffold.py           # 脚手架：生成 Hook / Plugin / 协议后端 / 组件骨架
  _docgen.py             # 从 __all__ 生成 api-surface.md
docs/api-surface.md      # 公共 API 分级表（生成 + 人工标注）
```

## 4. 公共 API 面清单（示例分段）

```text
stable（既有核心）:
  AgentRuntime / RuntimeBuilder / RunResult / StreamEvent / SessionSnapshot
  HookPoint / PrimitiveType / Observer / Transformer / Interceptor
  AllowAction / BlockAction / PauseAction
  LoopStrategy / LoopStrategyFactory / ReActLoop / PlanExecuteLoop / WorkflowLoop
  LLMExecutor / LLMExecutorConfig / LLMResponse / LLMProvider / OpenAILLMExecutor

experimental（新组件）:
  governance.* / gateway.* / observability.* / lifecycle.*

internal:
  src.runtime._* 模块 / RuntimeController / StepRunner 内部方法
```

> 目标：任何破坏 `stable` 的变更在合并前必须触发评审（`docs/api-surface.md` diff 检查）。

## 5. 脚手架（`_scaffold.py`）

```python
scaffold_hook(point: HookPoint, primitive: PrimitiveType, name: str) -> str   # 生成骨架代码
scaffold_plugin(name: str) -> str                                             # Plugin 骨架
scaffold_backend(protocol_name: str) -> str                                   # 协议实现骨架
scaffold_component(name: str) -> str                                          # 组件包骨架
```

输出可直接粘贴的骨架 + 文档注释，减少"读源码"成本。

## 6. 实施顺序

| 步 | 内容 | 验收 |
|----|------|------|
| 1 | `docs/api-surface.md` 分级表（基于现有导出） | 与 `__all__` 一致 |
| 2 | `_checks.py`：assert_implements + 签名校验 | 通过/失败用例 |
| 3 | `_scaffold.py`：四类骨架生成 | 生成物可运行/可测试 |
| 4 | `_docgen.py`：导出面自动同步 | 文档与代码 diff 一致 |
| 5 | 废弃机制标注（现有多处 @deprecated 收敛为统一格式） | 文档规范 |

每步完成即：全量测试通过、覆盖率 ≥96%、ruff 零报错、文档同步。

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 分级表与实际导出漂移 | `_docgen.py` 自动生成 + CI diff 检查 |
| 过度承诺导致演进僵化 | experimental 级别提供缓冲，stable 从严 |
| 脚手架生成低质代码 | 生成物必须通过契约校验与最小测试 |

## 8. 待确认决策

| 编号 | 决策 | 推荐 |
|------|------|------|
| D1 | 契约校验工具位置 | `src/extensions/`（推荐）vs 并入测试目录 |
| D2 | 脚手架形态 | 代码生成函数（推荐，零依赖）vs CLI（click） |
| D3 | 分级规则起始版本 | 自 0.2.0 起严格执行（推荐） |

## 附录 A：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/extensions/*` | 新增 | 校验 / 脚手架 / 文档生成 |
| `docs/api-surface.md` | 新增 | API 分级表 |
| `tests/test_extensions_*.py` | 新增 | 校验与脚手架测试 |

## 附录 B：修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-08-17 | 初稿 |