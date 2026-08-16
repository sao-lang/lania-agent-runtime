# Session 组件技术方案（v2：唯一事实源 + 零耦合）

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的 **Runtime 核心状态**（§3）、**RuntimeContext**（§4）和 **Hook 治理组件 #16 Session**（`session_start` / `session_end` Transform）。
>
> 关联文档：
> - [`context-management-redesign.md`](context-management-redesign.md) — ContextManager 五阶段管线
> - [`memory-system-design.md`](memory-system-design.md) — MemoryService 五层记忆

> **v2 修订要点**：
> 1. 明确三组件边界：**Session 是完整对话消息历史的唯一事实源**（不含 system，system prompt 属运行时配置，见 §16），Memory L1/L2 不再存储消息原文，Context 保持纯编排、不持有数据；
> 2. 新增**零耦合约束**：组件间运行期零导入，跨组件数据只经 RuntimeContext / Builder 传递，唯一接线点在 `RuntimeBuilder`；
> 3. 修正 v1 审查发现的问题：`ctx.services` 浅拷贝不可写、session_id 无注入入口、续聊 turn_index 重置、TTL 不生效等。

---

## 0. 三组件职责总览

| 组件 | 回答的问题 | 职责 | 持有数据 | 生命周期 |
|------|-----------|------|---------|---------|
| **Session** | 这次会话是什么？ | 会话身份、生命周期、完整历史归档 | 会话元数据 + 完整对话消息历史（唯一事实源，不含 system） | 长期 |
| **Memory** | 记住了什么？执行到哪了？ | 执行断点快照 + 五层记忆沉淀 | 执行状态游标（不含消息原文）+ 摘要/画像/概念/模式 | L1 短期、L2-L5 长期 |
| **Context** | LLM 这次看到什么？ | 上下文编排（选取/压缩/预算/序列化） | 不持有任何持久化数据 | 每次 LLM 调用 |

三者正交，数据流单向：`Session 提供历史与身份 → Runtime 注入 ctx → Context 编排（读 ctx + Memory 召回）→ LLM`；
`AFTER_STEP：Session 提交原文、Memory 沉淀摘要`；`SESSION_END：Session 归档元数据`。

---

## 1. 现状与痛点

| 现状 | 问题 |
|------|------|
| `AgentRuntime.__init__` 生成 `session_id = sess_{uuid}`，仅存于内存 | 进程重启后会话丢失，无法续聊、无法审计 |
| `ctx.messages` 持有完整消息，只存在于 Runtime 实例 | 会话结束后完整历史无法查询 |
| `WorkingMemorySnapshot` 存完整 messages（`wm:` 键），仅用于暂停/崩溃恢复 | 与"会话完整历史"职责重叠，且 TTL 1h 不具备归档能力 |
| `EpisodicMemoryEntry.raw_content` 存每轮原文（16KB 截断） | 与 Session 历史重叠，且不完整（Gate 会跳过低价值轮次） |
| `ContextConfig.cross_session_memory=True` 只是配置项 | 缺"会话"实体支撑；实际跨会话检索可复用现有 `ep_user:` 索引 |
| `SessionSnapshot` 仅用于调试/监控 | 无标题、用户、状态、token 等持久化元数据 |

---

## 2. 设计目标

### 2.1 原则

| 原则 | 含义 |
|------|------|
| **唯一事实源** | 每类数据只有一个写者：完整消息原文只归 Session，Memory 只存摘要/画像/知识/模式与执行游标，Context 不持有数据 |
| **零耦合** | 运行期组件间零导入；跨组件数据只经 RuntimeContext / Builder 传递；唯一接线点在 `RuntimeBuilder` |
| **复用持久化契约** | `SessionPersistence` 与 `MemoryPersistence` 同为 4 方法 KV 接口，可共用同一后端实例（依赖注入，非耦合） |
| **生命周期完整** | start → 多轮 step（逐轮提交对话消息）→ end / resume 全覆盖 |
| **只增不改** | 已有组件行为不变；Memory 侧仅"废弃字段、停止写入"（标记 `@deprecated v2`），Runtime 仅新增受限 writer 与 SESSION 挂载点执行顺序调整 |

### 2.2 职责边界与唯一事实源

