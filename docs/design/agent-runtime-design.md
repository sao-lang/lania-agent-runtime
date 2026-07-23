# Agent Runtime 通用架构设计

## 概述

本文档定义了 Agent Runtime 的通用架构设计，包括 Hook 挂载点、内部原语、状态管理、上下文管理和全治理组件的修改链路。设计目标：Runtime 管执行闭环，Hook 管治理逻辑，状态分层持有，互不越界。

> ⚠️ **重要：本文档是架构设计蓝图，不是 API 使用手册。**
> 开发者**必须同时阅读 [`README.md`](../../README.md)** 获取完整的 Python 接口规范、
> 4 种使用模式（傻瓜模式/加工具/加治理/完全自定义）和扩展生态说明。
> 脱离 README 阅读本文档可能导致接口实现与使用方式脱节。

---

## 一、Hook Point（挂载点）

目前定义了 **10 个挂载点**，覆盖从会话创建到错误处理的完整生命周期：

| # | Hook Point | 触发时机 | 覆盖的治理能力 |
|---|-----------|---------|-------------|
| 1 | `session_start` | 会话创建时 | Agent Identity, Audit, Observability, Session, Planner |
| 2 | `session_end` | 会话结束时 | Evaluation, Session, Audit |
| 3 | `before_step` | 每次 step 执行前 | Memory Bank, Budget control |
| 4 | `after_step` | 每次 step 执行后 | Memory Bank, Replan |
| 5 | `before_llm` | LLM 调用前 | Threat scanning, Context assembly, Token mgmt, RAG, Input guardrails, Semantic governance, Rate limiting |
| 6 | `after_llm` | LLM 调用后 | AI content detection, Output guardrails, Groundedness, Safety classification |
| 7 | `before_tool` | 工具调用前 | Threat scanning, Tool guardrails, Semantic governance, Human approval |
| 8 | `after_tool` | 工具调用后 | Groundedness, Budget control |
| 9 | `on_error` | 任意异常发生时 | Error handling |
| 10 | `session_resume` | 从 pause 状态恢复时 | Human approval 重新验证, Context 重新加载 |

> **内部 Execute**（Loop/LLM/Tool/Sandbox 的 `step()` 函数）和 **Router**（`_next()` 方法）是 Runtime 自身的可替换原语，不走 hook 注册，而是通过 DI / Strategy 替换。

---

## 二、5 种原语类型（Primitive）

每个 hook point 上挂载的组件，按其对数据流的控制力度分为 5 级：

```
Observe  <  Transform  <  Intercept  <  Router  <  Execute
(只读)     (可改数据)     (可阻断)      (改走向)    (替换执行)
```

| 原语 | 签名抽象 | 语义 | 典型用途 |
|-----|---------|------|---------|
| **Observe** | `(event, ctx) → void` | 只读观察，不能修改任何数据流 | Tracing, Audit, Observability, Evaluation |
| **Transform** | `(data, ctx) → data'` | 可修改流经的数据，但不能阻断 | Context assembly, Token mgmt, RAG, Memory Bank, Budget control(扣减) |
| **Intercept** | `(data, ctx) → Allow \| Block \| PauseForApproval` | 可阻断/暂停/放行 | Input/Output guardrails, Threat scanning, Rate limiting, Human approval, Safety classification |
| **Router** | `(ctx) → next_step_id` | 决定下一步去哪里 | Chain, Router, Parallel, Orch, EvalRouter, Multi-agent handoff, Planner/Replan |
| **Execute** | `(ctx) → Result` | 完全接管一段执行逻辑 | Loop, LLM call, Tool call, Sandbox, Stream, Background Runtime, Agent-as-tool |

### 2.1 原语的可修改字段白名单

```
原语类型      可读字段                          可写字段（受限 API）
─────────────────────────────────────────────────────────────────────
Observe      ctx 全部字段                      无（只读）

Transform    ctx 全部                         返回新值替换 data 参数；
                                              ctx.contextPayload.*（追加类方法）
                                              ctx.plan（仅 Planner/Replan）
                                              ctx.budget（仅 deduct 方法）

Intercept    ctx 全部                         无写权限；
                                              block 可导致 Runtime 终止当前路径

Router       ctx 全部                         return next_step_id 决定走向

Execute      ctx 全部（只读）                  完全接管执行；
                                              结果通过返回值写回 Runtime
```

---

## 三、Runtime 核心状态

> **原则**：Runtime 持有"执行必须"的最小状态集，Hook 是无状态纯函数，外部服务持有"治理专用"的持久化状态。

### 3.1 Runtime 必须持有的 8 类状态

