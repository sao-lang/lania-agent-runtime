# 安全设计方案（v0.1）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的
> **工具执行链**（before_tool / after_tool）与 **护栏治理**。
>
> 关联文档：
> - [`governance-component-design.md`](governance-component-design.md) — 审批 / 权限 / 脱敏护栏
> - [`gateway-design.md`](gateway-design.md) — 请求边界鉴权 / 限流
> - [`observability-design.md`](observability-design.md) — 日志 / 追踪脱敏

## 0. 背景与目标

当前安全能力是零散的：密钥走环境变量、工具参数走 pydantic 校验、
输出脱敏在护栏规划中，但没有体系化的安全设计。

本文档定义**安全设计方案**，覆盖：密钥管理、Prompt 注入防护、工具与 MCP 沙箱、
供应链安全、审计合规。目标不是"绝对安全"，而是**默认安全的基线 + 可替换加固点**。

## 1. 现状盘点

| 项 | 状态 |
|----|------|
| 密钥来源（环境变量 `OPENAI_API_KEY` 等） | ✅ 已实现 |
| 工具参数校验（pydantic） | ✅ 已实现 |
| 工具审批 / 权限（护栏 approval / permission） | 🚧 设计中 |
| 输出脱敏（护栏 redact） | 🚧 设计中 |
| 日志 / 追踪脱敏 | ❌ 缺失 |
| Prompt 注入防护 | ❌ 缺失 |
| MCP 沙箱边界 | ❌ 缺失 |

## 2. 设计原则

### R1 默认安全（secure by default）

- 密钥默认不落日志、不进快照、不进审计事件；
- 工具默认最小权限：未显式授权的高危工具不执行（permission 白名单优先）。

### R2 分层防御

```text
输入层：网关鉴权 → 请求校验 → Prompt 注入分类（护栏）
执行层：工具权限 / 审批 → 参数校验 → MCP 沙箱
输出层：脱敏 → 审计（脱敏后落库）
```

### R3 可替换加固点

每个安全点提供协议（如 `InputClassifier` / `SecretProvider`），
默认实现满足基线，生产可替换为更强实现（如企业 WAF / KMS）。

## 3. 方案

### 3.1 密钥管理

- 来源分级：环境变量 → secret 文件 → 外部 SecretProvider（协议）；
- 校验：`LLMExecutorConfig` 构造时校验密钥格式与来源；
- 红线：密钥**永不**出现在日志 / 追踪 / 审计 / wm 快照中
  （观测与审计做字段白名单 + 关键字拦截）。

### 3.2 Prompt 注入防护

- 输入分类：`InputClassifier` 协议，内置启发式（危险指令特征 / 系统提示词边界）；
- 护栏联动：命中高风险输入 → approval / block（复用 governance Intercept 语义）；
- 输出隔离：Agent 输出与系统指令分通道，防止越权指令被当作工具参数执行。

### 3.3 工具与 MCP 沙箱

- 工具权限：permission 白名单 + approval 人工审批（governance 已设计）；
- MCP：服务器白名单 + 工具级权限 + 超时 / 资源上限；
- 高危操作（删除 / 转账 / 外发）默认进审批名单。

### 3.4 供应链安全

- 依赖锁定：`uv.lock`（已有），CI 校验 lock 与 pyproject 一致；
- 依赖评审：新增依赖走评审流程；发布前 `uv audit`（若可用）；
- 发布签名：PyPI 发布走官方流程 + 版本 tag 签名（可选）。

### 3.5 审计合规

- 审计事件脱敏后落库（与护栏 AuditSink 联动）；
- 关键操作（审批通过 / 工具高危调用 / 数据外发）标记 `critical` 事件；
- 保留策略：审计 TTL 与导出（宿主配置）。

## 4. 实施顺序

| 步 | 内容 | 验收 |
|----|------|------|
| 1 | 密钥红线：日志 / 追踪 / 审计 / 快照字段白名单 + 关键字拦截 | 泄漏拦截单测 |
| 2 | InputClassifier + 护栏联动 | 高风险输入分类与阻断测试 |
| 3 | MCP 沙箱边界（白名单 / 超时 / 资源上限） | 越权调用阻断测试 |
| 4 | 审计脱敏与 critical 标记 | 脱敏落库测试 |
| 5 | 供应链：CI lock 校验 + 依赖评审清单 | CI 通过 |

每步完成即：全量测试通过、覆盖率 ≥96%、ruff 零报错、文档同步。

## 5. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 脱敏误伤业务数据 | 规则可配置 + 脱敏前后对照（仅审计场景） |
| Prompt 注入误报 | 分类器可替换 + 阈值可调 |
| MCP 服务器恶意行为 | 白名单 + 工具权限 + 资源上限 |
| 密钥在第三方 provider 日志 | 走 SecretProvider 注入，不在配置明文 |

## 6. 待确认决策

| 编号 | 决策 | 推荐 |
|------|------|------|
| D1 | 密钥/SecretProvider 位置 | `src/security/`（推荐）vs 并入 lifecycle |
| D2 | Prompt 注入分类器默认实现 | 启发式规则（推荐）vs 接入 LLM 分类 |
| D3 | 供应链审计工具 | `uv audit`（推荐，若可用）vs 手动清单 |

## 附录 A：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/security/*` | 新增 | SecretProvider / InputClassifier / 脱敏联动 |
| `src/observability/*` | 修改 | 日志 / 追踪字段白名单 |
| `src/tools/_mcp/*` | 修改 | 沙箱边界 |
| `tests/test_security_*.py` | 新增 | 各安全点测试 |

## 附录 B：修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-08-17 | 初稿 |