| 数据 | 唯一写者 | 读者 | 存储键 |
|------|---------|------|--------|
| 会话元数据（title/user/status/统计） | Session | 宿主应用、Session 自身 | `ss:` |
| 完整对话消息历史（user/assistant/tool，不含 system） | Session（AFTER_STEP 逐轮提交） | Session（恢复）、宿主（审计/UI） | `ss:` |
| 执行状态快照（游标，不含消息原文） | Memory L1（pause/error/checkpoint） | Memory（恢复）、宿主 | `wm:` |
| 情景摘要 / 实体画像 / 语义概念 / 行为模式 | Memory L2-L5（AFTER_STEP） | Context（LOAD 阶段） | `ep:` `en:` `sn:` `bp:` |
| llm_messages | Context（BEFORE_LLM） | LLM Executor | 无（内存） |

### 2.3 易混淆职责的归属裁定

以下点最容易误判为"重叠"，逐一定裁（实现与 Code Review 均以此表为准）：

| 容易混淆的点 | 归属裁定 |
|-------------|---------|
| 完整消息原文 | 只归 Session（`ss:`）。Memory 的 `wm:` / `ep:` 不存原文（v2 废弃） |
| 轮次/步进游标 | 权威来源是 Session 的 `step_index`（恢复时经 `set_step_index()` 写回 Runtime）；Memory 的 `turn_index` 只是提交时继承 `ctx.step_index` 的**存储字段**，不自行维护轮次 |
| token 用量 | Runtime 实时计量（`budget.token_used`）；Session 在 finalize 时**读取快照**归档统计；wm 保留执行预算。同一来源、不同用途，不是双份维护 |
| user_id | 宿主注入 `ctx.services`；Session 记录会话↔用户映射（`ssi:` 索引）；Memory / Context 仅作为检索维度消费，不维护映射 |
| 历史注入 vs 上下文选取 | Session 负责"恢复历史进 ctx.messages"；Context 负责"决定 LLM 看到多少"（SELECT 裁剪）。输入输出不同，不重叠 |
| system prompt | 唯一归属是运行时配置（`AgentRuntime` 构造时写入 `ContextPayload`）；Session 不存、Context 组装时注入（详见 §16） |
| 摘要去重 | `Selector` 的 `dedup_turn_indices` 是防御性机制（防同一轮"原文 + 摘要"双份进 prompt），不是记忆管理职责 |
| 断点恢复编排 | Session 恢复历史（消息 + 游标）、Memory 恢复执行状态（plan/budget/pause）；组合只发生在 Builder，组件内部不互相调用 |

### 2.4 非目标

- 不替代 Memory 的五层记忆（摘要/画像/知识/模式仍归 Memory）
- 不做 RAG / 向量库
- 不做多 Agent 会话编排（Phase 3 可扩展）

---

## 3. 零耦合约束

> **零耦合的定义范围**：本设计中的"0耦合"指 **Session / Memory / Context 三个组件之间**——运行期零导入、零直接调用，跨组件数据只经 RuntimeContext / Builder 传递。Runtime 是公共底座（Hook 机制、RuntimeContext、ContextPayload），组件对 Runtime 的单向依赖（如 Hook 签名）不属于组件间耦合，允许且必要。

### 3.1 依赖矩阵

| 依赖方向 | 允许 | 说明 |
|----------|------|------|
| `src/session` → `src/memory` / `src/context` | ❌ 禁止 | 运行期与 TYPE_CHECKING 均禁止 |
| `src/session` → `src/runtime` | ⚠️ 仅类型 | `RuntimeContext` / `Event` 仅在 TYPE_CHECKING 下引用（与 `context_hooks/_assembler_hook.py` 现状一致），运行期零导入 |
| `src/memory` → `src/context` / `src/session` | ❌ 禁止 | 现状已满足 |
| `src/context` → `src/memory` | ⚠️ 仅协议 | `MemoryRecallProtocol`（现状，保持） |
| `src/context` → `src/session` | ❌ 禁止 | 新增约束 |
| 组件 → `RuntimeBuilder` | ✅ 允许 | 唯一接线点 |

### 3.2 数据交换规则

- **Session ↔ Memory 不直接调用**：Session hooks 只依赖 `SessionServiceProtocol`；Memory hooks 只依赖 Memory 侧协议；断点恢复的编排发生在 Builder/宿主，两者并列注册、互不感知。
- **Session → Runtime**：恢复历史通过 `RuntimeContext.set_messages()` / `set_step_index()`（Runtime 机制，Session 不 import Runtime 实现）。
- **Memory → Context**：`ContextManager` 通过 `MemoryRecallProtocol.recall_raw()` 读取，`session_id` / `user_id` 由 `RuntimeContext` 注入。
- **Context → LLM**：`llm_messages` 经 BEFORE_LLM Transform 传递。

### 3.3 共享后端 ≠ 耦合

