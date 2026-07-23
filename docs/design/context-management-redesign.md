# ContextManager 技术方案

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的 **ContextPayload**（§5）、**Hook Point**（§1）和 **RuntimeContext**（§4）设计。
>
> 关联文档：[`serializer-design.md`](serializer-design.md) — Serializer 可替换接口定义
> 关联文档：[`memory-system-design.md`](memory-system-design.md) — MemoryService 数据来源
> 主文档：[`agent-runtime-design.md`](agent-runtime-design.md) — §6.5 `Pipeline[T]` 是本管线的通用抽象

> 在现有 Hook + Memory 体系上封装统一上下文管理层，实现选取→压缩→预算→序列化四阶段管线。

---

## 编码规范

本文档涉及的所有代码实现必须遵循以下质量要求：

### 注释
- 所有公共接口和方法必须包含完整的**中文 docstring**，说明用途、参数、返回值、异常
- 复杂逻辑（>10 行）必须添加行内中文注释
- 每个模块文件头部必须包含模块级别的中文注释说明职责

### 测试
- 完整的**单元测试**（覆盖 Selector / Compressor / BudgetController / Serializer 每个阶段）和**端到端测试**（ContextManager.assemble() 五阶段串联）
- 测试通过率：**100%**，覆盖率：**≥96%**（含分支覆盖）

### Lint
- **flake8** 零报错 + **Pylance** strict 模式零报错 + `ruff` 格式检查通过

### 类型标注
- 禁止使用 `Any`（无法推断具体类型的场景使用 `TypeVar` 或 `Union`）
- 所有函数参数和返回值必须标注完整类型

---

## 目录

