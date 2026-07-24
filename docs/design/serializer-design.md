# Serializer 可插拔方案 —— MessageSerializer 接口设计

> ⚠️ **本文档是 `context-management-redesign.md` 的细化文档**。
> 将 ContextManager 五阶段管线中的第 5 阶段「序列化」抽象为可替换的公共接口。
>
> 父文档：[`context-management-redesign.md`](context-management-redesign.md) — ContextManager 五阶段管线
> 主文档：[`agent-runtime-design.md`](agent-runtime-design.md) — ContextPayload 定义（§5）

> 在现有 ContextManager 五阶段管线基础上，将第 5 阶段「序列化」抽象为可替换的 `MessageSerializer` 接口，使用户能自定义 Agent 输入格式化，同时保持默认行为与现有 `serialize_for_llm()` 完全兼容。

---

## 编码规范

本文档涉及的所有代码实现必须遵循以下质量要求：

### 注释
- `MessageSerializer` 接口及其所有实现类必须包含完整的**中文 docstring**，说明序列化策略和输出格式
- 用户自定义 Serializer 示例必须包含中文注释说明各步骤的用途

### 测试
- 完整的**单元测试**（DefaultSerializer 在各种 payload/messages 组合下的输出）和**向后兼容测试**（新 DefaultSerializer 与旧 serialize_for_llm() 输出一致）
- 测试通过率：**100%**，覆盖率：**≥96%**（含分支覆盖）

### Lint
- **flake8** 零报错 + **Pylance** strict 模式零报错 + `ruff` 格式检查通过

### 类型标注
- 禁止使用 `Any`；`serialize()` 方法的输入参数和返回值必须标注精确类型
- `SelectionDecision` 等模型类的所有字段必须标注类型

---

## 源码目录结构

本文档对应的源码目录：

```
src/
├── context/
│   ├── __init__.py                # 导出 ContextManager, MessageSerializer, DefaultSerializer
│   ├── _manager.py                # ContextManager（五阶段管线编排）
│   ├── _selector.py               # Selector（滑动窗口 + 去重）
│   ├── _compressor.py             # Compressor（分层降级 + 截断）
│   ├── _budget.py                 # BudgetController（动态分配 + 强制裁剪）
│   ├── _serializer.py             # ★ MessageSerializer ABC + DefaultSerializer
│   ├── _models.py                 # SelectionDecision 等上下文专用模型
│   ├── _config.py                 # ContextConfig 配置
│   └── _hooks/
│       ├── __init__.py
│       └── _assembler_hook.py     # ContextAssemblerHook（before_llm Transform）
├── context_payload.py             # ContextPayload 定义（由主文档管理）
└── docs/examples/custom_serializer/  # 用户自定义 Serializer 示例
```

---

## 目录