`SessionService` 与 `MemoryService` 可以注入**同一个 persistence 实例**（如 `SQLitePersistence("./runtime.db")`）。这是依赖注入的基础设施复用：两个组件按各自的 key 前缀（`ss:` vs `wm:`/`ep:`）隔离读写，互不感知对方的数据结构与键名，因此不构成组件耦合。

### 3.4 零耦合验证清单（实现时逐条验证）

- [x] `src/session` 中无 `import src.memory` / `import src.context`（含 TYPE_CHECKING 块）
- [x] `src/session` 对 `src.runtime` 的 import 仅存在于 TYPE_CHECKING 块
- [x] `src/memory`、`src/context` 中无 `import src.session`
- [x] Session 各 hook 不调用 `MemoryService`；Memory 各 hook 不调用 `SessionService`
- [x] 跨组件数据只经 `RuntimeContext` / `RuntimeBuilder` 传递
- [ ] 断点/历史恢复由 Builder 并列注册完成，组件内部无互相调用（Phase 2：`SessionResumeHook` + `MemoryResumeHook` 待实现；Phase 1 的 `SessionStartHook` 恢复历史/游标已由 Builder 注册）

### 3.5 禁止清单（违反即视为耦合或重叠）

- [ ] `src/session` 中出现 `import src.memory` 或 `import src.context`（含 TYPE_CHECKING 块）
- [ ] Session hooks 调用 `MemoryService.*`；Memory hooks 调用 `SessionService.*`
- [ ] `src/session` 直接读写 `wm:` / `ep:` / `en:` / `sn:` / `bp:` 前缀的键
- [ ] Memory / Context 直接读写 `ss:` / `ssi:` 前缀的键
- [ ] 组件间通过 `ctx.services` 传递共享可变状态（services 为浅拷贝，禁止跨组件状态共享）
- [ ] 同一数据存在两个写者（完整消息原文、会话元数据、执行状态快照）
- [ ] Context / Memory 自行维护轮次游标（步进游标唯一权威是 Session）

---

## 4. 目录结构

```
src/
  ├── session/
  │   ├── __init__.py           # 导出 SessionService / SessionRecord / SessionPersistence / hooks
  │   ├── _models.py            # SessionRecord / SessionSummary
  │   ├── _persistence.py       # SessionPersistence ABC（get/put/delete/list_keys）
  │   ├── _store.py             # SessionStore（key 约定 + JSON 序列化 + TTL 过期）
  │   ├── _service.py           # SessionService 外观（含内存缓存）
  │   ├── _config.py            # SessionConfig
  │   ├── _protocols.py         # SessionServiceProtocol（hook 依赖）
  │   ├── _backends/
  │   │   ├── __init__.py
  │   │   └── _sqlite.py        # SQLite 后端（可选；也可直接复用 memory 的 SQLitePersistence）
  │   └── _hooks/
  │       ├── __init__.py
  │       ├── _start.py         # SessionStartHook   (SESSION_START Transform)
  │       ├── _commit.py        # SessionCommitHook  (AFTER_STEP Transform，逐轮提交对话消息，不含 system)
  │       ├── _end.py           # SessionEndHook     (SESSION_END Transform)
  │       └── _resume.py        # SessionResumeHook  (SESSION_RESUME Transform，Phase 2)
```

---

## 5. 数据模型

`src/session/_models.py`：

```python
@dataclass
class SessionRecord:
    """会话记录——会话元数据 + 完整对话消息历史（唯一事实源，不含 system）。

    Attributes:
        session_id: 主键，与 Runtime.session_id 一致。
        agent_id: 所属 Agent。
        user_id: 关联用户。
        title: 会话标题。
        status: active | paused | ended | error | cancelled。
        created_at / updated_at / ended_at: 生命周期时间戳。
        turn_count / message_count / step_count / token_used: 统计。
        step_index: 已提交的 step 游标（续聊时用于 turn_index 对齐）。
        last_error: 最后错误信息。
        metadata: 外部扩展字段。
        messages: 完整对话消息历史（user/assistant/tool，不含 system；system
            prompt 属运行时配置，Session 不保存）。Session 独有，其它组件不存原文。
        version: 数据格式版本号。
        ttl: 过期秒数，0 = 永久。
    """

    session_id: str = ""
    agent_id: str = ""
    user_id: str | None = None
    title: str = ""
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    ended_at: datetime | None = None
    turn_count: int = 0
    message_count: int = 0
    step_count: int = 0
    step_index: int = 0
    token_used: int = 0
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)
    version: int = 1
    ttl: int = 0


@dataclass
class SessionSummary:
    """会话摘要——列表展示用，不含 messages。"""

    session_id: str = ""
    title: str = ""
    status: str = ""
    user_id: str | None = None
    turn_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

> **step_index 的作用**：续聊时新 Runtime 的 step_index 从 0 开始，若直接写入情景记忆会与旧历史的 turn_index 冲突。Session 持久化 `step_index` 并在启动时经 `set_step_index()` 恢复，保证续聊后的提交从正确的轮次继续。

---

## 6. 持久化接口与 key 约定

`src/session/_persistence.py` 定义 `SessionPersistence` ABC，与 `MemoryPersistence` 完全同构（4 个方法），因此任何已实现 `MemoryPersistence` 的实例（如 `SQLitePersistence`）天然满足 `SessionPersistence`：

```python
class SessionPersistence(ABC):
    """会话持久化后端接口——SessionStore 内部使用。"""

    @abstractmethod
    async def get(self, key: str) -> bytes | None: ...

    @abstractmethod
    async def put(self, key: str, value: bytes) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def list_keys(self, prefix: str) -> list[str]: ...