```
AgentRuntime {
    // 1. 会话标识
    sessionId: string
    agentId: string
    status: "idle" | "running" | "paused" | "error" | "ended" | "cancelled"

    // 2. 消息累积（LLM 调用必须）
    messages: MessageBuffer        // system + user + assistant + tool 全量

    // 3. 执行进度（step loop 必须）
    plan: Plan                     // Planner 写入，Router 读取，Replan 修改
    stepIndex: number
    stepHistory: StepRecord[]

    // 4. 预算跟踪（Intercept hook 判读依据）
    budget: {
        tokenUsed: number
        tokenLimit: number
        stepCount: number
        stepLimit: number
        costInCents: number
    }

    // 5. 暂停/恢复（Human approval 必须）
    pauseState: {
        isPaused: boolean
        pendingApprovals: ApprovalRequest[]
        resumeToken: string        // 外部恢复凭证
    }

    // 6. 错误上下文（重试/降级决策依据）
    errorState: {
        consecutiveErrors: number
        maxRetries: number
        lastError: Error | null
    }

    // 7. 超时控制（wall-clock 超时）
    timeout: {
        stepTimeoutMs: number        // 单步超时
        totalTimeoutMs: number       // 会话总超时
        remainingMs: number          // 动态递减
        stepStartAt: int             // 当前 step 开始时间戳
    }

    // 8. 取消令牌（外部终止信号）
    cancelled: boolean               // 外部触发取消标记
}
```

### 3.2 Runtime 不持有的状态

| 不该持有的 | 理由 | 谁持有 |
|-----------|------|--------|
| API Keys / 密钥 | 安全边界，不应进运行时内存 | Capability 层 / Env |
| 长期记忆向量 | 体积大，生命周期超过 session | Memory Bank（外部向量库） |
| Agent 配置/身份 | 部署层概念，启动时注入即可 | Agent Registry |
| Tracing spans | 应直接写入外部收集器 | OpenTelemetry Collector |
| Audit 日志 | 应直接写入外部存储 | Audit Service |
| RAG 文档库 | 体积大，多 agent 共享 | RAG Service（外部） |

### 3.3 Runtime 字段的修改者

```
Runtime 字段                  修改者（原语类型 + 治理组件）
──────────────────────────────────────────────────────────────
ctx.sessionId               无（构造时设定）
ctx.agentId                 无（构造时设定）
ctx.status                  Human approval, Multi-agent handoff, Error, Cancellation
ctx.agentIdentity           Agent Identity Transform

ctx.messages                LLM/Tool Execute 返回后由 Runtime 写入
                            Output guardrails 有 modified 时替换内容

ctx.contextPayload          Memory Bank Transform → memories
  .memories                 RAG Transform → ragDocuments
  .ragDocuments             Context assembly Transform → injectedContext
  .injectedContext          Token management Transform → 裁剪所有字段
  .history                  Token management Transform → 裁剪

ctx.plan                    Planner Transform → 写入
                            Replan Transform → 改写
ctx.stepIndex               Runtime 内部 step loop 自增
ctx.stepHistory             Runtime 内部 after_step 追加

ctx.budget                  Budget control Transform → after_tool 累加
  .tokenUsed                Runtime 内部 → before_llm 调用后自动累加
                            ⚠️ Token management Transform 在 before_llm 中
                            看到的是上一次 LLM 调用后的 tokenUsed。连续 LLM
                            调用场景下超限检测会延迟一个 step。如需严格预算
                            控制，建议 Transform 自行估算即将消耗的 token
  .stepCount                Runtime 内部 → after_step 自增
  .costInCents              Budget control, Runtime 内部

ctx.pauseState              Human approval Intercept → 挂起时写入
                            Runtime.resume() → 恢复时清空

ctx.errorState              Error Intercept, Threat scanning,
  .consecutiveErrors        Input guardrails 等各种 block 导致递增
  .lastError
```

---

## 四、RuntimeContext 设计

Hook 签名中的 `ctx` 不是 Runtime 本身的引用，而是一个**不可变快照 + 类型安全的读写接口**：

```python
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class RuntimeContext:
    """
    Hook 看到的只读快照。每次 hook 调用时构造新实例。
    所有字段均为只读——修改需通过受限的 writer 方法。
    """
    # 只读快照
    session_id: str
    agent_id: str
    step_index: int
    messages: tuple[dict, ...]       # 不可变消息序列
    plan: dict | None
    budget: "BudgetSnapshot"

    # 外部服务引用（只读）
    services: dict[str, Any] = field(default_factory=dict)

    # --- 受限写方法 ---
    # 这些方法由 Runtime 内部注入，修改的是 Runtime 的内部状态而非此快照

    def set_plan(self, plan: dict) -> None:
        """仅 Planner / Replan 使用：更新执行计划"""
        ...

    def deduct_budget(self, tokens: int) -> None:
        """仅 after_tool / after_llm 使用：扣减 token 预算"""
        ...

    def update_context_payload(self, updater: Callable[["ContextPayload"], "ContextPayload"]) -> None:
        """
        允许 Transform 修改 ContextPayload 内容。
        所有上下文注入应通过此方法操作 ContextPayload，
        而非直接修改 messages。
        """
        ...
```

> **注意**：`appendMessage()` 已被移除——所有上下文注入必须通过 `update_context_payload()` 操作 `ContextPayload` 层，再由 Runtime 统一序列化为 messages。

---

## 五、ContextPayload —— 上下文管理的中间层

`messages` 是传输格式，`ContextPayload` 是操作对象。Hook 操作后者，Runtime 负责序列化为前者。

### 5.1 为什么需要 ContextPayload

