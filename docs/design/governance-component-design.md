# 护栏（治理）组件封装方案（v0.2 落实版）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的
> **Hook 治理体系**（12 挂载点 × 5 种原语）、**RuntimeContext 受限 writer**（§4）
> 与 **Builder 唯一接线点**。
>
> 关联文档：
> - [`session-component-design.md`](session-component-design.md) — 组件封装范式参照（config / protocols / models / hooks / Builder）
> - [`memory-system-design.md`](memory-system-design.md) — 协议解耦与按层注入模式参照
> - [`orchestration-components-design.md`](orchestration-components-design.md) — 编排组件（Critique 等）现状
> - [`loop-strategy-design.md`](loop-strategy-design.md) — LoopStrategy 与治理 Hook 的协作
> - [`context-management-redesign.md`](context-management-redesign.md) — 与 context 预算的职责边界（见 §2.4）

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
- 接入层网关（HTTP / SSE 服务）不在本文档范围内实现，但其与护栏的分工契约见 §8；
- 编排高级模式（AgentTool / 多 Agent）维持"暂缓 / 按需"状态。

## 1. 现状盘点

| 项 | 状态 |
|----|------|
| 治理机制（12 挂载点 × 5 原语） | ✅ 已实现 |
| HookRegistry 热插拔（enable / disable / replace / remove） | ✅ 已实现 |
| Plugin / PluggableComponent（`runtime.use()` 异步挂载） | ✅ 已实现 |
| Builder 唯一接线点 | ✅ 已实现 |
| 审批（ApprovalPolicy + HumanApprovalInterceptor） | ⚠️ 已实现但未组件化（位于 `runtime/hooks`） |
| Critique（Self / Dual） | ⚠️ 占位（仅记录元信息，未真正调用审查模型） |
| Replan | ✅ 完成（通用 ReplanHook + PlanExecuteLoop 内置） |
| 预算 | ⚠️ 只记账不强制（`RuntimeConfig.budget` 上限无执行者） |
| 审计 / 限流 / 脱敏 / 权限 / 错误治理 | ❌ 缺失 |

## 2. 设计原则

### R1 Runtime 纯壳

`AgentRuntime` 不感知任何治理组件；唯一接线点是 `RuntimeBuilder`。
因此 `src/runtime` 不得 import `src.governance`（含 TYPE_CHECKING）。

### R2 依赖单向 + 零耦合

`src/governance` 只依赖 `src.runtime` 的类型与协议
（HookPoint / PrimitiveType / RuntimeContext / LLMResponse / HookRegistry /
RuntimeController 的受控接口），**禁止** import `session / memory / context` 的实现；
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
Builder 注册时对同一挂载点 + 原语的重复优先级给出告警。

### R5 状态与并发约束

- `ctx.services` 是浅拷贝，**不可写共享状态**（v2 已确立）；
- 有状态治理（限流计数、Critique 重试、审计缓冲）放在 **Hook 实例内部**，
  按 `session_id` 索引，`SESSION_END` 统一清理（沿用 ReplanHook 先例）；
- 审计等重 IO 使用异步缓冲 + 后台任务，不阻塞主流程（`_background.py`），
  带背压上限（超限丢弃并告警，见 §6.3）。

### R6 兼容优先

现有 `src/runtime/hooks/_approval_hook.py` / `_critique_hook.py` / `_replan_hook.py`
及 `src/runtime/__init__.py` 的导出**保持可用**：
逻辑迁入 governance 后，旧模块改为**只读重导出 shim**（禁止再新增逻辑，防止双实现漂移）。

### R7 数据归属与状态分层

| 数据 | 归属 | 读写规则 |
|------|------|---------|
| 执行状态（messages / plan / budget / step_index） | Runtime | 治理**只读** `ctx.budget` 等；如需修改必须走受限 writer |
| 治理实例状态（限流计数 / 重试次数 / 已审批 ID / 审计缓冲） | 治理 Hook 实例 | 按 `session_id` 索引，`SESSION_END` 清理 |
| 后端数据（审计 / 审批 / 限流持久化） | 外部后端 | 治理经协议写入，不内建存储 |
| 请求元数据（client_ip / route / user） | 宿主 / 网关 | 只读注入 `ctx.services`，治理不写 |

## 3. 零耦合约束与验证清单