```

key 约定（与 memory 的 `wm:` / `ep:` 前缀并列，互不冲突）：

| 前缀 | 含义 |
|------|------|
| `ss:{session_id}` | SessionRecord（JSON 序列化，含完整消息历史） |
| `ssi:{user_id}:{session_id}` | 用户 → 会话索引，值只存存在标记（查询时回读 `ss:` 记录，避免摘要过期） |
| `ssh:{session_id}:{chunk_index}` | 历史分块（Phase 2，消息超阈值时启用） |

> **注意**：`wm:`（Memory L1）与 `ep:`（Memory L2）**不再存储消息原文**（见 §9），消息原文的唯一存储位置是 `ss:`。

---

## 7. SessionService

`src/session/_service.py` —— 会话统一外观，上层只感知这一个入口：

```python
class SessionService:
    """会话统一外观——管理会话生命周期、元数据与完整消息历史。"""

    def __init__(
        self,
        persistence: SessionPersistence,
        config: SessionConfig | None = None,
    ) -> None:
        """初始化；内部维护 session_id → SessionRecord 内存缓存。"""
        ...

    async def create(
        self,
        session_id: str,
        *,
        agent_id: str = "",
        user_id: str | None = None,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionRecord:
        """创建会话（幂等：已存在则返回现有记录，支持 resume 场景）。"""
        ...

    async def get(self, session_id: str) -> SessionRecord | None:
        """读取会话记录（内存缓存优先，含 TTL 过期检查）。"""
        ...

    async def list_user_sessions(
        self,
        user_id: str,
        *,
        limit: int = 20,
        status: str | None = None,
    ) -> list[SessionSummary]:
        """列出用户的会话摘要（按 updated_at 倒序，回读 ss: 记录组装）。"""
        ...

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict],
        *,
        step_index: int | None = None,
    ) -> SessionRecord | None:
        """增量提交消息：以 record.message_count 为基准只追加新消息（幂等）。

        超过 config.max_history_messages 时裁掉最旧消息；单条消息超过
        config.max_message_chars 时截断。step_index 用于续聊时对齐游标。
        """
        ...

    async def update_status(
        self,
        session_id: str,
        status: str,
        *,
        last_error: str | None = None,
    ) -> SessionRecord | None:
        """更新会话状态（paused / error / cancelled 等）。"""
        ...

    async def finalize(
        self,
        session_id: str,
        *,
        status: str = "ended",
        token_used: int = 0,
        step_count: int = 0,
        last_error: str | None = None,
    ) -> SessionRecord | None:
        """结束会话：更新状态/统计，标记 ended_at（消息已在 step 间提交）。"""
        ...

    async def delete(self, session_id: str) -> None:
        """删除会话记录（含用户索引）。"""
        ...

    async def close(self) -> None:
        """关闭持久化后端。"""
        ...