1. **多源上下文有优先级和编排逻辑** — 如果每个 Transform 直接往 `messages` 里塞内容，顺序就是隐式的注册顺序，非常脆弱
2. **Token 管理需要全局视野** — 需要按语义裁剪（保留 memory，删除多余的 RAG 文档），而非盲切字符串
3. **不同 LLM provider 的 messages 格式不同** — 直接操作 `messages` 导致 Hook 耦合到具体 provider 格式

### 5.2 ContextPayload 结构

```python
from dataclasses import dataclass, field


@dataclass
class ContextPayload:
    """上下文中间层——Hook 操作此对象，Runtime 负责序列化为 messages"""

    # 不可变核心
    system_prompt: str                       # System prompt，不可被任意 Hook 覆盖

    # 可追加的上下文来源（按优先级排序）
    memories: list = field(default_factory=list)         # Memory Bank 注入
    rag_documents: list = field(default_factory=list)    # RAG 检索结果
    injected_context: list = field(default_factory=list) # 其他 Hook 注入的额外上下文

    # 对话历史（可裁剪）
    history: list = field(default_factory=list)          # 最近 N 轮对话

    # 当前 step 的工具调用上下文
    tool_call_request: dict | None = None    # 本轮要调用的工具
    tool_results: list = field(default_factory=list)     # 历史工具结果

    # 元信息（给 Token 管理用）
    max_tokens: int = 0                      # 总 token 上限
    preserve_last_n_history: int = 10        # 至少保留最近 N 轮对话
    reserve_for_response: int = 1024         # 留给 LLM 回复的 token

    # 脏标记——避免重复序列化
    _dirty: bool = True

    def mark_dirty(self) -> None:
        self._dirty = True

    def mark_clean(self) -> None:
        self._dirty = False

    @property
    def is_dirty(self) -> bool:
        return self._dirty
```

### 5.3 数据流

```
ContextPayload（结构化、多源、可语义操作）
    │
    ├── Memory Bank hook  → 追加 memories
    ├── RAG hook          → 追加 ragDocuments
    ├── Token management  → 按优先级裁剪各来源
    └── 其他 Transform    → injectContext
    │
    ▼
serialize() ─────────────→ messages[0] = system message（单次产物，不持久）
    │
    ▼
messages[] ──────────────→ LLM API（最终传输格式）
```

`messages[0]` 是每次 `before_llm` 结束时从 `ContextPayload` 重新序列化生成的 system message。`messages[1..n]` 是对话日志，遵循以下契约：

- **常规情况**：只追加不修改（Runtime 内部在 LLM/Tool Execute 后追加新条目）
- **特殊例外**：`after_llm` Intercept 的 `modified` 结果可替换 messages 中最后一条 assistant 消息（这是唯一允许修改已有 messages 的路径）

### 5.4 避免重复序列化

每次 `before_llm` 都重新序列化 ContextPayload 代价较高，引入脏标记（dirty flag）机制：

1. 任何 Transform 修改 ContextPayload → 自动标记为 `_dirty = True`
2. `serialize()` 仅在 `_dirty` 时为 True 时执行序列化，否则返回上次序列化结果
3. 序列化完成后清除 `_dirty` 标记
4. 若本轮 step 不需要 LLM 调用（如纯工具执行步骤），序列化完全跳过

---

## 六、Hook 注册接口

### 6.1 原语类型定义

```python
from typing import Protocol, TypeVar, Any, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum

T = TypeVar("T")
Event = dict[str, Any]


class PrimitiveType(Enum):
    """原语类型——决定 handler 在 hook 管线中的行为"""
    OBSERVER = "observer"       # 只读观察
    TRANSFORM = "transform"     # 可改数据
    INTERCEPT = "intercept"     # 可阻断
    ROUTER = "router"           # 改走向（替换 _next）
    EXECUTE = "execute"         # 替换执行（替换核心引擎）


class HookPoint(Enum):
    """挂载点枚举——对应 Runtime 执行流程中的 10 个关键位置"""
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    SESSION_RESUME = "session_resume"
    BEFORE_STEP = "before_step"
    AFTER_STEP = "after_step"
    BEFORE_LLM = "before_llm"
    AFTER_LLM = "after_llm"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    ON_ERROR = "on_error"
    ON_STREAM_CHUNK = "on_stream_chunk"


# ============ 原语 Protocol ============

class Observer(Protocol):
    """只读观察：不能修改任何数据"""
    async def __call__(self, event: Event, ctx: "RuntimeContext") -> None: ...


class Transformer(Protocol[T]):
    """可变数据：返回新值替换 data 参数"""
    async def __call__(self, data: T, ctx: "RuntimeContext") -> T: ...


@dataclass
class AllowAction:
    """Intercept 放行结果"""
    modified: Any | None = None


@dataclass
class BlockAction:
    """Intercept 阻断结果"""
    reason: str = ""


@dataclass
class PauseAction:
    """Intercept 暂停结果——等待 Human approval"""
    approval_id: str = ""


InterceptResult = AllowAction | BlockAction | PauseAction


class Interceptor(Protocol[T]):
    """可阻断：返回 Allow | Block | Pause"""
    async def __call__(self, data: T, ctx: "RuntimeContext") -> InterceptResult: ...


type RouterFn = Callable[[RuntimeContext], Awaitable[str]]
type ExecutorFn[T] = Callable[[RuntimeContext], Awaitable[T]]
```

