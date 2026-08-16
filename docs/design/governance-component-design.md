# 护栏（治理）组件封装方案

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的
> **Hook 治理体系**（12 挂载点 × 5 种原语）、**RuntimeContext 受限 writer**（§4）
> 与 **Builder 唯一接线点**。
>
> 关联文档：
> - [`session-component-design.md`](session-component-design.md) — 组件封装范式参照（config / protocols / models / hooks / Builder）
> - [`memory-system-design.md`](memory-system-design.md) — 协议解耦与按层注入模式参照
> - [`orchestration-components-design.md`](orchestration-components-design.md) — 编排组件（Critique 等）现状
> - [`loop-strategy-design.md`](loop-strategy-design.md) — LoopStrategy 与治理 Hook 的协作

## 0. 背景与目标

本框架以"治理为核心"：Runtime 是纯壳，所有治理逻辑通过 Hook 插拔。
当前治理能力分散在 `src/runtime/hooks/`（审批 / Critique / Replan），
未按组件范式封装，且预算强制、审计、限流、脱敏/权限等能力缺失。

本文档定义**护栏（治理）组件的封装方案**：

- **目标 1（全治理）**：补齐预算强制 / 审计 / 限流 / Critique 真实现 / 脱敏与权限 / 错误治理；
- **目标 2（可插拔）**：每个治理能力按 session / memory / context 的组件范式封装，
  支持协议后端替换、热插拔（enable / disable / replace）、配置驱动；
- **目标 3（逐个落地）**：按能力分子组件，逐个封装、逐个验收，互不阻塞。

**非目标**：
- 接入层网关（HTTP / SSE 服务）不在本文档范围，另行设计；
- 编排高级模式（AgentTool / 多 Agent / CritiqueInterceptor）维持"暂缓 / 按需"状态。

## 1. 现状盘点

| 项 | 状态 |
|----|------|
| 治理机制（12 挂载点 × 5 原语） | ✅ 已实现 |
| HookRegistry 热插拔（enable / disable / replace / remove） | ✅ 已实现 |
| Plugin / PluggableComponent | ✅ 已实现（`runtime.use()` 异步挂载） |
| Builder 唯一接线点 | ✅ 已实现 |
| 审批（ApprovalPolicy + HumanApprovalInterceptor） | ⚠️ 已实现但未组件化（位于 `runtime/hooks`） |
| Critique（Self / Dual） | ⚠️ 占位（仅记录元信息，未真正调用审查模型） |
| Replan | ✅ 完成（通用 ReplanHook + PlanExecuteLoop 内置） |
| 预算 | ⚠️ 只记账不强制（token / step / cost 上限无执行者） |
| 审计 / 限流 / 脱敏 / 权限 / 错误治理 | ❌ 缺失 |

## 2. 设计原则

### R1 Runtime 纯壳

`AgentRuntime` 不感知任何治理组件；唯一接线点是 `RuntimeBuilder`。

### R2 依赖单向 + 零耦合

`src/governance` 只依赖 `src.runtime` 的类型与协议
（HookPoint / PrimitiveType / RuntimeContext / LLMResponse / HookRegistry），
**禁止** import `session / memory / context` 的实现；
需要外部能力一律走协议注入（沿用 `MemoryRecallProtocol` 的解耦模式）。

### R3 协议化后端

每个能力对外暴露一个协议，内置默认实现，用户可替换：

| 协议 | 职责 | 默认实现 |
|------|------|---------|
| `ApprovalPolicy` | 判断工具调用是否需要审批（既有契约：`needs_approval(ctx, tool_name, arguments) -> tuple[bool, str]`） | ToolNamePolicy / BudgetThresholdPolicy / RegexContentPolicy / CompoundPolicy |
| `AuditSink` | 审计事件落库 | 内置异步缓冲落库（可替换为 PG / 对象存储等） |
| `RateLimiter` | 单位窗口内请求计数与放行 | 滑动窗口内存实现 |
| `RedactPolicy` | 输出脱敏规则 | 正则 / 字段规则实现 |
| `BudgetLimits` | 预算上限来源（token / step / cost） | 静态配置实现 |

### R4 优先级契约

治理组件的执行顺序由 `_constants.py` 统一维护（见 §5.1），
写入文档作为契约，避免限流 / 预算 / 审批 / 脱敏组合时互相干扰。

### R5 状态与并发约束