```

要点：

- **内存缓存**：`SessionStartHook` 创建/加载后写入缓存，其它 hook 与宿主通过 `service.get()` 读取——不依赖 `ctx.services`（v1 的 `ctx.services["session_record"] = ...` 会因 services 浅拷贝而丢失，已废弃）。
- **逐轮提交**：`append_messages()` 由 `SessionCommitHook` 在 AFTER_STEP 调用，以 `message_count` 为基准增量追加，保证任何时刻 `ss:` 都包含"最后提交轮次"的完整消息（崩溃/续聊的恢复基准）；重复调用不重复写入。
- **TTL 自管**：`SessionService` 在 `get()` / `list_user_sessions()` 时自行检查 `record.ttl` 过期（不依赖 persistence 的默认 TTL 配置）。
- **索引只存标记**：`ssi:` 值不存摘要，`list_user_sessions()` 回读 `ss:` 记录组装 `SessionSummary`。
- 容错：序列化/后端异常时记录 warning 并静默降级，不阻塞主流程（与 `MemoryCommitHook` 一致）。

---

## 8. Hooks

Hooks 只依赖 `SessionServiceProtocol`（`src/session/_protocols.py` 定义，方法签名与 SessionService 一致，返回类型用 `Any`），运行期不 import 任何其它组件；`RuntimeContext` / `Event` 仅在 TYPE_CHECKING 下引用。

### 8.1 SessionStartHook（SESSION_START Transform，priority=10）

```python
class SessionStartHook:
    """session_start Transform：加载或创建会话，恢复历史消息与 step 游标。"""

    def __init__(
        self,
        service: SessionServiceProtocol,
        config: SessionConfig | None = None,
    ) -> None: ...

    async def __call__(self, data: Event, ctx: RuntimeContext) -> Event:
        record = await self._service.get(ctx.session_id)
        if record is None:
            record = await self._service.create(
                ctx.session_id,
                agent_id=ctx.agent_id,
                user_id=ctx.services.get(self._config.user_id_key),
                title=(
                    (data.get("input") or "").strip()[:30]
                    if self._config.auto_title
                    else ""
                ),
            )
        if record.messages and self._config.persist_messages:
            ctx.set_messages(record.messages)      # Runtime 受限 writer：恢复历史
            ctx.set_step_index(record.step_index)  # Runtime 受限 writer：对齐续聊游标
        return data
```

> **注意**：hook 不写 `ctx.services`（浅拷贝不可见）；后续 hook 需要会话信息时通过 `service.get(ctx.session_id)` 读取。

### 8.2 SessionCommitHook（AFTER_STEP Transform，priority=400）

```python
class SessionCommitHook:
    """after_step Transform：把本轮消息增量提交到会话历史（唯一事实源）。"""

    def __init__(
        self,
        service: SessionServiceProtocol,
        config: SessionConfig | None = None,
    ) -> None: ...

    async def __call__(self, data: Event, ctx: RuntimeContext) -> Event:
        if not self._config.persist_messages:
            return data
        await self._service.append_messages(ctx.session_id, list(ctx.messages))
        return data
```

> 与 `MemoryCommitHook`（priority=500）的关系：Session 先提交原文，Memory 后沉淀摘要——两者互不调用，仅由 Builder 按优先级并列注册。

> **存储约定（v2.1）**：`append_messages()` 在服务层过滤 `role == "system"` 的消息——
> system prompt 的唯一归属是运行时配置（`ContextPayload`），不入会话历史。
> 旧格式记录（v2 前首条为 system）在下次提交时自动剥离自愈，无需迁移。
> 恢复历史后由 `ContextAssemblerHook` 用运行时 `system_prompt` 组装（详见 §16）。

### 8.3 SessionEndHook（SESSION_END Transform，priority=10）

```python
class SessionEndHook:
    """session_end Transform：归档元数据与统计（消息已在 step 间提交）。"""

    def __init__(self, service: SessionServiceProtocol) -> None: ...

    async def __call__(self, data: Event, ctx: RuntimeContext) -> Event:
        await self._service.finalize(
            ctx.session_id,
            status=data.get("status", "ended"),
            token_used=ctx.budget.token_used,
            step_count=ctx.step_index,
            last_error=data.get("last_error"),
        )
        return data
```

### 8.4 SessionResumeHook（SESSION_RESUME Transform，Phase 2）

- 恢复 `ss:` 中的历史消息与 `step_index`（`set_messages` + `set_step_index`）
- **不调用 MemoryService**：执行断点（plan/budget/pause）的恢复由 Memory 侧 `MemoryResumeHook` 负责，Builder 并列注册两者

---

## 9. Memory 侧配合改动（消除重叠所必需）

目标：Memory 不再存储消息原文，确保"完整历史"只有 Session 一个写者。

| 改动 | 现状 | v2 目标 |
|------|------|---------|
| `WorkingMemorySnapshot.messages` | 存完整 messages 数组 | `@deprecated v2`：保留字段但**不再写入**；wm 只存执行状态 + 游标（session_id / step_index / plan / budget / pause / error / hook_states） |
| `EpisodicMemoryEntry.raw_content` | 存每轮原文（16KB 截断） | `@deprecated v2`：**不再写入**；情景记忆只存 summary + 标签 + importance |
| `MemoryCommitHook` | 写 summary + raw_content | 只写 summary（不写原文） |
| 断点恢复 | `MemoryService.restore()` 返回含 messages 的快照 | 恢复时消息由 Session 提供；wm 只负责执行状态与游标 |

新增（Phase 2）：

```python
class MemoryResumeHook:
    """session_resume Transform（Memory 侧）：恢复执行断点。

    与 SessionResumeHook 并列注册于 Builder，互不调用。
    """