### 3.1 依赖矩阵

| 依赖方向 | 允许 | 说明 |
|----------|------|------|
| `src/governance` → `src.runtime` | ✅ 仅类型/协议 | RuntimeContext / HookPoint / LLMResponse 等 |
| `src/governance` → `session / memory / context` | ❌ 禁止 | 运行期与 TYPE_CHECKING 均禁止 |
| `src/runtime` → `src/governance` | ❌ 禁止 | 纯壳约束 |
| `RuntimeBuilder` → `src.governance` | ✅ 允许 | 唯一接线点 |
| `src/governance` → 外部后端协议 | ✅ 允许 | 协议注入，非耦合 |

### 3.2 零耦合验证清单（实现时逐条核对）

- [ ] `src/governance` 中无 `import src.session` / `src.memory` / `src.context`（含 TYPE_CHECKING 块）
- [ ] `src/runtime` 中无 `import src.governance`
- [ ] 治理 hook 不调用 `SessionService.*` / `MemoryService.*` / `ContextManager.*`
- [ ] 跨组件数据只经 `RuntimeContext` / `RuntimeBuilder` 传递
- [ ] 与既有 hooks 的边界：实现只存在一处（governance），`runtime/hooks` 仅重导出

## 4. 组件封装范式与目录结构

护栏是一个组件域：`src/governance/` 包内部按能力分子组件，
每个子组件复用 session 组件的范式：

| session 组件 | 护栏子组件（每个能力） | 职责 |
|-------------|----------------------|------|
| `_config.py` | `_config.py` | 该能力的配置 dataclass |
| `_protocols.py` | `_protocols.py` | 可替换后端协议 |
| `_models.py` | `_models.py` | 数据类（审计事件 / 限流窗口 / 审批上下文） |
| `_hooks/` | `_hooks.py` | 挂载点 handler，**只依赖协议** |
| `__init__.py` | `__init__.py` | 惰性导出（`__getattr__`） |
| Builder `.session()` | Builder `.governance(...)` | 唯一接线点，注册并返回 handler_id |

无持久化需求的能力（approval / critique / redact / ratelimit）不需要
`_store / _service`；audit 落库走 `AuditSink` 协议，同样不内建 store。

```text
src/governance/
  __init__.py            # 惰性导出：GovernanceConfig + 各能力
  _config.py             # GovernanceConfig（enabled + stack + 各能力配置引用）
  _constants.py          # 治理优先级段位表（唯一契约来源）
  _events.py             # GovernanceEvent 审计事件 schema
  _background.py         # 异步任务组（审计缓冲用）
  approval/
    _config.py           # ApprovalConfig
    _protocols.py        # ApprovalPolicy（迁自 runtime/hooks/_approval_hook.py）
    _models.py           # ApprovalContext（可选）
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
| BEFORE_LLM | 110 | Intercept | budget（token / step / cost 强制） |
| BEFORE_TOOL | 100 | Intercept | approval（人工审批） |
| BEFORE_TOOL | 110 | Intercept | permission（工具权限） |
| AFTER_LLM | 100 | Transform | redact（输出脱敏，最早改） |
| AFTER_LLM | 200 | Transform | critique（自批评 / 双模型修正） |
| AFTER_LLM | 210 | Intercept | critique_block（安全拦截，可选） |
| AFTER_LLM | 999 | Transform | 默认预算记账（已有，保持最后） |
| 各点 | — | Observer | audit（Observer 并发执行，天然适配） |

### 5.2 原语链执行语义（代码依据，实现时必须遵守）

| 挂载点 | 实际执行顺序 | 出处 |
|--------|-------------|------|
| BEFORE_STEP | Intercept → Transform → Observer | `loops/_base.py` |
| BEFORE_LLM | Transform → Intercept | `steps/_step_runner.py` |
| AFTER_LLM | Transform → Intercept → Observer | 同上 |
| BEFORE_TOOL | Intercept（+ 后续 Transform/Observer 在工具执行后） | 同上 |
| AFTER_STEP / SESSION_* | Transform → Observer | `loops/_base.py` / `runtime/_runtime.py` |
| ON_ERROR / ON_STREAM_CHUNK | Observer / Transform → Observer | 同上 |

> 结论：**"限流/预算/审批/权限"必须选 Intercept**（可阻断）；
> **"脱敏/Critique 修正"必须选 Transform**（可改数据流，且先于 Intercept 执行）；
> **"审计/错误记录"选 Observer**（并发、只读）。

### 5.3 审计事件（`_events.py`）

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

### 5.4 异步任务组（`_background.py`）

审计 / 异步落库的后台任务组，语义与 memory 侧一致（等待排空 + 超时取消）。
实现位置见决策 D3（推荐提升到 `src/runtime/_background.py` 共用，避免两份实现漂移）。

### 5.5 GovernanceConfig（`_config.py`）

```python
@dataclass
class GovernanceConfig:
    """护栏总配置——各能力可独立开关。"""

    enabled: bool = True
    stack: str = ""               # "full" 启用全部能力（默认参数），否则逐能力配置
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