- `ctx.services` 是浅拷贝，**不可写共享状态**（v2 已确立）；
- 有状态治理（限流计数、Critique 重试、审计缓冲）放在 **Hook 实例内部**，
  按 `session_id` 索引，`SESSION_END` 清理（沿用 ReplanHook 先例）；
- 审计等重 IO 使用异步缓冲 + 后台任务，不阻塞主流程（`_background.py`）。

### R6 兼容优先

现有 `src/runtime/hooks/_approval_hook.py` / `_critique_hook.py` / `_replan_hook.py`
及 `src/runtime/__init__.py` 的导出**保持可用**：
逻辑迁入 governance 后，旧模块改为重导出 shim。

## 3. 组件封装范式（对照 session）

护栏是一个组件域：`src/governance/` 包内部按能力分子组件，
每个子组件复用 session 组件的范式：

| session 组件 | 护栏子组件（每个能力） | 职责 |
|-------------|----------------------|------|
| `_config.py` | `_config.py` | 该能力的配置 dataclass |
| `_protocols.py` | `_protocols.py` | 可替换后端协议 |
| `_models.py` | `_models.py` | 数据类（审计事件 / 限流窗口 / 审批上下文） |
| `_hooks/` | `_hooks.py` | 挂载点 handler，**只依赖协议** |
| `__init__.py` | `__init__.py` | 惰性导出（`__getattr__`） |
| Builder `.session()` | Builder `.governance(approval=..., budget=...)` | 唯一接线点，注册并返回 handler_id |

无持久化需求的能力（approval / critique / redact / ratelimit）不需要
`_store / _service`；audit 落库走 `AuditSink` 协议，同样不内建 store。

## 4. 目录结构

```text
src/governance/
  __init__.py            # 惰性导出：GovernanceConfig + 各能力
  _config.py             # GovernanceConfig（enabled + 各能力配置引用）
  _constants.py          # 治理优先级段位表（唯一契约来源）
  _events.py             # GovernanceEvent 审计事件 schema
  _background.py         # 异步任务组（审计缓冲用）
  approval/
    _config.py           # ApprovalConfig
    _protocols.py        # ApprovalPolicy（迁自 runtime/hooks/_approval_hook.py）
    _models.py           # ApprovalRequest / ApprovalContext（可选）
    _hooks.py            # HumanApprovalInterceptor（迁入 + 配置化）
    __init__.py
  budget/                # 同构
  audit/                 # 同构
  ratelimit/             # 同构
  critique/              # 同构
  redact/                # 同构
  permission/            # 同构
```

## 5. 公共底座

### 5.1 优先级段位表（`_constants.py`）

| 挂载点 | 优先级 | 原语 | 能力 |
|--------|--------|------|------|
| BEFORE_LLM | 100 | Intercept | ratelimit（先限流，成本最低） |
| BEFORE_LLM | 110 | Intercept | budget（token / step 强制） |
| BEFORE_TOOL | 100 | Intercept | approval（人工审批） |
| BEFORE_TOOL | 110 | Intercept | permission（工具权限） |
| AFTER_LLM | 100 | Transform | redact（输出脱敏，最早改） |
| AFTER_LLM | 200 | Transform | critique（自批评 / 双模型修正） |
| AFTER_LLM | 210 | Intercept | critique_block（安全拦截，可选） |
| AFTER_LLM | 999 | Transform | 默认预算记账（已有，保持最后） |
| 各点 | — | Observer | audit（Observer 并发执行，天然适配） |

> 原语链语义（现状）：Transform 按优先级顺序链式执行；
> Intercept 按优先级执行并返回第一个 Block / Pause；
> Observer 并发执行。治理组件必须按此语义选择挂载点与原语。

### 5.2 审计事件（`_events.py`）

```python
@dataclass
class GovernanceEvent:
    """统一审计事件。"""

    point: str                    # 挂载点名称（"session_start" / "after_llm" / ...）
    type: str                     # 事件类型（request / approval / ratelimit / budget / critique / tool / error / session）
    session_id: str
    step_index: int
    timestamp: datetime
    data: dict[str, Any]          # 结构化载荷（含网关注入的 client_ip / route / user）
```

审计为**单一出口**：网关只把请求元数据写入 `ctx.services`（只读注入），
由 AuditPlugin 统一采集并交给 `AuditSink`，避免双写。

### 5.3 异步任务组（`_background.py`）

审计 / 异步落库的后台任务组，语义与 memory 侧一致（等待排空 + 超时取消）。
实现位置见决策 D3。