1. [设计目标](#1-设计目标)
2. [新目录结构](#2-新目录结构)
3. [核心数据流](#3-核心数据流)
4. [ContextManager](#4-contextmanager)
5. [选取策略（Selector）](#5-选取策略selector)
6. [压缩机制（Compressor）](#6-压缩机制compressor)
7. [预算执行（BudgetController）](#7-预算执行budgetcontroller)
8. [序列化（Serializer）](#8-序列化serializer)
9. [MemoryService 改造](#9-memoryservice-改造)
10. [Hook 改造](#10-hook-改造)
11. [Runtime 集成](#11-runtime-集成)
12. [配置模型](#12-配置模型)
13. [分层降级矩阵](#13-分层降级矩阵)
14. [迁移路径](#14-迁移路径)

---

## 1. 设计目标

### 1.1 原则

| 原则 | 含义 |
|------|------|
| **Memory 返回数据，Context 做决策** | MemoryService 只返回裸结构体，ContextManager 决定怎么组 prompt |
| **管线化** | 选取 → 压缩 → 预算 → 序列化，四阶段顺序执行，每阶段可替换 |
| **分层降级** | L1 原始消息 → L2 轮次摘要 → L3 提取事实 → L4 行为模式，逐级 fallback |
| **单向依赖** | ContextManager → MemoryService，不允许反向 |

### 1.2 与非目标

| 范围 | 说明 |
|------|------|
| **包括** | 选取、压缩、预算、序列化、Memory recall 接口改造、新 Hook |
| **不包括** | RAG pipeline、长期向量库、LLM extractor 实现、跨 agent 上下文共享 |

---

## 2. 新目录结构

```
src/
  ├── context/                          # 上下文管理
  │   ├── __init__.py                   #   导出 ContextManager
  │   ├── _manager.py                   #   ContextManager 主类（编排管线）
  │   ├── _selector.py                  #   选取策略（滑动窗口 + 去重）
  │   ├── _compressor.py               #   压缩机制（截断/摘要/分层降级）
  │   ├── _budget.py                    #   预算执行（动态分配 + 强制裁剪）
  │   ├── _serializer.py                #   序列化（ContextPayload → llm_messages）
  │   ├── _models.py                    #   上下文专用模型
  │   ├── _config.py                    #   上下文管理配置
  │   └── context_hooks/
  │       ├── __init__.py
  │       └── _assembler_hook.py         #   before_llm Transform: 编排入口
  │
  └── memory/
      └── ...                           #   见 memory-system-design.md
```

---

## 3. 核心数据流

```
before_llm 触发
  │
  ├─ 0. ContextManager.assemble()
  │     │
  │     ├─ Phase 1: SELECT
  │     │   Selector.select(ctx) → SelectionDecision
  │     │   ├─ 决定 messages 中保留哪些原始轮次（滑动窗口）
  │     │   ├─ 记录被裁轮次的 turn_index 范围 → cropped_ranges
  │     │   └─ 标记已存在的 memory 与保留消息的重复 → dedup_keys
  │     │
  │     ├─ Phase 2: LOAD
  │     │   Loader.load(decision) → RawContext
  │     │   ├─ 调用 MemoryService.recall_raw() 获取各层数据
  │     │   ├─ 按 dedup_keys 过滤掉与原始消息重叠的记忆
  │     │   └─ 从 episodic store 检索被裁轮次的摘要
  │     │
  │     ├─ Phase 3: COMPRESS
  │     │   Compressor.compress(raw, budget) → ContextPayload
  │     │   ├─ 分层决策（token 够 → L1+L2+L3, 不够 → L2+L3, 再不够 → L3+L4）
  │     │   ├─ 工具结果截断
  │     │   └─ 构建 ContextPayload
  │     │
  │     ├─ Phase 4: BUDGET
  │     │   BudgetController.apply(payload) → ContextPayload
  │     │   ├─ 动态配额分配
  │     │   ├─ TokenManager.apply_budget() 强制裁剪
  │     │   └─ 保底预留校验
  │     │
  │     └─ Phase 5: SERIALIZE
  │       Serializer.serialize(payload, ctx) → llm_messages
  │       ├─ 从 ContextPayload 构建 system message
  │       └─ 追加保留的原始消息
  │
  └─ → Runtime 拿 llm_messages 调用 LLM
```

---

## 4. ContextManager

`context/manager.py`

```python
class ContextManager:
    """上下文管理统一入口。

    编排五阶段管线：SELECT → LOAD → COMPRESS → BUDGET → SERIALIZE。
    单一入口 assemble(ctx) 被 ContextAssemblerHook 调用。
    """

    def __init__(
        self,
        memory: MemoryService,
        selector: Selector | None = None,
        compressor: Compressor | None = None,
        budget_controller: BudgetController | None = None,
        serializer: Serializer | None = None,
        config: ContextConfig | None = None,
    ):
        self._memory = memory       # 唯一的外部依赖
        self._selector = selector or Selector()
        self._compressor = compressor or Compressor()
        self._budget = budget_controller or BudgetController()
        self._serializer = serializer or Serializer()
        self._config = config or ContextConfig()

    async def assemble(self, ctx: RuntimeContext) -> list[dict]:
        """五阶段编排，返回 llm_messages。"""
        # Phase 1: 选取
        decision = await self._selector.select(ctx, self._config)

        # Phase 2: 加载
        raw = await self._load(decision, ctx)

        # Phase 3: 压缩
        payload = await self._compressor.compress(raw, decision, ctx)

        # Phase 4: 预算
        payload = await self._budget.apply(payload, self._config)

        # Phase 5: 序列化
        return self._serializer.serialize(payload, decision, ctx)
```

### 4.1 与 MemoryService 的新接口

```python
# MemoryService 新增方法（v2）
class MemoryService:
    async def recall_raw(
        self,
        session_id: str,
        user_id: str | None = None,
        query: str = "",
        *,
        turn_ranges: list[tuple[int, int]] | None = None,
        # 指定需要检索的 turn 区间（被裁轮次要补摘要时用到）
    ) -> RecallResult:
        """返回裸数据，而非 ContextPayload。"""
        ...

    # recall() 保留向后兼容，内部调用 recall_raw() + Compressor
```

```python
@dataclass
class RecallResult:
    """Memory 返回的裸数据，不含任何裁剪/序列化逻辑。"""
    episodic_memories: list[EpisodicMemoryEntry]    # 含 summary + raw_content + turn_index
    entity_profile: dict[str, EntityProfileValue]
    concepts: list[ConceptSummary]
    tone_instruction: str
```

---

## 5. 选取策略（Selector）

`context/selector.py`

```python
@dataclass
class SelectionDecision:
    """选取决策结果。"""
    # sliding window
    preserve_message_count: int          # 保留的原始消息轮次数
    cropped_ranges: list[tuple[int, int]]  # 被裁的 [start, end] turn_index 范围
    keep_from_index: int                 # ctx.messages 中保留的起始索引

    # dedup
    dedup_memory_ids: set[str]           # 与保留消息重叠的记忆 ID
    dedup_turn_indices: set[int]         # 与保留消息重叠的 turn_index
```

```python
class Selector:
    """选取策略：滑动窗口 + 结构去重 + 语义排序（v2）。"""

    async def select(
        self,
        ctx: RuntimeContext,
        config: ContextConfig,
    ) -> SelectionDecision:
        """执行选取策略，返回决策。"""
        # 1. 滑动窗口
        keep = self._apply_sliding_window(ctx, config)

        # 2. 结构去重：找出哪些 memory 摘要与保留的原始消息重叠
        dedup = self._find_dedup_keys(ctx, keep, config)

        return SelectionDecision(
            preserve_message_count=keep.count,
            cropped_ranges=keep.cropped_ranges,
            keep_from_index=keep.from_index,
            dedup_memory_ids=dedup.memory_ids,
            dedup_turn_indices=dedup.turn_indices,
        )

    def _apply_sliding_window(
        self, ctx: RuntimeContext, config: ContextConfig
    ) -> SlidingResult:
        """滑动窗口裁剪 ctx.messages。

        规则：
        - 保留最后 N 轮（user + assistant + tool 完整的轮次）
        - tool_call 与其 result 视为同一轮，不可分割
        - system message 始终保留
        """
        ...

    def _find_dedup_keys(
        self, ctx: RuntimeContext, keep: SlidingResult, config: ContextConfig
    ) -> DedupResult:
        """找出与保留的原始消息重叠的记忆 ID。

        判断标准：
        - memory.turn_index 在 keep 范围内 → 记忆摘要已在原始消息中 → 去重
        - memory 的原始内容与保留消息内容高度相似 → 去重（v2 语义去重）
        """
        ...
```

### 5.1 滑动窗口规则

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `preserve_turns` | 10 | 保留最近多少轮完整对话 |
| `preserve_tool_context` | true | 工具调用与结果成对保留，不拆分 |
| `min_preserve_turns` | 3 | 即使 token 超限也至少保留 N 轮 |
| `adaptive_window` | true | v2：根据本轮 query token 数动态调整窗大小 |

### 5.2 去重规则

| 规则 | 触发条件 | 行为 |
|------|---------|------|
| turn_index 去重 | memory.turn_index 在保留的原始消息中 | 移除该 memory 摘要 |
| 内容近似去重（v2） | 摘要与原始消息 TF-IDF 余弦 > 0.85 | 移除冗余摘要 |
| 跨 session 记忆 | turn_index 不在任何原始消息中 | 始终保留（无重叠可能） |

---

## 6. 压缩机制（Compressor）

`context/compressor.py`

```python
class Compressor:
    """压缩机制：分层降级 + 截断 + 实体化（v2）。"""

    def __init__(self, token_manager: TokenManager):
        self._token_manager = token_manager

    async def compress(
        self,
        raw: RawContext,
        decision: SelectionDecision,
        ctx: RuntimeContext,
    ) -> ContextPayload:
        """根据可用 token 和选取决策，构建 ContextPayload。

        分层降级策略（详见 §13 矩阵）：
        - token 充足 → L1(原始消息) + L2(摘要) + L3(实体) + L4(行为)
        - token 中等 → L2(摘要) + L3(实体) + L4(行为)
        - token 紧张 → L3(事实) + L4(行为)
        """
        # 1. 估算可用 token
        available = self._estimate_available(ctx)

        # 2. 选择层级
        level = self._select_level(available)

        # 3. 按层级构建 ContextPayload
        payload = ContextPayload()
        payload.system_prompt = self._get_system_prompt(ctx)
        payload.priority_hints = PriorityHints(
            max_tokens=available,
            preserve_last_n_history=decision.preserve_message_count,
            reserve_for_response=self._config.reserve_for_response,
        )

        if level >= LEVEL.L1:
            # L1: 原始消息已在 ctx.messages 中，标记保留多少
            ...
        if level >= LEVEL.L2:
            # L2: 被裁轮次的摘要 + 跨 session 记忆
            payload.memories = self._select_memories(raw, decision, available)
        if level >= LEVEL.L3:
            # L3: 实体画像 + 概念
            payload.entity_profile = raw.entity_profile
            payload.concepts = raw.concepts
        if level >= LEVEL.L4:
            # L4: 行为模式
            payload.tone_instruction = raw.tone_instruction

        return payload

    def _select_level(self, available: int) -> LEVEL:
        """根据 token 预算选择层级。"""
        if available > 20000:
            return LEVEL.L1
        elif available > 8000:
            return LEVEL.L2
        elif available > 2000:
            return LEVEL.L3
        else:
            return LEVEL.L4

    def _select_memories(
        self,
        raw: RawContext,
        decision: SelectionDecision,
        budget: int,
    ) -> list[MemoryEntrySummary]:
        """选择注入的记忆，排除被截断的轮次。

        策略：
        1. 移除与保留原始消息重叠的记忆（dedup）
        2. 优先选被裁轮次的记忆（补偿）
        3. 按重要性降序取前 N 条
        4. 按 token 预算截断
        """
        # 1. 排除重复
        candidates = [
            m for m in raw.episodic_memories
            if m.id not in decision.dedup_memory_ids
        ]

        # 2. 被裁轮次的记忆优先（补偿）
        cropped = [m for m in candidates if m.turn_index in decision.cropped_indices()]
        others = [m for m in candidates if m not in cropped]

        # 3. 按重要性排序
        ordered = sorted(cropped, key=lambda m: m.importance, reverse=True)
        ordered += sorted(others, key=lambda m: m.importance, reverse=True)

        # 4. 按 token 预算截断
        ...

        return ordered[:limit]
```

### 6.1 TOKEN 估算

```python
def _estimate_message_tokens(messages: list[dict]) -> int:
    """估算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        content = str(msg.get("content", ""))
        total += len(content)
        if "tool_calls" in msg:
            total += sum(len(str(tc)) for tc in msg["tool_calls"])
    return int(total * 0.4)  # 中英混合估算
```

---

## 7. 预算执行（BudgetController）

`context/budget.py` — 迁入现有 `TokenManager` 并增强

```python
class BudgetController:
    """预算执行：动态分配 + 强制裁剪 + 保底预留。

    接替原 memory/pipeline/token_manager.py 的 TokenManager。
    """

    def __init__(self, token_manager: TokenManager | None = None):
        self._token_manager = token_manager or TokenManager()

    async def apply(
        self,
        payload: ContextPayload,
        raw_messages: list[dict],   # ← 新增：待保留的原始消息
        config: ContextConfig,
    ) -> ContextPayload:
        """执行预算。

        计算总 token = payload 各字段 + 原始消息。
        超限时先裁 payload 字段，还不够则标记降级。
        """
        # 1. 动态配额分配
        payload.priority_hints = self._allocate_budget(payload, config)

        # 2. 强制裁剪（payload 字段 + 原始消息统一预算）
        payload = self._token_manager.apply_budget(
            payload,
            raw_messages=raw_messages,     # ← 新增：传入原始消息算总账
            max_tokens=config.max_context_tokens,
        )

        # 3. 保底预留校验
        self._ensure_reserve(payload, config)

        return payload

    def _allocate_budget(
        self,
        payload: ContextPayload,
        config: ContextConfig,
    ) -> PriorityHints:
        """按各来源预估占比动态分配 token 配额。

        分配比例（可配置）：
        - system prompt + tone:     10%
        - entity profile:           10%
        - concepts:                 10%
        - episodic memories:        30%
        - history (raw messages):   30%
        - reserve for response:     10%
        """
        budget = config.max_context_tokens
        return PriorityHints(
            max_tokens=budget,
            preserve_last_n_history=max(3, int(
                (budget * 0.30) / config.avg_message_tokens
            )),
            reserve_for_response=int(budget * 0.10),
        )
```

### 7.1 动态分配 vs 静态分配

| | 静态 | 动态（本方案） |
|--|------|--------------|
| history 配额 | 固定 N 轮 | 根据 token 预算 ÷ 平均消息大小 计算 |
| memory 配额 | 固定 5 条 | 按重要性排序后按 token 配额截断 |
| 保底预留 | 固定 1024 | 总预算的 10%，至少 512 |

---

## 8. 序列化（Serializer）

`context/serializer.py`

```python
class Serializer:
    """序列化 ContextPayload + 保留的原始消息 → llm_messages。"""

    def serialize(
        self,
        payload: ContextPayload,
        decision: SelectionDecision,
        ctx: RuntimeContext,
    ) -> list[dict]:
        """构建最终送 LLM 的消息数组。

        当前逻辑（与现有 serialize_for_llm() 兼容）：
        llm_messages[0] = { "role": "system", "content": payload.serialize_to_system_message() }
        llm_messages[1..n] = 保留的原始消息（按 decision.keep_from_index 截取）
        """
        # 构建 system message
        system_content = payload.serialize_to_system_message()
        llm_messages = [{"role": "system", "content": system_content}]

        # 追加保留的原始消息
        keep_from = decision.keep_from_index
        for msg in ctx.messages[keep_from:]:
            if msg.get("role") == "system":
                continue
            llm_messages.append(dict(msg))

        return llm_messages
```

---

## 9. MemoryService 改造

### 9.1 新增 `recall_raw()` 接口

```python
# memory/service.py 新增

@dataclass
class RecallResult:
    """Memory 裸数据返回结构。

    与 ContextPayload 的区别：
    - 不含裁剪/序列化逻辑
    - 返回完整数据，由 ContextManager 决定取舍
    """
    episodic_memories: list[EpisodicMemoryEntry]
    entity_profile: dict[str, EntityProfileValue]
    concepts: list[ConceptSummary]
    tone_instruction: str

class MemoryService:
    async def recall_raw(
        self,
        session_id: str,
        user_id: str | None = None,
        query: str = "",
        *,
        turn_ranges: list[tuple[int, int]] | None = None,
        max_memories: int = 20,
    ) -> RecallResult:
        """返回裸数据供 ContextManager 使用。

        Args:
            turn_ranges: 指定检索哪些 turn_index 范围的记忆
                         例如 [(0, 5), (10, 15)] 表示检索第 0-5 轮和第 10-15 轮
        """
        episodic = []
        if self._episodic_store:
            if turn_ranges:
                # 按 turn 区间检索（被裁轮次的摘要补偿）
                for start, end in turn_ranges:
                    memories = await self._episodic_store.recall_by_turn_range(
                        session_id, start, end,
                    )
                    episodic.extend(memories)
            else:
                # 默认检索
                memories = await self._episodic_store.recall_session(
                    session_id, limit=max_memories, min_importance=0.3,
                )
                episodic.extend(memories)

        # entity / semantic / pattern 保持不变
        ...

        return RecallResult(
            episodic_memories=episodic,
            entity_profile=entity_profile,
            concepts=concepts,
            tone_instruction=tone_instruction,
        )

    # 旧 recall() 标记 deprecated，内转为 recall_raw() + Compressor
    async def recall(self, ...) -> ContextPayload:
        """已废弃，请使用 recall_raw()。"""
        result = await self.recall_raw(...)
        return self._legacy_compressor.compress(result)
```

### 9.2 EpisodicStore 新增接口

```python
# memory/interfaces/episodic_memory.py 新增

class EpisodicStore(ABC):
    @abstractmethod
    async def recall_by_turn_range(
        self,
        session_id: str,
        start_turn: int,
        end_turn: int,
    ) -> list[EpisodicMemoryEntry]:
        """按 turn_index 范围检索记忆。"""
        ...
```

### 9.3 `TokenManager` 迁移

TokenManager 的核心逻辑（估算 + 按优先级裁剪 ContextPayload 字段）**保留不变**，但涉及 3 处改动：

#### 9.3.1 迁移路径

```
迁出: memory/pipeline/token_manager.py  TokenManager
  │      (改为向后兼容别名)
  ▼
迁入: context/budget.py                TokenManager (增强版)
       + apply_budget() 新增 raw_messages 参数算总账
```

#### 9.3.2 `context/budget.py` 中的增强版

```python
class TokenManager:
    """Token 管理器: 按语义优先级裁剪 ContextPayload。

    增强点（与旧版区别）:
    - 新增 raw_messages 参数，计算总 token = payload + 原始消息
    - 配额分配走 PriorityHints 配置，不再硬编码 50%
    - 超限后返回裁剪结果 + 降级建议（反馈给 Compressor）
    """

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return int(len(text) * 0.4)

    def apply_budget(
        self,
        payload: ContextPayload,
        raw_messages: list[dict],        # ← 新增
        max_tokens: int,
    ) -> ContextPayload:
        """强制裁剪，算总账（payload 各字段 + 原始消息）。"""
        reserve = payload.priority_hints.reserve_for_response
        budget = max_tokens - reserve

        # ---- 算总账 ----
        payload_tokens = self._sum_payload_tokens(payload)
        message_tokens = sum(
            self.estimate_tokens(str(m.get("content", "")))
            for m in raw_messages
        )
        total = payload_tokens + message_tokens

        if total <= budget:
            return payload

        # ---- payload 裁剪（旧逻辑） ----
        # 以下保持原有按优先级裁剪 memories → concepts → entity 的逻辑不变
        ...
```

#### 9.3.3 `memory/pipeline/recall.py` 移除 TokenManager 调用

当前 `RecallPipeline.run()` 最后一行需要移除：

```python
# 当前（需删除）
return self._token_manager.apply_budget(payload, max_tokens)

# 改为
return payload   # 原样返回，裁剪由 ContextManager 统一负责
```

同时 `RecallPipeline.__init__` 中移除 `self._token_manager = TokenManager()`。

#### 9.3.4 `memory/pipeline/token_manager.py` 保留为别名

```python
# memory/pipeline/token_manager.py
# 保留为向后兼容别名，实际实现在 context/budget.py

from lania_agent_runtime.context.budget import TokenManager  # noqa: F401
```

#### 9.3.5 完整的 import 链变化

```
迁移前:
  memory.service → pipeline.recall → pipeline.token_manager
                                       └─ models.ContextPayload

迁移后:
  memory.service → pipeline.recall           ← 不再 import TokenManager
  context.manager → context.budget.TokenManager
                     └─ models.ContextPayload
  memory.pipeline.token_manager → context.budget.TokenManager (别名)
```

所有引用 `memory.pipeline.token_manager.TokenManager` 的代码（如果有）通过别名自动转发，无需改动。

---

## 10. Hook 改造

### 10.1 新增：ContextAssemblerHook

`context/hooks/assembler_hook.py`

```python
class ContextAssemblerHook:
    """before_llm Transform: 上下文编排入口。

    替换原有的 MemoryRecallHook（BEFORE_STEP）。
    挂载在 BEFORE_LLM，因为需要拿到 user_message 作为 query。
    """

    def __init__(self, manager: ContextManager):
        self._manager = manager

    async def __call__(self, data: dict, ctx: RuntimeContext) -> dict:
        """Transform 调用。"""
        if not isinstance(data, dict):
            return data

        # 执行五阶段管线
        llm_messages = await self._manager.assemble(ctx)

        # 将结果写回 data，供 Runtime 消费
        data["messages"] = llm_messages
        return data
```

### 10.2 Runtime 注册变更

```python
# runtime.py: __init__()

# 旧代码（移除）
if has_episodic:
    runtime.transform(
        HookPoint.BEFORE_STEP, MemoryRecallHook(self._memory), name="memory_recall",
    )

# 新代码——使用主文档 agent-runtime-design.md §6 定义的 API
if has_episodic:
    self._context_manager = ContextManager(
        memory=self._memory,
        config=ContextConfig(max_context_tokens=self._config.max_tokens or 4096),
    )
    runtime.transform(
        HookPoint.BEFORE_LLM,
        ContextAssemblerHook(self._context_manager),
        name="context_assembler",
    )
```

### 10.3 MemoryRecallHook 废弃

`MemoryRecallHook` 标记为 deprecated，保留向后兼容但不建议使用。其逻辑由 `ContextAssemblerHook` → `ContextManager.assemble()` → `Loader` 替代。

### 10.4 整体 Hook 变更一览

| Hook | 原挂载点 | 新挂载点 | 变化 |
|------|---------|---------|------|
| `MemoryRecallHook` | `BEFORE_STEP` | 废弃 | 由 ContextAssemblerHook 替代 |
| `MemoryCommitHook` | `AFTER_STEP` | `AFTER_STEP` | 不变 |
| `ContextAssemblerHook` | — | `BEFORE_LLM` | 新增 |

> ⚠️ **关于 Serializer**：ContextManager 的第 5 阶段（SERIALIZE）已抽象为可替换的 `MessageSerializer` 接口。
> 详见 [`serializer-design.md`](serializer-design.md)。
> 本章的 Serializer 是内部默认实现，用户可通过注入自定义 `MessageSerializer` 替换。

---

## 11. Runtime 集成

```python
# runtime.py 改动部分

class AgentRuntime:
    def __init__(self, ..., context_manager: ContextManager | None = None):
        # ... 原有逻辑 ...

        self._ctx = RuntimeContext(...)
        self._ctx.set_services({
            "memory": self._memory,
            "context": self._context_manager,   # 新增：暴露给其他 hook 使用
        })

        has_episodic = (...)
        if has_episodic:
            # 注册上下文编排 Hook（替换 MemoryRecallHook）
            self._hooks.transform(
                BEFORE_LLM,
                ContextAssemblerHook(self._context_manager),
                name="context_assembler",
            )
            # Commit 不变
            self._hooks.transform(
                AFTER_STEP,
                MemoryCommitHook(self._memory),
                name="memory_commit",
            )

    # _step_loop 中移除 serialize_for_llm() 的调用
    # 改为直接使用 ContextAssemblerHook 返回的 messages
    async def _step_loop(self, user_id: str | None = None):
        for _ in range(max_iterations):
            # before_step (不再包含 memory recall)
            ...

            # before_llm transform → ContextAssemblerHook → messages 已组装好
            llm_data = {"messages": self._ctx.messages}
            llm_data = await self._hooks.run_transformers(BEFORE_LLM, llm_data, self._ctx)

            # ContextAssemblerHook 已填充 llm_data["messages"]
            messages = llm_data.get("messages", self._ctx.messages)

            # LLM Execute 直接用 messages
            response = await self._llm_executor.execute_with_messages(messages)
            ...
```

---

## 12. 配置模型

`context/config.py`

```python
@dataclass
class ContextConfig:
    """上下文管理配置。"""

    # ── 预算 ──
    max_context_tokens: int = 32768       # 上下文总 token 上限
    reserve_for_response: int = 0          # 0 = 自动（10% of max_context_tokens）
    avg_message_tokens: int = 500          # 单轮消息平均 token 数（用于动态配额）

    # ── 滑动窗口 ──
    preserve_turns: int = 10               # 保留的原始对话轮次数
    min_preserve_turns: int = 3            # 最少保留轮次
    preserve_tool_context: bool = True     # 工具调用成对保留

    # ── 分层降级 ──
    level1_threshold: int = 20000          # token > 20K 用 L1
    level2_threshold: int = 8000           # token > 8K 用 L2
    level3_threshold: int = 2000           # token > 2K 用 L3
    # token ≤ 2K 用 L4

    # ── 记忆检索 ──
    max_memories: int = 15                 # 最多注入记忆条数
    min_memory_importance: float = 0.3     # 最小重要性阈值
    cross_session_memory: bool = True      # 是否跨 session 检索
```

---

## 13. 分层降级矩阵

| Token 预算 | 层级 | 原始消息 | 记忆摘要 | 实体画像 | 行为模式 |
|-----------|------|---------|---------|---------|---------|
| > 20K | L1 | 保留 10 轮 | 注入全部 | 注入全部 | 注入 |
| 8K–20K | L2 | 保留 5 轮 | 注入顶部 5 条 | 注入全部 | 注入 |
| 2K–8K | L3 | 保留 3 轮 | 注入顶部 2 条 | 注入关键 3 项 | 注入 |
| ≤ 2K | L4 | 保留 1 轮 | 不注入 | 注入关键 1 项 | 注入 |

> 注意：`serialize_to_system_message()` 中 `memories[-5:]` 的硬编码 5 条上限应改为读取 `priority_hints` 或 `ContextConfig`。

---

## 14. 迁移路径

### Phase 1 — 基础管线（当前 sprint）

1. 新建 `context/` 目录及所有模块
2. 实现 `Selector`（滑动窗口 + 去重）
3. 实现 `Compressor`（分层降级 + 截断）
4. **TokenManager 迁移 + 增强**:
   - `context/budget.py` 实现增强版 `TokenManager`（新增 `raw_messages` 参数计算总账）
   - `memory/pipeline/recall.py` 移除 `self._token_manager.apply_budget()` 调用
   - `memory/pipeline/recall.py` 移除 `from .token_manager import TokenManager`
   - `memory/pipeline/token_manager.py` 改为 `context.budget.TokenManager` 别名
5. 实现 `BudgetController`，整合增强版 `TokenManager`
6. 实现 `ContextAssemblerHook`
7. MemoryService 新增 `recall_raw()`（保留旧接口）
8. Runtime 切换注册（`BEFORE_LLM` 替代 `BEFORE_STEP`）
9. 全部现有测试通过

### Phase 2 — 增强（v2）

1. 语义去重（TF-IDF / embedding 相似度）
2. 自适应滑动窗口（根据 query 复杂度动态调整）
3. `EpisodicStore.recall_by_turn_range()` 实现
4. 按 turn 区间的记忆检索（被裁轮次的精准补偿）

### Phase 3 — 高级（v3）

1. LLM extractor 接入实体化压缩
2. Cost budget 动态跟踪
3. Agent identity 注入上下文

---

## 附录：文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `context/__init__.py` | 新增 | 导出 ContextManager |
| `context/manager.py` | 新增 | 五阶段编排 |
| `context/selector.py` | 新增 | 滑动窗口 + 去重 |
| `context/compressor.py` | 新增 | 分层降级 + 截断 |
| `context/budget.py` | 新增 | TokenManager 迁入 + 动态分配 |
| `context/serializer.py` | 新增 | 序列化 |
| `context/config.py` | 新增 | 配置模型 |
| `context/models.py` | 新增 | 上下文专用模型 |
| `context/hooks/__init__.py` | 新增 | hook 包 |
| `context/hooks/assembler_hook.py` | 新增 | before_llm Transform |
| `memory/service.py` | 修改 | 新增 recall_raw() |
| `memory/interfaces/episodic_memory.py` | 修改 | 新增 recall_by_turn_range() |
| `memory/pipeline/token_manager.py` | 修改 | 改为 `context.budget.TokenManager` 的 import 别名 |
| `memory/pipeline/recall.py` | 修改 | 移除 `TokenManager.__init__` 和 `apply_budget()` 调用 |
| `memory/pipeline/recall.py` | 修改 | 移除 `from .token_manager import TokenManager` |
| `memory/hooks/recall_hook.py` | 废弃 | 标记 deprecated |
| `runtime.py` | 修改 | 注册 ContextAssemblerHook |
| `models.py` | 修改 | ContextPayload 保留，部分字段迁移 |