```python
@dataclass
class ApprovalConfig:
    enabled: bool = True
    mode: str = "sync_blocking"                    # sync_blocking | async_deferred | notify_only
    policies: list[ApprovalPolicy] = field(default_factory=list)
    approval_id_prefix: str = "approval_"
```

- **挂载**：BEFORE_TOOL / Intercept / priority=100。
- **行为**：任一策略判定需要审批 → 返回 `PauseAction(approval_id, context)`；
  已审批 ID 直接放行（`mark_approved()` 保持 resume 防死循环语义）；
  `notify_only` 模式只记录不暂停。
- **状态**：`_approved_ids`（Hook 实例内，按审批 ID），SESSION_END 不清空（审批 ID 跨会话无效，天然隔离）。
- **异常**：策略抛异常 → 记录 warning 并按"需审批"处理（fail-closed）。
- **测试**：策略各实现、拦截器三种模式、mark_approved、fail-closed、
  Builder 接线、旧 import 兼容。

### 6.2 budget（新增强制）

- **定位**：**执行期预算强制**（token / step / cost 上限）。
  与 `context/_budget.py`（上下文窗口 token 裁剪）职责不同：前者管"这次能不能继续跑"，
  后者管"这次 LLM 看到多少上下文"，互不替代。
- **协议**：`BudgetLimits`。

```python
@dataclass
class BudgetConfig:
    enabled: bool = True
    token_limit: int = 0          # 0 = 不限
    step_limit: int = 0
    cost_limit_cents: int = 0
    block_on_exceed: bool = True  # False = 降级（仅记录并放行一次）
    limits: BudgetLimits | None = None   # 外部来源（可替换）
```

- **挂载**：BEFORE_LLM / Intercept / priority=110。
- **行为**：`ctx.budget` 超限 → `BlockAction(reason)`（或降级模式）；
  记账沿用现有 after_llm 默认 Transform（priority=999，不重复实现）。
- **前置依赖**：cost 维度需要 `LLMUsage` 补 `cost` 字段（决策 D4）。
- **测试**：token / step 超限阻断、降级模式、未超限放行、`BudgetLimits` 替换。

### 6.3 audit（新增）

- **定位**：全链路审计采集与落库（唯一审计出口）。
- **协议**：`AuditSink`。

```python
@dataclass
class AuditConfig:
    enabled: bool = True
    sink: AuditSink | None = None
    include_points: tuple[str, ...] = ()   # 空 = 全部治理相关点
    batch_size: int = 64
    flush_interval_ms: int = 1000
    max_queue: int = 10_000               # 背压上限，超限丢弃并告警
```

- **挂载**：SESSION_START / SESSION_END、BEFORE_LLM、AFTER_LLM、BEFORE_TOOL、AFTER_TOOL、ON_ERROR → Observer（并发执行）。
- **行为**：各点事件标准化为 `GovernanceEvent`，异步缓冲批量写 `AuditSink`；
  SESSION_END 触发 flush；缓冲满时丢弃新事件并告警（不阻塞主流程）。
- **状态**：缓冲队列 + 后台任务（`_background.py`）。
- **测试**：事件标准化、批量 flush、背压丢弃、Sink 异常不影响主流程。

### 6.4 ratelimit（新增）

- **定位**：会话内限流（与网关的请求级限流分工，见 §8）。
- **协议**：`RateLimiter`。