1. [设计目标](#1-设计目标)
2. [接口定义](#2-接口定义)
3. [默认实现](#3-默认实现)
4. [用户自定义范例](#4-用户自定义范例)
5. [集成到 ContextManager](#5-集成到-contextmanager)
6. [Runtime 集成](#6-runtime-集成)
7. [配置模型](#7-配置模型)
8. [与现有序列化的关系](#8-与现有序列化的关系)
9. [测试策略](#9-测试策略)
10. [迁移路径](#10-迁移路径)
11. [附录：完整代码清单](#11-附录完整代码清单)

---

## 1. 设计目标

### 1.1 核心原则

| 原则 | 含义 |
|------|------|
| **可替换** | `ContextManager` 的序列化阶段通过 DI 注入，用户可以传入自己的 Serializer |
| **接口契约** | 输入 `(ContextPayload, SelectionDecision, RuntimeContext)` → 输出 `list[dict]`，无副作用 |
| **默认兼容** | 默认实现与当前 `serialize_for_llm()` + `serialize_to_system_message()` 行为完全一致 |
| **纯函数** | 不修改 ctx，仅产生返回值；多次相同输入产生相同输出 |
| **单一职责** | 只负责"如何组装 messages"，不负责消息选取/压缩/预算 |

### 1.2 职责边界

```
Serializer 负责:                               Serializer 不负责:
─────────────────────────                      ─────────────────────────
• 将 ContextPayload 各字段格式化到 system message     • 消息选取（Selector）
• 决定 messages 数组的排列结构和 role 分配             • Token 预算（BudgetController）
• 注入额外引导消息（如自定义前缀、few-shot 示例）       • 记忆压缩（Compressor）
• 按用户需求重排 prompt 段落顺序                      • 消息去重
```

### 1.3 与非目标

| 范围 | 说明 |
|------|------|
| **包括** | `MessageSerializer` 抽象接口、`DefaultSerializer` 实现、ContextManager 集成、配置注入、用户自定义范例 |
| **不包括** | Selector/Compressor/BudgetController 的改造、MemoryService 的改造、RAG 集成 |

---

## 2. 接口定义

### 2.1 核心接口

`context/serializer.py`

```python
"""Serializer 接口：ContextPayload + 选取决策 → llm_messages。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from lania_agent_runtime.context.models import SelectionDecision
from lania_agent_runtime.context.config import ContextConfig
from lania_agent_runtime.models import ContextPayload


class MessageSerializer(ABC):
    """可替换的消息序列化接口。

    职责：将 ContextPayload（多源上下文）和原始消息历史，
    组装为最终发送给 LLM 的 messages 数组。

    一个 Serializer 控制：
      - system message 中各来源（memories / profile / concepts 等）的拼接方式
      - 是否将某些来源放到 user message 而非 system message
      - 是否注入额外的引导消息
      - messages 中 role 的分配和顺序
    """

    @abstractmethod
    def serialize(
        self,
        payload: ContextPayload,
        decision: SelectionDecision,
        messages: list[dict[str, Any]],
        config: ContextConfig,
    ) -> list[dict[str, Any]]:
        """执行序列化。

        Args:
            payload: 经过 SELECT → LOAD → COMPRESS → BUDGET 后的上下文载荷，
                     包含 system_prompt, memories, entity_profile, concepts,
                     tone_instruction, rag_documents, injected_context 等字段。
            decision: Selector 的选取决策，含 keep_from_index 等。
            messages: 完整的原始消息历史（可能含被裁的消息，Serializer 按需过滤）。
            config: 上下文管理配置。

        Returns:
            最终发送给 LLM 的消息数组。
            典型结构：[{role: "system", content: ...},
                       {role: "user", content: ...},
                       ...]
        """
        ...
```

### 2.2 设计决策说明

#### 为什么接口是同步的？

序列化操作本质是字符串/字典组装，不涉及 IO 或 LLM 调用，因此使用同步接口。用户自定义 Serializer 也不应执行异步操作（如需异步操作应在 Hook Transform 阶段完成）。

#### 为什么传入完整的 `messages` 而非已裁减的？

历史消息的选取已在 `SelectionDecision` 中表达（`keep_from_index`）。传入完整 `messages` 给 Serializer，让自定义实现可以灵活决定何时引用原始消息、何时注入摘要——而不是强制只取某个切片。

#### 为什么不直接操作 `RuntimeContext`？

保持接口纯函数的约束。只读参数通过入参显式传递，避免隐式依赖 `ctx` 的某些属性导致难以测试。

---

## 3. 默认实现

### 3.1 DefaultSerializer

`context/serializer.py`（与接口同文件）

```python
class DefaultSerializer(MessageSerializer):
    """默认序列化实现。

    行为与当前 RuntimeContext.serialize_for_llm() 完全兼容：
      - 将所有上下文源（memories / entity_profile / tone / concepts / rag / injected）
        合并到一条 system message 中，格式由 ContextPayload.serialize_to_system_message() 定义
      - 从 keep_from_index 开始截取原始消息追加到 system message 之后
      - 跳过 role="system" 的原始消息（已合并到 system message 中）

    这是用户自定义 Serializer 的参考基准实现。
    """

    def serialize(
        self,
        payload: ContextPayload,
        decision: SelectionDecision,
        messages: list[dict[str, Any]],
        config: ContextConfig,
    ) -> list[dict[str, Any]]:
        # 1. 构建 system message 内容
        system_content = payload.serialize_to_system_message()
        result: list[dict[str, Any]] = [
            {"role": "system", "content": system_content},
        ]

        # 2. 追加保留的原始消息
        keep_from = decision.keep_from_index
        for msg in messages[keep_from:]:
            if msg.get("role") == "system":
                continue  # 原始 system 已合并进上方的长字符串
            result.append(dict(msg))

        return result
```

### 3.2 与现有 `serialize_for_llm()` 的等价性证明

`DefaultSerializer.serialize(payload, decision, messages, config)` 与当前 `RuntimeContext.serialize_for_llm()` 在相同输入下产生相同输出：

| 输入 | 当前 serialize_for_llm() | DefaultSerializer |
|------|------------------------|-------------------|
| `payload.system_prompt` | 从 messages 中回填（若无） | 由 ContextManager 保证已填充 |
| `payload.serialize_to_system_message()` | 直接调用 | 委托调用 |
| `keep_from_index` | 硬编码为 1（保留全部） | 从 `decision.keep_from_index` 取值 |
| 跳过 system 消息 | 显式跳过 | 显式跳过 |

**差异点**（改进）：`DefaultSerializer` 的 `keep_from` 由 `SelectionDecision` 提供，而当前代码硬编码为保留全部消息。这意味着一旦 Selector 启用滑动窗口，Serializer 自动遵循窗口策略——不需要改动 Serializer 代码。

---

## 4. 用户自定义范例

### 4.1 将 memories 放到 user message 而非 system message

```python
class MemoriesBeforeUserSerializer(MessageSerializer):
    """将记忆摘要作为 user message 的前缀注入，而非塞入 system message。"""

    def __init__(self, max_memories: int = 5):
        self._max_memories = max_memories

    def serialize(
        self,
        payload: ContextPayload,
        decision: SelectionDecision,
        messages: list[dict[str, Any]],
        config: ContextConfig,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        # 1. system message（不含 memories，保持简洁）
        system_parts = [payload.system_prompt]
        if payload.tone_instruction:
            system_parts.append(f"## Communication Style\n{payload.tone_instruction}")
        result.append({"role": "system", "content": "\n\n".join(system_parts)})

        # 2. 将 memories 作为独立的 user 消息注入（带有时间上下文）
        if payload.memories:
            mem_lines = []
            for m in payload.memories[:self._max_memories]:
                mem_lines.append(f"- [{m.get('created_at', '?')}] {m.get('summary', '')}")
            result.append({
                "role": "user",
                "content": "## Previous Conversation Context\n" + "\n".join(mem_lines),
            })

        # 3. 追加保留的原始消息
        keep_from = decision.keep_from_index
        for msg in messages[keep_from:]:
            if msg.get("role") == "system":
                continue
            result.append(dict(msg))

        return result
```

### 4.2 实体画像优先 + 精简记忆的 serializer

```python
class ProfileFirstSerializer(MessageSerializer):
    """将 entity_profile 放在 system message 顶部，记忆只保留高重要性的。"""

    def __init__(self, min_importance: float = 0.5):
        self._min_importance = min_importance

    def serialize(
        self,
        payload: ContextPayload,
        decision: SelectionDecision,
        messages: list[dict[str, Any]],
        config: ContextConfig,
    ) -> list[dict[str, Any]]:
        parts = [payload.system_prompt]

        # 用户画像优先
        if payload.entity_profile:
            lines = [f"- {k}: {v.get('value', v)}" for k, v in payload.entity_profile.items()]
            parts.append("## User Profile\n" + "\n".join(lines))

        # 只保留高重要性记忆
        if payload.memories:
            important = [m for m in payload.memories
                         if m.get("importance", 0) >= self._min_importance]
            if important:
                lines = [f"- [{m['created_at']}] {m['summary']}" for m in important]
                parts.append("## Key Memories\n" + "\n".join(lines))

        # 行为风格
        if payload.tone_instruction:
            parts.append(f"## Style\n{payload.tone_instruction}")

        result = [{"role": "system", "content": "\n\n".join(parts)}]

        keep_from = decision.keep_from_index
        for msg in messages[keep_from:]:
            if msg.get("role") == "system":
                continue
            result.append(dict(msg))

        return result
```

### 4.3 Jinja2 模板驱动的 serializer

```python
from jinja2 import Template

class TemplateSerializer(MessageSerializer):
    """用 Jinja2 模板完全自定义 system message 格式。

    用户在模板中可访问:
      - {{ system_prompt }}
      - {{ memories }}         — list[MemoryEntrySummary]
      - {{ entity_profile }}   — dict[str, EntityProfileValue]
      - {{ concepts }}         — list[ConceptSummary]
      - {{ tone_instruction }} — str
      - {{ rag_documents }}    — list[RagDocumentSummary]
      - {{ injected_context }} — list[str]

    模板示例:
        \"""
        ## System
        {{ system_prompt }}

        ## User Profile
        {% for k, v in entity_profile.items() %}
        - {{ k }}: {{ v.value }}
        {% endfor %}

        ## Context
        {% for ctx_text in injected_context %}
        {{ ctx_text }}
        {% endfor %}
        \"""
    """

    def __init__(self, template_str: str):
        self._template = Template(template_str)

    def serialize(
        self,
        payload: ContextPayload,
        decision: SelectionDecision,
        messages: list[dict[str, Any]],
        config: ContextConfig,
    ) -> list[dict[str, Any]]:
        system_content = self._template.render(
            system_prompt=payload.system_prompt,
            memories=payload.memories,
            entity_profile={
                k: v if not isinstance(v, dict) else v
                for k, v in payload.entity_profile.items()
            },
            concepts=payload.concepts,
            tone_instruction=payload.tone_instruction,
            rag_documents=payload.rag_documents,
            injected_context=payload.injected_context,
        )
        result = [{"role": "system", "content": system_content}]

        keep_from = decision.keep_from_index
        for msg in messages[keep_from:]:
            if msg.get("role") == "system":
                continue
            result.append(dict(msg))

        return result
```

### 4.4 多条 system 消息（仅限支持多 system 的 provider）

> ⚠️ **注意**：本方案与主文档 `agent-runtime-design.md` §5.3 的假设不同。
> 主文档规定 `messages[0]` 是唯一的 system message，`messages[1..n]` 是对话日志。
> 此方案**仅适用于支持多个 system 消息的 LLM provider**（如 Anthropic Claude），
> 在 OpenAI 上后续 system 消息会被视为 user 角色。
> 使用前请确认 LLMExecutor 的 Provider 实现支持。

```python
class MultiSystemSerializer(MessageSerializer):
    """将上下文中不同来源拆成多条 system 消息（仅限支持多 system 的 provider）。

    结构:
      [0] role=system: 基础 system_prompt
      [1] role=system: 用户画像
      [2] role=system: 记忆 + 概念
      [3] role=user:   最新的用户消息
    """

    def serialize(
        self,
        payload: ContextPayload,
        decision: SelectionDecision,
        messages: list[dict[str, Any]],
        config: ContextConfig,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = [
            {"role": "system", "content": payload.system_prompt},
        ]

        if payload.entity_profile:
            lines = [f"- {k}: {v.get('value', v)}" for k, v in payload.entity_profile.items()]
            result.append({
                "role": "system",
                "content": "## User Profile\n" + "\n".join(lines),
            })

        if payload.memories or payload.concepts:
            parts = []
            if payload.memories:
                parts.append("## Memories\n" + "\n".join(
                    f"- [{m['created_at']}] {m['summary']}" for m in payload.memories[-5:]
                ))
            if payload.concepts:
                parts.append("## Concepts\n" + "\n".join(
                    f"- {c.get('name', '')}: {c.get('description', '')}" for c in payload.concepts
                ))
            result.append({"role": "system", "content": "\n\n".join(parts)})

        # 只保留最新一条 user 消息（简洁模式）
        for msg in reversed(messages):
            if msg.get("role") == "user":
                result.append({"role": "user", "content": msg.get("content", "")})
                break

        return result
```

---

## 5. 集成到 ContextManager

### 5.1 ContextManager 构造变更

`context/manager.py`

```python
from lania_agent_runtime.context.serializer import (
    MessageSerializer,
    DefaultSerializer,
)


class ContextManager:
    """上下文管理统一入口。

    编排五阶段管线：SELECT → LOAD → COMPRESS → BUDGET → SERIALIZE。
    序列化阶段通过 serializer 参数可替换。
    """

    def __init__(
        self,
        memory: MemoryService,
        selector: Selector | None = None,
        compressor: Compressor | None = None,
        budget_controller: BudgetController | None = None,
        serializer: MessageSerializer | None = None,  # ← 可替换
        config: ContextConfig | None = None,
    ):
        self._memory = memory
        self._selector = selector or Selector()
        self._compressor = compressor or Compressor()
        self._budget = budget_controller or BudgetController()
        self._serializer = serializer or DefaultSerializer()  # ← 默认实现
        self._config = config or ContextConfig()

    async def assemble(self, ctx: RuntimeContext) -> list[dict]:
        """五阶段编排，返回 llm_messages。"""
        # Phase 1-4: 选取 → 加载 → 压缩 → 预算
        decision = await self._selector.select(ctx, self._config)
        raw = await self._load(decision, ctx)
        payload = await self._compressor.compress(raw, decision, ctx)
        payload = await self._budget.apply(payload, self._config)

        # Phase 5: 序列化（可替换）
        return self._serializer.serialize(
            payload=payload,
            decision=decision,
            messages=ctx.messages,
            config=self._config,
        )
```

### 5.2 文档说明图

```
ContextManager.assemble(ctx)
  │
  ├─ Phase 1: Selector.select()
  ├─ Phase 2: Loader.load()
  ├─ Phase 3: Compressor.compress()
  ├─ Phase 4: BudgetController.apply()
  │
  └─ Phase 5: Serializer.serialize()   ← 用户可替换
       │
       ├─ DefaultSerializer (默认)
       │    └─ serialize_to_system_message() + messages[keep_from:]
       │
       ├─ 用户自定义 Serializer 1
       │    └─ 例: memories 放到 user message
       │
       ├─ 用户自定义 Serializer 2
       │    └─ 例: Jinja2 模板驱动
       │
       └─ 用户自定义 Serializer 3
            └─ 例: 多 system 消息拆分
```

---

## 6. Runtime 集成

### 6.1 AgentRuntime 构造 API

用户通过两种方式注入自定义 Serializer：

#### 方式 A：通过 ContextManager 注入

```python
from lania_agent_runtime.context import ContextManager
from lania_agent_runtime.context.serializer import DefaultSerializer
from lania_agent_runtime.memory import MemoryService, GenericMemoryStore
from lania_agent_runtime.memory.backends import SQLiteBackend

# 用户自定义 serializer
class MySerializer(MessageSerializer):
    def serialize(self, payload, decision, messages, config):
        # ... 自定义逻辑 ...
        return [{"role": "system", "content": "custom..."}]

store = GenericMemoryStore(SQLiteBackend("memory.db"))
await store.initialize()
memory_svc = MemoryService(store=store)

from src.context import ContextConfig
from src.context._manager import ContextManager

context_manager = ContextManager(
    memory=memory_svc,
    serializer=MySerializer(),  # ← 注入自定义 serializer
)

# 通过 Builder 接线——AgentRuntime 本身不接收 context_manager 参数
runtime = (AgentRuntime.builder()
    .system_prompt("你是助手")
    .llm(executor=my_executor)
    .memory(memory_svc)
    .context(config=ContextConfig(max_context_tokens=4096))
    .build())
# build() 内部使用 ContextManager(memory=memory_svc, serializer=MySerializer())
```

### 6.2 ContextService 暴露

`ContextManager` 由 Builder 在 `build()` 中创建并注入 `services["context_manager"]`，
使其他 Hook 可以读取序列化结果：

---

## 7. 配置模型

### 7.1 ContextConfig 新增序列化相关字段

`context/config.py`

```python
from dataclasses import dataclass, field
from lania_agent_runtime.context.serializer import (
    MessageSerializer,
    DefaultSerializer,
)


@dataclass
class ContextConfig:
    """上下文管理配置。"""

    # 选取策略
    preserve_turns: int = 10
    min_preserve_turns: int = 3
    preserve_tool_context: bool = True
    adaptive_window: bool = True

    # 预算
    max_context_tokens: int = 16000
    reserve_for_response: int = 1024
    avg_message_tokens: int = 200

    # 序列化（新增）
    serializer: MessageSerializer | None = None
    # 如果设置了 serializer，ContextManager 构造时使用它；否则使用 DefaultSerializer。

    # 压缩
    enable_memory_dedup: bool = True
    enable_entity_extraction: bool = True
    enable_semantic_extraction: bool = True
    enable_pattern_convergence: bool = True
```

---

## 8. 与现有序列化的关系

### 8.1 现有代码现状

当前 `RuntimeContext` 上有两个序列化方法：

```python
# context.py (现有)
class RuntimeContext:
    def serialize_for_llm(self) -> list[dict]:
        """序列化 context_payload + history 为 LLM 最终消息数组。"""
        ...

    def serialize_messages(self) -> list[dict]:
        """序列化（兼容旧接口），优先返回缓存。"""
        ...
```

这两个方法在 `LLMExecutor._extract_messages()` 中被调用：

```python
# executor.py (现有)
def _extract_messages(self, ctx: RuntimeContext) -> list[dict[str, Any]]:
    return ctx.serialize_messages()
```

### 8.2 迁移后关系

```
迁移前                                   迁移后
─────────                               ─────────
RuntimeContext.serialize_for_llm()       ContextManager.assemble()
  └─ ContextPayload.serialize_...()         ├─ ... SELECT/LOAD/COMPRESS/BUDGET
  └─ messages[keep_from:]                   └─ Serializer.serialize()
                                               └─ ContextPayload.serialize_...() (复用)
LLMExecutor._extract_messages()           LLMExecutor._extract_messages()
  └─ ctx.serialize_messages()               └─ ctx.llm_messages (由 ContextAssemblerHook 预填充)
```

### 8.3 向后兼容策略

| 组件 | 兼容措施 |
|------|---------|
| `RuntimeContext.serialize_for_llm()` | 标记 `@deprecated`，内部委托给 `DefaultSerializer` |
| `RuntimeContext.serialize_messages()` | 标记 `@deprecated`，内部委托给 `serialize_for_llm()` |
| `LLMExecutor._extract_messages()` | 检查 `ctx.llm_messages` 是否已预填充，优先使用；否则回退旧路径 |
| `ContextPayload.serialize_to_system_message()` | 保持不变，作为 `DefaultSerializer` 的内部工具方法 |

---

## 9. 测试策略

### 9.1 单元测试

| 测试 | 内容 |
|------|------|
| `test_default_serializer_basic` | 空 payload + 空 messages → 只返回 system message |
| `test_default_serializer_with_memories` | memories 正确拼入 system message |
| `test_default_serializer_with_entity_profile` | entity_profile 正确拼入 |
| `test_default_serializer_skip_system` | 原始 system 消息被跳过 |
| `test_default_serializer_keep_from` | keep_from_index 正确截取 |
| `test_default_serializer_all_fields` | 所有字段同时存在时的拼接顺序 |

### 9.2 自定义 Serializer 测试

```python
class TestCustomSerializer(MessageSerializer):
    """测试用：简单的自定义 serializer。"""
    def serialize(self, payload, decision, messages, config):
        return [
            {"role": "system", "content": payload.system_prompt},
            {"role": "user", "content": f"Custom: {payload.tone_instruction}"},
        ]

def test_custom_serializer_injection():
    """验证自定义 serializer 被正确使用。"""
    manager = ContextManager(
        memory=mock_memory,
        serializer=TestCustomSerializer(),
        config=ContextConfig(),
    )
    result = await manager.assemble(mock_ctx)
    assert result[1]["content"].startswith("Custom:")
```

### 9.3 集成测试

| 测试 | 内容 |
|------|------|
| `test_context_manager_with_serializer` | ContextManager 五阶段串联，验证最后输出的 messages 结构 |
| `test_runtime_with_custom_serializer` | Runtime 完整 step loop，使用自定义 Serializer，验证 LLM 收到自定义格式 |

### 9.4 向后兼容测试

```python
def test_serialize_for_llm_deprecated_consistency():
    """验证废弃的 serialize_for_llm() 与 DefaultSerializer 输出一致。"""
    ctx = RuntimeContext(...)
    # 填充相同的 payload 和 messages
    ...
    old_result = ctx.serialize_for_llm()
    new_result = DefaultSerializer().serialize(
        payload=ctx.context_payload,
        decision=SelectionDecision(keep_from_index=0),
        messages=ctx.messages,
        config=ContextConfig(),
    )
    assert old_result == new_result
```

---

## 10. 迁移路径

### Phase 1：新增 `MessageSerializer` 接口 + `DefaultSerializer`（1-2 天）

| 步骤 | 文件 | 操作 |
|------|------|------|
| 1.1 | `context/serializer.py` | 创建新文件，定义 `MessageSerializer` 抽象基类和 `DefaultSerializer` |
| 1.2 | `context/models.py` | 确保 `SelectionDecision` 等模型存在（或创建） |
| 1.3 | `context/__init__.py` | 导出 `MessageSerializer`, `DefaultSerializer` |

### Phase 2：集成到 ContextManager（1 天）

| 步骤 | 文件 | 操作 |
|------|------|------|
| 2.1 | `context/manager.py` | `ContextManager.__init__` 新增 `serializer` 参数，`assemble()` 中调用 `self._serializer.serialize()` |\n| 2.2 | 所有 `keep_from_index` 循环 | 跳过 system 消息时增加 `metadata.is_original_system` 判断，避免误删 tool_call 间的辅助 system 消息 |
| 2.2 | `context/config.py` | `ContextConfig` 新增 `serializer` 字段 |
| 2.3 | 测试 | 验证 `ContextManager` 使用 `DefaultSerializer` 输出与预期一致 |

### Phase 3：Runtime 快捷入口（0.5 天）

| 步骤 | 文件 | 操作 |
|------|------|------|
| 3.1 | `runtime.py` | `AgentRuntime.__init__` 新增 `serializer` 参数；`__init__` 中注入 `ctx.services["context_manager"]` |
| 3.2 | 测试 | 验证 Runtime 构造时正确使用自定义 Serializer |

### Phase 4：旧方法标记废弃 + 别名（0.5 天）

| 步骤 | 文件 | 操作 |
|------|------|------|
| 4.1 | `context.py` | `serialize_for_llm()` 标记 `@deprecated`，内部委托给 `DefaultSerializer` |
| 4.2 | `context.py` | `serialize_messages()` 标记 `@deprecated` |
| 4.3 | `executor.py` | `_extract_messages()` 优先使用 `ctx.llm_messages` |

### Phase 5：用户自定义范例文档（0.5 天）

| 步骤 | 文件 | 操作 |
|------|------|------|
| 5.1 | `docs/design/serializer-design.md` | 本文档 |
| 5.2 | `examples/custom_serializer/` | 创建完整可运行的示例目录 |

### 迁移路径总览

```
Phase 1: 定义接口
  context/serializer.py  ← MessageSerializer(ABC), DefaultSerializer

Phase 2: 集成到管线
  context/manager.py     ← serializer 参数
  context/config.py      ← serializer 配置字段

Phase 3: Runtime 入口
  runtime.py             ← serializer 快捷参数

Phase 4: 废弃旧路径
  context.py             ← serialize_for_llm() 标记 deprecated
  executor.py            ← 优先使用预填充的 llm_messages

Phase 5: 文档和示例
  docs/design/serializer-design.md
  examples/custom_serializer/
```

---

## 11. 附录：完整代码清单

### 11.1 `context/serializer.py`（完整）

```python
"""Serializer 接口：ContextPayload + 选取决策 → llm_messages。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from lania_agent_runtime.context.config import ContextConfig
from lania_agent_runtime.context.models import SelectionDecision
from lania_agent_runtime.models import ContextPayload


class MessageSerializer(ABC):
    """可替换的消息序列化接口。"""

    @abstractmethod
    def serialize(
        self,
        payload: ContextPayload,
        decision: SelectionDecision,
        messages: list[dict[str, Any]],
        config: ContextConfig,
    ) -> list[dict[str, Any]]:
        """执行序列化，返回最终送 LLM 的消息数组。"""
        ...


class DefaultSerializer(MessageSerializer):
    """默认序列化实现，与现有 serialize_for_llm() 兼容。"""

    def serialize(
        self,
        payload: ContextPayload,
        decision: SelectionDecision,
        messages: list[dict[str, Any]],
        config: ContextConfig,
    ) -> list[dict[str, Any]]:
        system_content = payload.serialize_to_system_message()
        result: list[dict[str, Any]] = [
            {"role": "system", "content": system_content},
        ]

        keep_from = decision.keep_from_index
        for msg in messages[keep_from:]:
            # 跳过原始 system 消息（已被合并到上方的拼接结果中）
            # 但保留 tool_call 之间的辅助 system 消息
            if msg.get("role") == "system" and msg.get("metadata", {}).get("is_original_system", True):
                continue
            result.append(dict(msg))

        return result
```

### 11.2 `context/models.py` — SelectionDecision（新增）

```python
"""上下文管理专用模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SelectionDecision:
    """选取策略的决策结果。"""

    preserve_message_count: int = 0
    cropped_ranges: list[tuple[int, int]] = field(default_factory=list)
    keep_from_index: int = 0
    dedup_memory_ids: set[str] = field(default_factory=set)
    dedup_turn_indices: set[int] = field(default_factory=set)
```

### 11.3 `context/__init__.py`（更新导出）

```python
from lania_agent_runtime.context.manager import ContextManager
from lania_agent_runtime.context.serializer import (
    MessageSerializer,
    DefaultSerializer,
)
from lania_agent_runtime.context.config import ContextConfig
from lania_agent_runtime.context.models import SelectionDecision

__all__ = [
    "ContextManager",
    "MessageSerializer",
    "DefaultSerializer",
    "ContextConfig",
    "SelectionDecision",
]
```

### 11.4 `context/config.py`（更新）

```python
from __future__ import annotations

from dataclasses import dataclass, field

from lania_agent_runtime.context.serializer import (
    MessageSerializer,
)


@dataclass
class ContextConfig:
    """上下文管理配置。"""

    # 选取策略
    preserve_turns: int = 10
    min_preserve_turns: int = 3
    preserve_tool_context: bool = True
    adaptive_window: bool = True

    # 预算
    max_context_tokens: int = 16000
    reserve_for_response: int = 1024
    avg_message_tokens: int = 200

    # 序列化（可选，注入自定义 Serializer）
    serializer: MessageSerializer | None = None

    # 压缩
    enable_memory_dedup: bool = True
    enable_entity_extraction: bool = True
    enable_semantic_extraction: bool = True
    enable_pattern_convergence: bool = True
```

---

## 附录 A：与 context-management-redesign.md 的关系

本文档是 `context-management-redesign.md` 的 **第 8 章「序列化（Serializer）」的细化与增强**。原文档的 Serializer 是内部实现细节，本文档将其提升为**可替换的公共接口**。

```
context-management-redesign.md          serializer-design.md
────────────────────────────           ────────────────────
§8 Serializer (内部类)                  §2 MessageSerializer (ABC)
  └─ serialize()                         └─ serialize() (接口契约)
                                          §3 DefaultSerializer (默认实现)
                                          §4 用户自定义范例 (新增)
                                          §5 ContextManager 集成 (替换 §8)
                                          §6 Runtime 集成 (新增)
                                          §7 配置模型 (新增)
                                          §8-10 兼容/测试/迁移 (新增)
```