### 5.4 GovernanceConfig（`_config.py`）

```python
@dataclass
class GovernanceConfig:
    """护栏总配置——各能力可独立开关。"""

    enabled: bool = True
    approval: ApprovalConfig | None = None
    budget: BudgetConfig | None = None
    audit: AuditConfig | None = None
    ratelimit: RateLimitConfig | None = None
    critique: CritiqueConfig | None = None
    redact: RedactConfig | None = None
    permission: PermissionConfig | None = None
```

## 6. 各子组件规格

### 6.1 approval（第一个封装，已有基础）

- **定位**：Human-in-the-loop 审批，注册到 before_tool。
- **协议**：`ApprovalPolicy`（既有契约不变）。
- **配置**：`ApprovalConfig(enabled=True, mode="sync_blocking", policies=[...], approval_id_prefix="approval_")`。
- **挂载**：BEFORE_TOOL / Intercept / priority=100。
- **行为**：策略判定需要审批 → 返回 `PauseAction(approval_id, context)`；
  `mark_approved()` 保持 resume 防死循环语义。
- **状态**：`_approved_ids`（Hook 实例内，按审批 ID）。
- **测试**：策略各实现、拦截器三种模式、mark_approved、Builder 接线、旧 import 兼容。

### 6.2 budget（新增强制）

- **定位**：执行期预算强制（token / step / cost 上限）。
- **协议**：`BudgetLimits`。
- **配置**：`BudgetConfig(token_limit=0, step_limit=0, cost_limit_cents=0, block_on_exceed=True)`。
- **挂载**：BEFORE_LLM / Intercept / priority=110。
- **行为**：`ctx.budget` 超限 → `BlockAction(reason)`（或降级模式，可配置）；
  记账沿用现有 after_llm 默认 Transform（priority=999，不重复实现）。
- **前置依赖**：cost 维度需要 `LLMUsage` 补 `cost` 字段（决策 D4）。

### 6.3 audit（新增）

- **定位**：全链路审计采集与落库。
- **协议**：`AuditSink`。
- **配置**：`AuditConfig(sink=None, include_points=[...], batch_size=..., flush_interval_ms=...)`。
- **挂载**：SESSION_START/END、BEFORE_LLM、AFTER_LLM、BEFORE_TOOL、AFTER_TOOL、ON_ERROR → Observer（并发执行）。
- **行为**：各点事件标准化为 `GovernanceEvent`，异步缓冲批量写 `AuditSink`。
- **状态**：缓冲队列 + 后台任务（`_background.py`），`SESSION_END` 触发 flush。

### 6.4 ratelimit（新增）

- **定位**：会话内限流（与网关的请求级限流分工：本组件管会话内调用频率）。
- **协议**：`RateLimiter`。
- **配置**：`RateLimitConfig(limit=0, window_seconds=60)`。
- **挂载**：BEFORE_LLM / Intercept / priority=100。
- **状态**：按 `session_id` 的滑动窗口计数，`SESSION_END` 清理。

### 6.5 critique（真实现）

- **定位**：LLM 输出质量审查（自我批评 / 双模型修正 / 安全拦截）。
- **挂载**：AFTER_LLM / Transform / priority=200（Self / Dual）；AFTER_LLM / Intercept / priority=210（Block）。
- **行为**：
  - SelfCritique：同一 executor 审查，不合格重试（`max_retries` 上限）；
  - DualModelCritique：critic 审查 → generator 修正（`max_rounds` 上限）；
  - CritiqueInterceptor：不合格直接 `BlockAction`。
- **前置依赖**：重试信号机制（决策 D2：Transform 内就地重试 vs `request_retry()` writer）。
- **状态**：按 `session_id` 的重试/轮次计数，`SESSION_END` 清理。

### 6.6 redact（新增）

- **定位**：LLM 输出脱敏。
- **协议**：`RedactPolicy`。
- **挂载**：AFTER_LLM / Transform / priority=100（在 critique 之前，先脱敏再审查）。
- **行为**：按规则改写 `response.content`；规则可配置、可替换。

### 6.7 permission（新增）

- **定位**：工具调用权限（白名单 / 黑名单），与 approval 分工：
  approval 管"要不要人批"，permission 管"能不能调"。
- **挂载**：BEFORE_TOOL / Intercept / priority=110（approval 之后）。
- **行为**：无权调用 → `BlockAction`。

### 6.8 error（可选，先记录后强化）