```python
@dataclass
class RateLimitConfig:
    enabled: bool = True
    limit: int = 0                # 窗口内最大 LLM 调用次数，0 = 不限
    window_seconds: int = 60
    limiter: RateLimiter | None = None
```

- **挂载**：BEFORE_LLM / Intercept / priority=100。
- **状态**：按 `session_id` 的滑动窗口计数，SESSION_END 清理。
- **测试**：窗口内超限阻断、窗口过期放行、跨 session 隔离。

### 6.5 critique（真实现）

- **定位**：LLM 输出质量审查（自我批评 / 双模型修正 / 安全拦截）。
- **挂载**：AFTER_LLM / Transform / priority=200（Self / Dual）；
  AFTER_LLM / Intercept / priority=210（Block）。

```python
@dataclass
class CritiqueConfig:
    enabled: bool = True
    mode: str = "self"            # self | dual | block
    max_retries: int = 1          # self 模式（就地重试次数）
    max_rounds: int = 2           # dual 模式（修正轮次）
    critic_executor: Any | None = None   # dual / block 模式的批评模型
    prompt: str = ""
```

- **行为**：
  - SelfCritique：同一 executor 审查，不合格**就地重试**（`max_retries` 上限）；
  - DualModelCritique：critic 审查 → generator 修正（`max_rounds` 上限）；
  - CritiqueInterceptor：不合格直接 `BlockAction`。
- **前置依赖**：重试机制选型见决策 D2（推荐 Transform 内就地重试）。
- **状态**：按 `session_id` 的重试 / 轮次计数，SESSION_END 清理。
- **测试**：合格放行、不合格重试/修正、上限截停、拦截阻断、token 预算联动。

### 6.6 redact（新增）

- **定位**：LLM 输出脱敏。
- **协议**：`RedactPolicy`。

```python
@dataclass
class RedactConfig:
    enabled: bool = True
    policies: list[RedactPolicy] = field(default_factory=list)
```

- **挂载**：AFTER_LLM / Transform / priority=100（在 critique 之前，先脱敏再审查）。
- **行为**：按规则改写 `response.content`（LLMResponse 为可变 dataclass）。
- **测试**：规则命中改写、多规则顺序、空规则放行。

### 6.7 permission（新增）

- **定位**：工具调用权限（白名单 / 黑名单），与 approval 分工：
  approval 管"要不要人批"，permission 管"能不能调"。

```python
@dataclass
class PermissionConfig:
    enabled: bool = True
    allowed_tools: tuple[str, ...] = ()   # 白名单，空 = 不限制
    denied_tools: tuple[str, ...] = ()    # 黑名单优先
```

- **挂载**：BEFORE_TOOL / Intercept / priority=110（approval 之后）。
- **行为**：无权调用 → `BlockAction`。
- **测试**：白名单放行、黑名单阻断、黑名单优先。

### 6.8 error（可选，先记录后强化）

- **定位**：错误分类 / 重试上限 / 降级文案。
- **挂载**：ON_ERROR / Observer。
- **说明**：ON_ERROR 目前只有 Observer，重试循环控制需 Loop 协作；
  本阶段先落地"分类 + 记录"（产出 `GovernanceEvent(type="error")`），重试联动列为后续。

## 7. 协作时序（一次 run()）

```text
run("用户输入")
  │
  ├─ SESSION_START (Transform→Observer)
  │    ├─ (既有) SessionStartHook (10)：加载/创建会话、恢复历史
  │    └─ AuditPlugin (Observer)：session_start 审计
  │
  ├─ BEFORE_STEP (Intercept→Transform→Observer)
  │
  ├─ BEFORE_LLM (Transform→Intercept)
  │    ├─ Transform 段（既有）：tools_schema(100) / skill(200) / context_assembler(300)
  │    └─ Intercept 段（护栏）：ratelimit(100) → budget(110)
  │         ├─ 通过 → 继续
  │         └─ Block → controller.status=ERROR，流程终止
  │
  ├─ LLM 调用（StepRunner）
  │
  ├─ AFTER_LLM (Transform→Intercept→Observer)
  │    ├─ Transform：redact(100) → critique(200) → 默认预算记账(999)
  │    ├─ Intercept：critique_block(210)（可选）
  │    └─ Observer：audit
  │
  ├─ BEFORE_TOOL (Intercept)
  │    ├─ approval(100) → PauseAction（挂起，等待 resume(approval_id)）
  │    └─ permission(110) → BlockAction（无权调用）
  │
  ├─ AFTER_TOOL (Transform→Observer)
  │
  ├─ AFTER_STEP (Transform→Observer)（既有 session_commit(400) / memory_commit(500)）
  │
  └─ SESSION_END (Transform→Observer)
       └─ AuditPlugin flush + 治理实例状态清理
```