```

**恢复语义**：恢复点 = Session 最后提交的轮次；未提交的失败轮次不恢复（由用户重发）。wm 快照仅在 step 边界（pause / error / checkpoint）触发，此时 Session 已完成本轮提交，两者一致。

---

## 10. Context 侧无改动

- Context 不新增任何存储/生命周期职责，保持纯编排。
- `ContextManager` 的 SELECT 阶段已有 `dedup_turn_indices` 去重：当 Session 恢复了原始历史、Memory 又召回了同轮摘要时，防止双份进 prompt。这是**防御性机制**，不是功能重叠，予以保留。
- 跨会话检索（Phase 3）：`ContextManager` 消费 `ContextConfig.cross_session_memory` 后调用 `recall_raw()`，Memory 侧复用现有 `ep_user:` 索引与 `EpisodicMemoryStore.recall_user()`，不新造机制。

---

## 11. Runtime 最小变更

### 11.1 AgentRuntime 支持注入 session_id

```python
def __init__(self, *, ..., session_id: str = "") -> None:
    self.session_id: str = session_id or f"sess_{uuid.uuid4().hex[:12]}"
```

Builder 增加 `.session_id("...")`，宿主在续聊/审计场景显式传入已有会话 ID。

### 11.2 RuntimeContext 增加受限 writer

与 `set_plan` / `deduct_budget` / `update_context_payload` 同一模式：

```python
@dataclass(frozen=True)
class RuntimeContext:
    ...
    _set_messages_callback: Callable[[list[dict]], None] | None = field(
        default=None, repr=False
    )
    _set_step_index_callback: Callable[[int], None] | None = field(
        default=None, repr=False
    )

    def set_messages(self, messages: list[dict]) -> None:
        """恢复会话历史（仅 SessionStartHook / SessionResumeHook 使用）。"""
        ...

    def set_step_index(self, step_index: int) -> None:
        """恢复 step 游标（仅 SessionStartHook / SessionResumeHook 使用）。"""
        ...
```

`_build_context()` 传入对应实现（整体替换 `self._messages` / `self._step_index`）。

### 11.3 SESSION 挂载点先 Transform 后 Observer

`run()` / `run_stream()` / `resume()` 中：

```python
event = await self._hooks.run_transformers(HookPoint.SESSION_START, event, ctx)
await self._hooks.run_observers(HookPoint.SESSION_START, event, ctx)
```

SESSION_END / SESSION_RESUME 同理；`session_end` 事件补充 `last_error` 字段：

```python
{"type": "session_end", "status": self.status, "last_error": self._error_state["last_error"]}
```

未注册任何 Transform 时行为不变，向后兼容。

---

## 12. Builder 集成（唯一接线点）

```python
from src.memory import MemoryService
from src.memory._backends._sqlite import SQLitePersistence
from src.session import SessionConfig, SessionService

backend = SQLitePersistence("./runtime.db")  # 共享基础设施，非耦合

runtime = (
    AgentRuntime.builder()
    .system_prompt("你是助手")
    .session_id("sess_abc")                # 可选：续聊/审计时注入已有会话
    .session(SessionService(backend, config=SessionConfig()))
    .memory(MemoryService(backend))
    .context(config=ContextConfig())
    .build()
)
```

build() 内部注册（priority 为执行顺序）：

| Hook | 挂载点 | priority | 归属 |
|------|--------|----------|------|
| `_session_start` | SESSION_START | 10 | Session |
| `_session_end` | SESSION_END | 10 | Session |
| `_session_commit` | AFTER_STEP | 400 | Session |
| `_memory_commit` | AFTER_STEP | 500 | Memory |
| `_context_assembler` | BEFORE_LLM | 300 | Context |

> **断点恢复编排**：Phase 2 时 Builder 并列注册 `SessionResumeHook`（历史）与 `MemoryResumeHook`（执行断点），两者互不感知，组合只发生在接线点。

---

## 13. 配置 SessionConfig

```python
@dataclass
class SessionConfig:
    """会话组件配置。"""

    enabled: bool = True            # 总开关
    persist_messages: bool = True   # 是否持久化完整消息历史（续聊/恢复依赖此开关）
    max_history_messages: int = 200  # 历史消息上限（超出裁最旧）
    max_message_chars: int = 16384  # 单条消息截断长度
    auto_title: bool = True         # 用首条用户消息生成标题（strip 后截断 30 字符）
    ttl_seconds: int = 0            # 0 = 永久；由 SessionService 内置过期检查
    user_id_key: str = "user_id"    # ctx.services 中取 user_id 的键名