### 6.2 HookRegistry —— 核心注册引擎

```python
@dataclass
class HandlerInfo:
    """已注册 handler 的元信息"""
    handler_id: str
    point: HookPoint
    primitive: PrimitiveType
    handler: Callable
    priority: int = 0
    name: str = ""


class HookRegistry:
    """
    Hook 注册中心——分层编排引擎。

    同一 hook point 上按以下顺序执行：
      1. Transformer（按 priority 升序）
      2. Interceptor（按 priority 升序，遇到 block/pause 短路）
      3. Observer（按 priority 升序，全部执行不阻塞）
    """

    def register(
        self,
        point: HookPoint,
        handler: Callable,
        *,
        primitive: PrimitiveType,   # 必须显式指定原语类型
        name: str = "",             # 可选，用于调试/热加载
        priority: int = 0,          # 可选，值越小越先执行
    ) -> str:
        """注册一个 handler，返回 handler_id（可用于后续移除）"""
        ...

    def remove(self, handler_id: str) -> None:
        """移除已注册的 handler"""
        ...

    def list(self, point: HookPoint | None = None) -> list[HandlerInfo]:
        """列出所有（或指定 point 的）已注册 handler"""
        ...

    def replace(self, handler_id: str, new_handler: Callable) -> None:
        """替换已注册的 handler（保持 point / primitive / priority 不变）"""
        ...

    async def run_transformers(self, point: HookPoint, data: Any, ctx: RuntimeContext) -> Any:
        """执行指定 point 上所有 Transform，返回最终 data"""

    async def run_interceptors(self, point: HookPoint, data: Any, ctx: RuntimeContext) -> InterceptResult:
        """执行指定 point 上所有 Intercept，返回第一个 block/pause 或最终 allow"""

    async def run_observers(self, point: HookPoint, event: Event, ctx: RuntimeContext) -> None:
        """并发执行指定 point 上所有 Observer"""
```

### 6.3 AgentRuntime 对外 API

```python
class AgentRuntime:
    """
    对外暴露的便捷方法——内部委托给 HookRegistry。

    注册方法的命名约定：
      - observe_xxx()     → 注册 Observer
      - transform_xxx()   → 注册 Transformer
      - intercept_xxx()   → 注册 Interceptor
      - set_xxx()         → 替换 Router / Executor（不经过 HookRegistry）
    """

    def __init__(self, hooks: HookRegistry | None = None, ...):
        self._hooks = hooks or HookRegistry()

    # === Observer 注册 ===
    def observe(self, point: HookPoint, handler: Observer, *, name: str = "", priority: int = 0) -> str:
        return self._hooks.register(point, handler, primitive=PrimitiveType.OBSERVER, name=name, priority=priority)

    # === Transform 注册 ===
    def transform(self, point: HookPoint, handler: Transformer, *, name: str = "", priority: int = 0) -> str:
        return self._hooks.register(point, handler, primitive=PrimitiveType.TRANSFORM, name=name, priority=priority)

    # === Intercept 注册 ===
    def intercept(self, point: HookPoint, handler: Interceptor, *, name: str = "", priority: int = 0) -> str:
        return self._hooks.register(point, handler, primitive=PrimitiveType.INTERCEPT, name=name, priority=priority)

    # === Runtime 引擎配置（不经过 HookRegistry，通过 DI / setter 替换） ===

    def set_router(self, router: RouterFn) -> None:
        """替换 _next() 行为——如 Chain / Router / Parallel / Orch / Handoff"""
        ...

    def set_llm_executor(self, executor: ExecutorFn) -> None:
        """替换 LLM 调用实现——如 OpenAI → Claude 切换"""
        ...
        # 详见 docs/design/llm-executor-design.md

    def set_tool_executor(self, executor: ExecutorFn) -> None:
        """替换工具执行实现"""
        ...

    def set_loop_executor(self, executor: ExecutorFn) -> None:
        """替换 Step Loop 实现——如 ReAct → PlanExecute → Workflow"""
        ...
        # 详见 docs/design/loop-strategy-design.md

    # === 装饰器语法糖（面向用户的便捷方式） ===

    def on(self, point: HookPoint, *, primitive: PrimitiveType = PrimitiveType.OBSERVER, priority: int = 0):
        """装饰器：@runtime.on(HookPoint.AFTER_LLM)"""
        def decorator(func):
            self._hooks.register(point, func, primitive=primitive, priority=priority)
            return func
        return decorator
```

### 6.4 设计说明

1. **Python 不支持函数重载**——因此用方法名后缀（`observe` / `transform` / `intercept`）或 `primitive` 参数来区分原语类型，而非 TypeScript 的同名重载
2. **`set_router` / `set_llm_executor` 等 setter 方法不经过 HookRegistry**——它们直接替换 Runtime 的核心引擎，对应 §9 关键设计决策中的"Execute/Router 通过 DI / Strategy 替换"
3. **装饰器语法 `@runtime.on(HookPoint.AFTER_LLM)`** 提供声明式注册方式，适合简单场景
4. **`HandlerInfo` 的 `handler_id` 支持后续热加载操作**（remove / replace / list）

---

## 七、内部执行模型（完整数据流）