- **定位**：错误分类 / 重试上限 / 降级文案。
- **挂载**：ON_ERROR / Observer。
- **说明**：ON_ERROR 目前只有 Observer，重试循环控制需 Loop 协作；
  本阶段先落地"分类 + 记录"，重试联动列为后续。

## 7. Builder 接线与配置驱动

```python
agent = (
    AgentRuntime.builder()
    .governance(
        approval=ApprovalConfig(policies=[ToolNamePolicy(["deploy"])]),
        budget=BudgetConfig(token_limit=100_000, step_limit=50),
        audit=AuditConfig(sink=MyAuditSink()),
    )
    .build()
)
```

- `.governance()` 统一入口，逐能力配置；注册返回各 hook 的 `handler_id`，
  供 `enable / disable / replace` 热插拔；
- `RuntimeConfig` 增加 `governance` 段（`stack: "full"` 或各能力配置），
  `from_config` 解析后经 `.governance()` 接线；
- 配置驱动加载涉及插件异步初始化，启动入口见决策 D1。

## 8. 兼容与迁移

- `src/runtime/hooks/_approval_hook.py` → 重导出 `src.governance.approval` 全部符号；
- `_critique_hook.py` / `_replan_hook.py` 同理（critique 真实现后 shim 指向新实现）；
- `src/runtime/__init__.py` 导出不变（间接保持）；
- 既有测试（`test_hooks_approval.py` 等）不破坏；新增 `tests/test_governance_*.py`。

## 9. 实施顺序

1. **公共底座**：`_constants.py` / `_events.py` / `_background.py` + `GovernanceConfig` + Builder `.governance()` 骨架；
2. **approval**：迁移封装 + shim + 测试；
3. **budget**：强制上限 + 测试；
4. **audit**：事件采集 + AuditSink + 测试；
5. **ratelimit**：滑动窗口 + 测试；
6. **critique**：真实现 + 测试；
7. **redact / permission**：脱敏与权限 + 测试；
8. **error**：错误分类记录 + 测试。

每一步完成即：全量测试通过、覆盖率 ≥96%、ruff 零报错、
overview + 自审记录 + README / 本文档同步。

## 10. 验收标准

- 任一治理能力可独立开关（`GovernanceConfig.enabled` / 逐能力配置）；
- 任一能力后端可协议替换（内置默认实现 + 用户实现均可）；
- 全部注册返回 `handler_id`，支持热插拔；
- 旧 import 路径与行为完全兼容；
- 一个示例工程用配置（或一行代码）启用完整治理栈；
- 全量测试 / 覆盖率 / ruff 达标。

## 11. 待确认决策

| 编号 | 决策 | 选项 |
|------|------|------|
| D1 | 启动入口 | A：`runtime.start()` 异步挂载（推荐）；B：异步 build |
| D2 | Critique 重试机制 | A：Transform 内就地重试（推荐，不动 Loop）；B：`request_retry()` writer + Loop 消费 |
| D3 | 后台任务组位置 | A：提升到 `src/runtime/_background.py` 共用（推荐）；B：governance 内自建一份 |
| D4 | 预算 cost 维度 | A：先补 `LLMUsage.cost` 字段并强制（推荐）；B：先只做 token / step，cost 留接口 |

## 附录：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/governance/__init__.py` | 新增 | 惰性导出 |
| `src/governance/_config.py` | 新增 | GovernanceConfig |
| `src/governance/_constants.py` | 新增 | 优先级段位表 |
| `src/governance/_events.py` | 新增 | GovernanceEvent |
| `src/governance/_background.py` | 新增 | 异步任务组 |
| `src/governance/approval/*` | 新增 | 审批组件（迁入 + 配置化） |
| `src/governance/budget/*` | 新增 | 预算强制组件 |
| `src/governance/audit/*` | 新增 | 审计组件 |
| `src/governance/ratelimit/*` | 新增 | 限流组件 |
| `src/governance/critique/*` | 新增 | Critique 真实现 |
| `src/governance/redact/*` | 新增 | 脱敏组件 |
| `src/governance/permission/*` | 新增 | 权限组件 |
| `src/runtime/hooks/_approval_hook.py` 等 | 修改 | 重导出 shim |
| `src/runtime/_builder.py` | 修改 | `.governance()` 接线 |
| `src/runtime/config/_runtime_config.py` | 修改 | `governance` 配置段 |
| `tests/test_governance_*.py` | 新增 | 各能力 + Builder 接线测试 |