```

> **注意**：`persist_messages=False` 时会话只存元数据，**续聊/断点恢复不可用**（历史消息无来源）；此开关面向"只做审计元数据"的轻量场景。

---

## 14. 协作时序

```
SESSION_START (Transform)
  └─ SessionStartHook：加载/创建记录 → set_messages(历史) + set_step_index(游标)
      （不调用 Memory / Context）
BEFORE_LLM
  └─ ContextAssemblerHook → ContextManager.assemble(ctx)
       ├─ SELECT   从 ctx.messages（含恢复的历史）滑动窗口
       ├─ LOAD     MemoryRecallProtocol.recall_raw(session_id, user_id, query)
       └─ COMPRESS / BUDGET / SERIALIZE → llm_messages
AFTER_STEP
  ├─ SessionCommitHook（priority 400）：append_messages → ss:（原文唯一事实源）
  └─ MemoryCommitHook（priority 500）：摘要 → ep:（不写原文）
SESSION_END (Transform)
  └─ SessionEndHook：finalize 元数据 + 统计（last_error 来自事件）
恢复场景（Phase 2）
SESSION_RESUME (Transform)
  ├─ SessionResumeHook：ss: → set_messages + set_step_index
  └─ MemoryResumeHook：wm: → 恢复 plan / budget / pause_state（不存消息）