```
Session Start
  │
  ├─[session_start: Observer → Transformer]
  │   Agent Identity: Intercept → 注入身份
  │   Planner: Transform → ctx.setPlan()
  │   Audit / Observability: Observe
  │
  ├─[session_resume: Observer → Transformer]（仅从 pause 恢复时触发）
  │   Human approval 重新验证
  │   Context 重新加载
  │   Audit: Observe
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│  Step Loop (可替换 Execute 原语)                         │
│                                                         │
│  Runtime: ctx.stepIndex++, ctx.stepHistory.push(step)   │
│                                                         │
  ┌─[before_step: 取消检查]                               │
  │   ctx.cancelled → 走 session_end 清理终止            │
  │                                                      │
  ├─[before_step: 超时检查]                               │
  │   ctx.timeout.remainingMs ≤ 0 → on_error             │
  │                                                      │
  ├─[before_step: Intercept]                             │
│  │   Budget control: 读 ctx.budget → allow/block        │
│  │   block → on_error, step 终止                        │
│  │                                                      │
│  ├─[before_step: Transform]                             │
│  │   Memory Bank: 读外部记忆                             │
│  │     → ctx.contextPayload.addMemory()                 │
│  │                                                      │
│  ├─[Router: _next()]                                    │
│  │   Planner: 读 ctx.plan → return stepId               │
│  │   Chain/Router/Parallel/Orch/Handoff 选一种           │
│  │                                                      │
│  ├─ LLM 调用段 ──────────────────────────────────────   │
│  │   [before_llm: Transform]                            │
│  │     Context assembly → ctx.contextPayload.inject()   │
│  │     RAG → ctx.contextPayload.addRagDocument()        │
│  │     Token mgmt → 裁剪 ctx.contextPayload.*           │
│  │                                                      │
  │   [before_serialize: Transform]（仅在 dirty 时执行） │
  │     最终格式调整，provider 适配                      │
  │     检查脏标记，跳过重复序列化                       │
  │                                                      │
  │   [before_llm: Intercept]                            │
  │     Input guardrails → allow/block                   │
  │     Rate limiting → allow/block                      │
  │     Threat scanning → allow/block                    │
  │     Semantic governance → allow/block                │
  │                                                      │
  │   Runtime: messages = serialize(ctx.contextPayload)  │
  │            + ctx.messages[1:]                        │
  │            （仅在 dirty 时执行，否则复用上次结果）   │
│  │                                                      │
│  │   [LLM Execute] → LLMResponse                        │
│  │   [Stream: Observe/Transform] 每个 chunk             │
│  │                                                      │
│  │   Runtime: ctx.messages.push(response)               │
│  │            ctx.budget.tokenUsed += tokens            │
│  │                                                      │
│  │   [after_llm: Intercept]                             │
│  │     Output guardrails → allow/block/modified         │
│  │     Groundedness → allow/block                       │
│  │     Safety classification → allow/block              │
│  │     modified → 替换 messages 最后一条内容             │
│  │                                                      │
│  │   [after_llm: Observe]                               │
│  │     AI content detection → 外部标记                  │
│  │     Tracing / Audit → 写外部系统                     │
│  │                                                      │
│  ├─ Tool 调用段（如有）──────────────────────────────   │
│  │   [before_tool: Intercept]                           │
│  │     Tool guardrails → allow/block                    │
│  │     Human approval → pause / allow                   │
│  │     Threat scanning → allow/block                    │
│  │     Semantic governance → allow/block                │
│  │                                                      │
│  │   pause → Runtime 挂起，ctx.pauseState 写入          │
│  │        → 外部信号 → Runtime.resume()                 │
│  │        → 重新走 before_tool                          │
│  │                                                      │
│  │   [Tool Execute] → ToolResult                        │
│  │     若 tool=agent-as-tool → 启动子 Runtime           │
│  │                                                      │
│  │   Runtime: ctx.messages.push({role:"tool", result})  │
│  │            ctx.toolResults.push(result)              │
│  │                                                      │
│  │   [after_tool: Transform]                            │
│  │     Budget control: ctx.budget.tokenUsed += tokens   │
│  │                                                      │
│  │   [after_tool: Intercept/Observe]                    │
│  │     Groundedness → block/observe                     │
│  │                                                      │
│  ├─ Step 结束 ──────────────────────────────────────   │
│  │   [after_step: Transform]                            │
│  │     Memory Bank: 写回外部记忆                        │
│  │     Replan: 若偏差 → ctx.setPlan(newPlan)            │
│  │                                                      │
│  │   Runtime: ctx.budget.stepCount++                    │
│  │                                                      │
│  │   [Router._next() → 下一 step 或 结束]              │
│  │                                                      │
│  └─ [on_error]（任意阶段异常触发）                       │
│      Error Intercept: 读 error → retry/skip/degrade     │
│      Error Router: 决定 nextStepId                      │
│      ctx.errorState 更新                                │
└─────────────────────────────────────────────────────────┘
  │
  ▼
Session End
  ├─[session_end: Observer]
  │   Evaluation → 评估模型打分
  │   Audit → 审计汇总写入
  └─[session_end: Transform]
      Session → 清理、脱敏、持久化
```

---

## 八、全治理组件修改链路