## 8. 与网关（接入层）的分工契约

| 层 | 管什么 | 例子 |
|----|--------|------|
| 网关（请求边界） | 每次请求的鉴权、IP / 请求级限流、错误码封装、SSE 协议、会话映射 | 谁在调、调多快、以什么格式回 |
| 护栏（会话内治理） | 预算 / 审批 / 质量 / 脱敏 / 工具权限 / 审计采集 | 这次会话能不能超支、工具要不要人批、输出是否合规 |

- **审计单一出口在护栏**：网关把 `client_ip / route / user` 写入 `ctx.services`（只读注入），
  AuditPlugin 采集时合并进 `GovernanceEvent.data`，网关不双写；
- **审批恢复**：网关的 `POST /approvals/{id}/approve` 映射到 `runtime.resume(approval_id)`；
- **限流分工**：网关管请求级（IP / API Key），护栏管会话内 LLM 调用频率，两者配置独立、可同时启用。

## 9. Builder 接线与配置驱动

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

- `.governance()` 统一入口，逐能力配置；`GovernanceConfig(stack="full")` 一行开启全部能力；
- 注册返回各 hook 的 `handler_id`，供 `enable / disable / replace` 热插拔；
- `RuntimeConfig` 增加 `governance` 段：

```yaml
governance:
  stack: full
  approval:
    mode: sync_blocking
    policies: [deploy, delete_db]     # ToolNamePolicy 快捷语法
  budget:
    token_limit: 100000
    step_limit: 50
  audit:
    sink: my_audit_sink               # 按注册名解析
```

- `from_config` 解析后经 `.governance()` 接线；
- 配置驱动加载涉及插件异步初始化，启动入口见决策 D1（推荐 `runtime.start()`）。

## 10. 兼容与迁移

- `src/runtime/hooks/_approval_hook.py` → **只读重导出** `src.governance.approval` 全部符号；
- `_critique_hook.py` / `_replan_hook.py` 同理（critique 真实现后 shim 指向新实现）；
- `src/runtime/__init__.py` 导出不变（间接保持）；
- 既有测试（`test_hooks_approval.py` 等）不破坏；新增 `tests/test_governance_*.py`；
- 迁移完成后在 `runtime/hooks` 中**禁止新增治理逻辑**（代码评审约束），防止双实现漂移。

## 11. 实施顺序

| 步 | 内容 | 依赖 | 验收 |
|----|------|------|------|
| 1 | 公共底座：`_constants.py` / `_events.py` / `_background.py` + `GovernanceConfig` + Builder `.governance()` 骨架 | 无 | 骨架空转不破坏现有行为 |
| 2 | approval：迁移封装 + shim + 测试 | 1 | 旧 import 兼容 + 新组件测试 |
| 3 | budget：强制上限 + 测试 | 1（cost 依赖 D4） | 超限阻断 / 降级 / 替换协议 |
| 4 | audit：事件采集 + AuditSink + 测试 | 1 | 缓冲 / flush / 背压 / 异常隔离 |
| 5 | ratelimit：滑动窗口 + 测试 | 1 | 窗口限流 / 隔离 / 清理 |
| 6 | critique：真实现 + 测试 | 1（重试选型 D2） | 三种模式 + 上限 + 预算联动 |
| 7 | redact / permission：脱敏与权限 + 测试 | 1 | 规则改写 / 黑白名单 |
| 8 | error：错误分类记录 + 测试 | 1 | 事件产出 + 不阻塞 |

每步完成即：全量测试通过、覆盖率 ≥96%、ruff 零报错、
overview + 自审记录 + README / 本文档同步。

## 12. 验收标准

- 任一治理能力可独立开关（`GovernanceConfig.enabled` / 逐能力配置）；
- 任一能力后端可协议替换（内置默认实现 + 用户实现均可）；
- 全部注册返回 `handler_id`，支持热插拔；
- 旧 import 路径与行为完全兼容；
- 一个示例工程用配置（或一行代码）启用完整治理栈；
- 全量测试 / 覆盖率 / ruff 达标。