```

---

## 15. 迁移路径

### Phase 1 — 基础

> ✅ **Phase 1 已实现**（2026-08-15）。实现时补充的两处细节：
> - `append_messages()` 增加可选 `step_index` 参数，`SessionCommitHook` 传入 `ctx.step_index`，
>   保证续聊时持久化游标（对应 v2 修复"续聊 turn_index 重置"）。
> - `_backends/_sqlite.py` 未单独实现：按 §3.3 约定直接复用 memory 的 `SQLitePersistence`
>   （满足 `SessionPersistence` 4 方法契约，依赖注入、非耦合），由 Builder 接线。

1. [x] 新建 `src/session/`：models / persistence / store / service / config / protocols
2. [x] 实现 SessionStartHook / SessionCommitHook / SessionEndHook
3. [x] Runtime 最小变更：session_id 注入、`set_messages` / `set_step_index` writer、SESSION 挂载点先跑 Transform、session_end 事件带 last_error
4. [x] Builder 增加 `.session()` / `.session_id()`
5. [x] Memory 侧字段废弃：`WorkingMemorySnapshot.messages`、`EpisodicMemoryEntry.raw_content` 标记 `@deprecated v2`，`MemoryCommitHook` 停止写原文
6. [x] 单元测试（store 增删改查、service 生命周期、TTL、hook 恢复/提交/归档）+ 端到端测试（Session → Runtime → Memory → Session 全链路）
7. [x] 零耦合验证清单逐条核对（§3.4）

> **顺带修复**：实现中发现 AFTER_STEP 的 `ctx` 是步骤执行前的快照，导致 Session/Memory
> 提交看不到本轮 assistant 回复——已在 ReAct / PlanExecute / Workflow 三种 Loop 与
> `run_step()` 中统一在步后重建 ctx；并修复 ContextAssemblerHook 组装路径丢失
> Runtime `system_prompt` 的问题。
>
> **v2.1 修订**：system prompt 唯一归属运行时配置、Session 历史不含 system，
> 执行器经重建 ctx 收到序列化/组装后的完整消息（详见 §16）。

### Phase 2 — 增强

> ✅ **Phase 2 已实现**（2026-08-16）。实现细节：
> - RuntimeContext 新增 `set_budget` / `set_pause_state` 受限 writer（Memory 侧恢复断点用）；
> - `ssh:` 分块存储由 `SessionStore` 统一处理（`chunk_size` 阈值，超阈值分块、重读重组、切换布局清理残留）。

1. [x] SessionResumeHook + MemoryResumeHook（Builder 并列注册）
2. [x] 消息分块（`ssh:` 前缀）与历史裁剪策略
3. [x] `list_user_sessions` 分页 / 状态过滤

### Phase 3 — 高级

1. 跨会话检索打通：`ContextManager` 消费 `cross_session_memory`，Memory 复用 `ep_user:` / `recall_user()`
2. 会话级权限 / 审计 / 脱敏（与治理 Hook 组合）
3. 多 Agent 会话（父会话 → 子会话）

---

## 16. system prompt 归属与执行器消息传递（v2.1 修订）

### 16.1 背景

v2 Phase 1 实现后审查发现两个问题：

1. **system prompt 归属不清**：StepRunner 序列化后把 system 消息写回 `controller.messages`，
   Session 逐轮提交时把 system 一并存入 `ss:`。续聊恢复历史后，
   `Compressor._get_system_prompt()` 直接把历史首条 system 当作提示词——
   同一 `session_id` 更换 `system_prompt` 时，旧提示词仍然生效（静默错误）。
2. **执行器收不到组装结果**：StepRunner 把序列化/组装后的 messages 写进
   `controller.messages`，但调用 `executor.execute(ctx)` 时传的是**步前快照 ctx**——
   实际发给 LLM 的消息既可能缺 system，也可能缺最新轮次。
   这与 `LLMExecutor` 接口文档"`ctx.messages` 已序列化、`[0]` 为 system message"的契约不符。

### 16.2 设计裁定

| 数据 | 归属 |
|------|------|
| system prompt | 运行时配置（`AgentRuntime` 构造时写入 `ContextPayload`），唯一权威来源 |
| 会话历史 | Session 只存 user/assistant/tool 对话消息，**不含 system** |

### 16.3 机制（两层修复）

**L1：执行器消息传递（StepRunner）**

- 序列化/组装完成、写入 `controller.messages` 后**重建 ctx 再调用执行器**
  （`fresh_ctx = controller.build_context()`），确保执行器收到 `[system, ...]` 完整消息；
- dirty 序列化路径的 `[serialized[0]] + controller.messages[1:]` 改为条件分支：
  历史首条是 system 时替换（保持旧语义）；否则前置新 system
  （Session 恢复的纯对话历史首条为 user，不能被丢弃）。

**L2：Session 不存 system**

- `SessionService.append_messages()` 存储层过滤 `role == "system"`；
- 旧格式记录（v2 前首条为 system）在提交时剥离首条 system 自愈，无需迁移脚本；
- 恢复历史后 `Compressor` 推导不出 system → `ContextAssemblerHook` 用运行时
  `system_prompt` 兜底填充 → 续聊更换提示词立即生效。

### 16.4 迁移与边界

- 无 schema / API 变更；旧记录首次提交自动自愈；
- 过渡行为：升级后**第一次**续聊旧会话仍可能沿用历史中的旧 system（该次运行提交后自愈）；
- 执行器入参变化属于契约修正（与 `LLMExecutor` 接口文档对齐），
  第三方自定义执行器若依赖旧行为（收到步前快照）需要适配。

---

## 附录：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `session/__init__.py` | 新增 | 导出公共 API |
| `session/_models.py` | 新增 | SessionRecord / SessionSummary |
| `session/_persistence.py` | 新增 | SessionPersistence ABC |
| `session/_store.py` | 新增 | key 约定 + 序列化 + TTL 过期 |
| `session/_service.py` | 新增 | 会话生命周期管理（含内存缓存） |
| `session/_config.py` | 新增 | 配置 |
| `session/_protocols.py` | 新增 | SessionServiceProtocol |
| `session/_backends/_sqlite.py` | 新增 | SQLite 后端（或复用 memory 的） |
| `session/_hooks/_start.py` | 新增 | SESSION_START Transform |
| `session/_hooks/_commit.py` | 新增 | AFTER_STEP Transform（逐轮提交） |
| `session/_hooks/_end.py` | 新增 | SESSION_END Transform |
| `session/_hooks/_resume.py` | 新增 | SESSION_RESUME Transform（Phase 2） |
| `runtime/_runtime.py` | 修改 | + session_id 注入；SESSION 挂载点先跑 Transform；session_end 事件带 last_error |
| `runtime/_helper_mixin.py` | 修改 | _build_context 传 set_messages / set_step_index writer |
| `runtime/context/_context.py` | 修改 | + set_messages / set_step_index |
| `runtime/_builder.py` | 修改 | + `.session()` / `.session_id()` |
| `memory/_types.py` | 修改 | WorkingMemorySnapshot.messages / EpisodicMemoryEntry.raw_content 标记 @deprecated v2 |
| `memory/_hooks/_commit.py` | 修改 | 停止写 raw_content |
| `memory/_hooks/_resume.py` | 新增（Phase 2） | 执行断点恢复（Memory 侧） |
| `pyproject.toml` | 修改 | wheel packages 增加 `src/session`（顺带修复打包） |