以下按编号列出每个治理组件经过的原语步骤及修改的 Runtime 字段。

### #1 Agent Registry（部署层，不进 Runtime）

Agent Registry → 启动时读取 agent 配置 → 注入 `Runtime.agentId`, `Runtime.hooks[]`。不经过任何 Hook，是 Runtime 构造阶段的初始化。

### #2 Agent Identity → `session_start` Intercept

- 从外部服务读取 agent 身份信息
- 返回 `{ action: "allow", modified: { agentIdentity } }`
- 修改：`ctx.agentIdentity`

### #3 Tracing → 全部 hook point 的 Observe

- 构造 span，写入外部 OpenTelemetry Collector
- 无修改

### #4 Audit → 全部 hook point 的 Observe

- 序列化为审计日志，写入外部审计存储
- 无修改

### #5 Observability → 全部 point 的 Observe

- 读取性能指标，写入 Prometheus / Grafana
- 无修改

### #6 Evaluation → `session_end` Observe

- 读取完整会话数据，调用评估模型打分
- 无修改

### #7 Threat scanning → `before_llm` + `before_tool` Intercept

- 扫描消息内容或工具参数
- 命中威胁 → `block`，触发 `on_error`；安全 → `allow`
- block 时：`ctx.errorState.lastError` 更新，`ctx.status = "error"`

### #8 AI content detection → `after_llm` Observe

- 调用 AI 内容检测服务，写入标签到外部存储
- 无修改

### #9-14 Loop/LLM/Tool/Sandbox/Stream/BgRuntime → 内部 Execute

Execute 替换 Runtime 核心执行逻辑，结果通过返回值写回 Runtime：

- LLM Execute 返回 → Runtime 写入 `ctx.messages.append(response)`
- Tool Execute 返回 → Runtime 写入 `ctx.toolResults.append(result)`，同时写入 `ctx.messages.append({role: "tool", content: result})`

### #15 Error handling → `on_error` Intercept + Transform + Router

- Intercept：决定 retry / skip / escalate / degrade
- Transform：在 retry 前对错误做降级处理（截断错误消息、擦除敏感信息）
- Router：返回对应 stepId（当前 stepId 重试 / 跳过 / 降级 stepId / null 终止）
- 修改：`ctx.errorState.consecutiveErrors`（block 时递增），`ctx.errorState.lastError`

### #16 Session → `session_start` / `session_end` Transform

- `session_start`：从外部加载历史上下文，注入 metadata
- `session_end`：清理、脱敏、持久化
- 修改：`ctx.session`（start 设置，end 标记结束）

### #17 Memory Bank → `before_step` + `after_step` Transform

- `before_step`：读取近期记忆 → `ctx.contextPayload.addMemory()`
- `after_step`：提取关键信息 → 通过 `ctx.services.memory.write()` 写入外部
- 修改：`ctx.contextPayload.memories`（追加）

### #18 Context assembly → `before_llm` Transform

- 判断是否需要额外上下文注入 → `ctx.contextPayload.injectContext()`
- 修改：`ctx.contextPayload.injectedContext`（追加）

### #19 Token management → `before_llm` Transform

- 预序列化计算 tokens，超过上限时按优先级裁剪
- 修改：`ctx.contextPayload.history`, `.ragDocuments`, `.memories`, `.injectedContext`（裁剪）

### #20 RAG retrieval → `before_llm` Transform

- 提取用户最后一条消息作为 query → `ctx.services.rag.search(query)`
- 修改：`ctx.contextPayload.ragDocuments`（追加）

### #21 Input guardrails → `before_llm` Intercept

- 检查 PII 泄露 / 越狱提示 / 不允许的话题
- 命中 → `block`；安全 → `allow`
- block 时：step 终止，`ctx.errorState` 更新

### #22 Output guardrails → `after_llm` Intercept

- 检查 PII 泄露 / 有害内容 / 幻觉 / 权限范围
- 命中 → `block` 或 `allow + modified`
- modified 时：`ctx.messages` 中最后一条 assistant 消息被替换

### #23 Tool guardrails → `before_tool` Intercept

- 检查参数越权、policy 违规
- 命中 → `block`；安全 → `allow`

### #24 Semantic governance → `before_llm` + `before_tool` Intercept

- 语义检查是否符合治理策略
- 不符合 → `block`；符合 → `allow`

### #25 Human approval → `before_tool` Intercept

- 需要审批 → `pause`，写入 `ctx.pauseState`，持久化到外部
- 外部恢复后重新走 `before_tool` → `allow`
- 修改：`ctx.pauseState`, `ctx.status = "paused"` / `"running"`

### #26 Budget control → `before_step` Intercept + `after_tool` Transform

- `before_step` Intercept：检查 budget 各项是否超限 → `allow` / `block`
- `after_tool` Transform：累加 `ctx.budget.tokenUsed`, `ctx.budget.costInCents`
- 修改：`ctx.budget.tokenUsed`, `ctx.budget.costInCents`

### #27 Rate limiting → `before_llm` Intercept

- 查询限流服务，配额用尽 → `block`；有配额 → `allow`

### #28 Groundedness → `after_llm` + `after_tool` Intercept/Observe