## 13. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 审计事件量过大阻塞主流程 | 异步缓冲 + 批量写 + 背压丢弃 + 可配置采样（include_points / batch / flush） |
| Critique 重试 / 修正产生额外 token 成本 | `max_retries` / `max_rounds` 上限；重试仍走 BEFORE_LLM，被 BudgetPlugin 天然覆盖 |
| 治理优先级组合冲突 | `_constants.py` 单一契约 + 文档表格 + Builder 注册重复优先级告警 |
| 异步启动与同步 `build()` 兼容 | D1 推荐 `runtime.start()`；`build()` 保持同步，未 start 时治理不生效且告警 |
| 状态泄漏（SESSION_END 未清理） | SESSION_END Observer 统一清理 + 专项测试 |
| shim 双实现漂移 | 迁移后 `runtime/hooks` 只读重导出，禁止新增逻辑 |
| 预算与 context 预算概念混淆 | §6.2 明确职责边界；命名上区分"执行期预算"与"上下文预算" |
| 审批策略异常导致放行 | fail-closed：策略异常按"需审批"处理 |

## 14. 待确认决策

| 编号 | 决策 | 选项与推荐理由 |
|------|------|---------------|
| D1 | 配置驱动启动入口 | **A：`runtime.start()` 异步挂载（推荐）**——`build()` 保持同步、不破坏现有用法；B：异步 build，API 分叉、迁移成本高 |
| D2 | Critique 重试机制 | **A：Transform 内就地重试（推荐）**——不动 Loop、作用域局部、上限明确；B：`request_retry()` writer + Loop 消费，可见性更好但改动面大。就地重试的 LLM 调用同样走 BEFORE_LLM，预算联动天然成立 |
| D3 | 后台任务组位置 | **A：提升到 `src/runtime/_background.py` 共用（推荐）**——复用优先、避免两份实现漂移；B：governance 内自建一份（自包含但重复） |
| D4 | 预算 cost 维度 | **A：补 `LLMUsage.cost` 字段并强制（推荐）**——全治理要求 cost 上限；Provider 未回报成本时按模型单价估算（可配置估算器）；B：先只做 token / step，cost 留 `BudgetLimits` 接口 |

## 附录 A：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/governance/__init__.py` | 新增 | 惰性导出 |
| `src/governance/_config.py` | 新增 | GovernanceConfig |
| `src/governance/_constants.py` | 新增 | 优先级段位表 |
| `src/governance/_events.py` | 新增 | GovernanceEvent |
| `src/governance/_background.py` | 新增（或复用 runtime 提升版） | 异步任务组 |
| `src/governance/approval/*` | 新增 | 审批组件（迁入 + 配置化） |
| `src/governance/budget/*` | 新增 | 预算强制组件 |
| `src/governance/audit/*` | 新增 | 审计组件 |
| `src/governance/ratelimit/*` | 新增 | 限流组件 |
| `src/governance/critique/*` | 新增 | Critique 真实现 |
| `src/governance/redact/*` | 新增 | 脱敏组件 |
| `src/governance/permission/*` | 新增 | 权限组件 |
| `src/runtime/hooks/_approval_hook.py` 等 | 修改 | 只读重导出 shim |
| `src/runtime/_builder.py` | 修改 | `.governance()` 接线 |
| `src/runtime/config/_runtime_config.py` | 修改 | `governance` 配置段 |
| `src/runtime/llm/_models.py` | 修改（D4=A 时） | `LLMUsage.cost` 字段 |
| `src/runtime/_background.py` | 新增（D3=A 时） | 公共异步任务组 |
| `tests/test_governance_*.py` | 新增 | 各能力 + Builder 接线测试 |

## 附录 B：修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-08-16 | 初稿：组件域与分阶段封装框架 |
| v0.2 | 2026-08-16 | 落实版：补齐职责边界（R7）、零耦合依赖矩阵与验证清单（§3）、原语链执行语义（§5.2）、完整组件规格（§6）、协作时序（§7）、与网关分工（§8）、配置 YAML（§9）、风险表（§13）、决策分析（§14） |