- `after_llm` Intercept：事实检查，检测幻觉 → `block` / `allow`
- `after_tool` Observe：检查结果格式，仅观测不阻断

### #29 Safety classification → `after_llm` Intercept

- 安全分类模型 → harmful → `block`；caution → `allow + flagged`；safe → `allow`
- flagged 时：`ctx.messages` 中该条消息附加 `metadata: { safetyFlag: true }`

### #30-34 Chain/Router/Parallel/Orch/EvalRouter → Router 原语（`_next` 方法）

- Chain Router：`return plan.steps[ctx.stepIndex + 1]`
- LLM Router：调用 LLM 决策 → 返回选中的 stepId
- Parallel Router：`return [stepA, stepB, stepC]`（并发）
- Orch Router：调用编排模型 → 返回最优下一步
- Eval Router：读取 evalResults → 策略选择 → 返回 stepId
- 不修改字段，通过返回值控制 Runtime 走向

### #35 Planner → `session_start` Transform + Router

- `session_start` Transform：调用 LLM 生成执行计划 → `ctx.setPlan(generatedPlan)`
- Router：读取 `ctx.plan` → 返回第一个 stepId
- 修改：`ctx.plan`

### #36 Replan → `after_step` Transform + Router

- `after_step` Transform：判断偏差 → 调用 LLM 重新规划 → `ctx.setPlan(newPlan)`
- Router：读取更新后的 `ctx.plan` → 返回当前进度指向的 stepId
- 修改：`ctx.plan`

### #37 Multi-agent handoff → Router

- 判断需要切换 agent → `return { targetAgentId, handoffMessage, context }`
- 当前 Runtime `ctx.status = "handed_off"`
- 新 Runtime 从 handoff 信息初始化

### #38 Agent-as-tool → Tool Execute 内部递归

- `executeTool` 启动子 Runtime，持有独立 hook 链
- 子 Runtime **拷贝**父 Runtime 的 HookRegistry（深拷贝 handler 引用）
- Observer 类 hooks：父 Runtime 的 handler 自动注册到子 Runtime
- Intercept 类 hooks：子 Runtime 可覆盖同名 handler，互不影响父 Runtime
- Transform 类 hooks：子 Runtime 默认继承，可追加新的
- 子 Runtime 完成后 → 结果作为 ToolResult 返回
- 父 Runtime 正常走 after_tool 流程

---

## 九、关键设计决策

1. **Execute 原语不通过 hook 注册，而是通过 DI / Strategy 替换** — LLM、Tool、Loop 的执行器是 Runtime 核心骨架，应直接替换实现（如 OpenAI → Claude，或本地 sandbox → 远程 sandbox）

2. **Router 同理** — `_next()` 方法是 Runtime 内核的决策引擎，Chain/Router/Parallel/Orch/Handoff 都通过替换 Router 实现

3. **Human approval 是 Intercept 原语的 `pause` 状态** — Runtime 挂起当前 step，持久化到外部存储，等待外部信号恢复。要求 Runtime 支持 step 级别的暂停/恢复协议

4. **Agent-as-tool 是 Execute 的递归** — 工具执行器内部启动子 Runtime，子 Runtime **拷贝**父 Runtime 的 HookRegistry（深拷贝 handler 引用）。Observer 自动继承，Intercept 可覆盖（互不影响），Transform 默认继承可追加

5. **Agent Registry 是部署层概念** — 不在 Runtime 内部，而是在 Runtime 启动时从 Registry 拉取配置决定挂载哪些能力组件

6. **Hook 是无状态纯函数** — 可任意组合、排序、热加载，可独立测试。状态集中由 Runtime 持有，Hook 通过 `ctx` 只读访问

7. **ContextPayload 是上下文操作对象，messages 是传输格式** — Hook 操作 ContextPayload，Runtime 负责序列化为 messages。引入脏标记避免重复序列化

---

## 十、Python 接口总览

以下列出核心类的完整签名，作为编码实现的参考骨架。

### AgentRuntime

```python
class AgentRuntime:
    def __init__(
        self,
        *,
        system_prompt: str,
        hooks: HookRegistry | None = None,
        llm_executor: ExecutorFn | None = None,
        tool_executor: ExecutorFn | None = None,
        loop_executor: ExecutorFn | None = None,
        router: RouterFn | None = None,
        services: dict[str, Any] | None = None,
    ) -> None: ...

    # === 核心执行 ===
    async def run(self, user_input: str) -> str: ...
    async def run_step(self) -> None: ...

    # === 生命周期控制 ===
    async def resume(self, approval_id: str) -> None: ...
    async def cancel(self) -> None: ...

    # === 注册方法 ===
    def observe(self, point: HookPoint, handler: Observer, *, name: str = "", priority: int = 0) -> str: ...
    def transform(self, point: HookPoint, handler: Transformer, *, name: str = "", priority: int = 0) -> str: ...
    def intercept(self, point: HookPoint, handler: Interceptor, *, name: str = "", priority: int = 0) -> str: ...

    # === 引擎替换 ===
    def set_router(self, router: RouterFn) -> None: ...
    def set_llm_executor(self, executor: ExecutorFn) -> None: ...
    def set_tool_executor(self, executor: ExecutorFn) -> None: ...
    def set_loop_executor(self, executor: ExecutorFn) -> None: ...

    # === 装饰器 ===
    def on(self, point: HookPoint, *, primitive: PrimitiveType = PrimitiveType.OBSERVER, priority: int = 0): ...
```

### HookRegistry

```python
class HookRegistry:
    def register(self, point: HookPoint, handler: Callable, *, primitive: PrimitiveType, name: str = "", priority: int = 0) -> str: ...
    def remove(self, handler_id: str) -> None: ...
    def list(self, point: HookPoint | None = None) -> list[HandlerInfo]: ...
    def replace(self, handler_id: str, new_handler: Callable) -> None: ...

    # 内部执行管线（由 Runtime 调用）
    async def run_transformers(self, point: HookPoint, data: Any, ctx: RuntimeContext) -> Any: ...
    async def run_interceptors(self, point: HookPoint, data: Any, ctx: RuntimeContext) -> InterceptResult: ...
    async def run_observers(self, point: HookPoint, event: Event, ctx: RuntimeContext) -> None: ...
```

### RuntimeContext

```python
@dataclass(frozen=True)
class RuntimeContext:
    session_id: str
    agent_id: str
    step_index: int
    messages: tuple[dict, ...]
    plan: dict | None
    budget: "BudgetSnapshot"
    services: dict[str, Any]

    def set_plan(self, plan: dict) -> None: ...
    def deduct_budget(self, tokens: int) -> None: ...
    def update_context_payload(self, updater: Callable[[ContextPayload], ContextPayload]) -> None: ...
```

### ContextPayload

```python
@dataclass
class ContextPayload:
    system_prompt: str
    memories: list = field(default_factory=list)
    rag_documents: list = field(default_factory=list)
    injected_context: list = field(default_factory=list)
    history: list = field(default_factory=list)
    tool_call_request: dict | None = None
    tool_results: list = field(default_factory=list)
    max_tokens: int = 0
    preserve_last_n_history: int = 10
    reserve_for_response: int = 1024
    # 脏标记
    _dirty: bool = True

    @property
    def is_dirty(self) -> bool: ...
    def mark_dirty(self) -> None: ...
    def mark_clean(self) -> None: ...
```

### 类型别名

```python
# 枚举
class PrimitiveType(Enum): OBSERVER, TRANSFORM, INTERCEPT, ROUTER, EXECUTE
class HookPoint(Enum): SESSION_START, SESSION_END, SESSION_RESUME, BEFORE_STEP, AFTER_STEP, BEFORE_LLM, AFTER_LLM, BEFORE_TOOL, AFTER_TOOL, ON_ERROR, ON_STREAM_CHUNK

# Protocol
class Observer(Protocol):     async def __call__(self, event, ctx): ...
class Transformer(Protocol):  async def __call__(self, data, ctx): ...
class Interceptor(Protocol):  async def __call__(self, data, ctx): ...

# 联合类型
InterceptResult = AllowAction | BlockAction | PauseAction
RouterFn = Callable[[RuntimeContext], Awaitable[str]]
ExecutorFn = Callable[[RuntimeContext], Awaitable[T]]
```

---

> **下一步**：查看 [`README.md`](../../README.md) 了解完整的 Python 使用示例（4 种渐进式模式）、
> 扩展插件安装和开发指南。

---

## 十一、关联设计文档

本文档是 Runtime 整体的架构总纲。各子模块的详细设计方案见以下独立文档：

| 文档 | 内容 | 对应主文档章节 |
|------|------|--------------|
| [`llm-executor-design.md`](llm-executor-design.md) | LLMExecutor 接口、Provider 适配器、流式执行 | §6.4 `set_llm_executor` |
| [`loop-strategy-design.md`](loop-strategy-design.md) | 3 种 LoopStrategy（ReAct / PlanExecute / Workflow）、工厂模式 | §6.4 `set_loop_executor` |
| [`context-management-redesign.md`](context-management-redesign.md) | ContextManager 五阶段管线：Select → Load → Compress → Budget → Serialize | §5 ContextPayload |
| [`memory-system-design.md`](memory-system-design.md) | 5 层记忆系统（工作/情景/实体/语义/行为模式）、SQLite 存储 | §8 #17 Memory Bank |
| ~~`observer-and-primitive-redesign.md`~~ | **已废弃**——核心思想已并入 §6，编码以 §6 为准 | §6 |
| [`orchestration-components-design.md`](orchestration-components-design.md) | Planner、Replanner、CoT、子任务拆解、反思/自我批评 | §7 Router / §8 #35-36 |
| [`serializer-design.md`](serializer-design.md) | MessageSerializer 可替换接口、ContextManager 第 5 阶段 | §5.3 序列化 / context-management.md §8 |
| [`tool-mcp-skill-design.md`](tool-mcp-skill-design.md) | ToolSpec / MCPBridge / SkillManager 三种工具原语、统一调度器 | §8 #23 Tool guardrails |

> ⚠️ **重要**：编码实现时，**必须同时加载主文档 + 对应子文档**作为上下文，否则可能因缺少交叉引用导致实现偏差。
> 各文档之间通过顶部 ⚠️ 标记相互绑定——阅读任一子文档时请留意其关联文档列表。
