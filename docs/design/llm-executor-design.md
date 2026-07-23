# LLMExecutor 技术方案文档

> ⚠️ **本文档是 `agent-runtime-design.md` 的子文档**。阅读前请确保已理解主文档中的 **Execute 原语**（§2）、**RuntimeContext**（§4）和 **Step Loop**（§7）设计。
>
> 关联文档：[`loop-strategy-design.md`](loop-strategy-design.md) — LoopStrategy 调用 LLMExecutor
> 关联文档：[`context-management-redesign.md`](context-management-redesign.md) — ContextManager 组装 messages
> 主文档：[`agent-runtime-design.md`](agent-runtime-design.md)

> 基于 agent-runtime-design.md 的五级原语体系，定义 LLMExecutor 的接口、实现、数据流和集成方案。

---

## 编码规范

本文档涉及的所有代码实现必须遵循以下质量要求：

### 注释
- 所有公共接口（LLMExecutor / StreamableLLMExecutor / LLMProvider）和数据类型（LLMResponse / ToolCall）必须包含完整的**中文 docstring**
- Provider 适配逻辑必须添加行内中文注释说明 API 差异

### 测试
- 完整的**单元测试**（mock Provider，覆盖正常/错误/重试/流式路径）和**集成测试**（真实 LLM API 调用验证往返）
- 测试通过率：**100%**，覆盖率：**≥96%**（含分支覆盖）

### Lint
- **flake8** 零报错 + **Pylance** strict 模式零报错 + `ruff` 格式检查通过

### 类型标注
- 禁止使用 `Any`；`LLMResponse`、`ToolCall` 等数据结构所有字段必须标注具体类型
- 所有函数参数和返回值必须标注完整类型

---

## 目录

1. [设计目标](#1-设计目标)
2. [接口定义](#2-接口定义)
3. [数据模型](#3-数据模型)
4. [核心实现](#4-核心实现)
5. [完整数据流链路](#5-完整数据流链路)
6. [外部 API 设计](#6-外部-api-设计)
7. [流式支持](#7-流式支持)
8. [错误与重试](#8-错误与重试)
9. [测试策略](#9-测试策略)
10. [附录：文件清单](#10-附录文件清单)

---

## 1. 设计目标

LLMExecutor 在架构中定位为 **Execute 原语**，是 Step Loop 中 LLM 调用段的核心执行块。

### 1.1 核心原则

| 原则 | 含义 |
|------|------|
| **纯函数** | `(ctx) → LLMResponse`，无副作用，结果通过 return 传回 |
| **不写 messages** | 追加消息是 Runtime 的职责，executor 只负责调用 LLM |
| **不感知治理** | 上下文组装、安全扫描、输出校验由外层 Hook 完成 |
| **可替换** | 通过 DI/Strategy 注入不同 Provider 实现 |
| **一次往返** | 接收 messages，调用 LLM API，返回 LLMResponse |

### 1.2 职责边界

```
LLMExecutor 负责:                            LLMExecutor 不负责:
─────────────────────────                    ─────────────────────────
• messages → LLM API → LLMResponse           • 上下文组装（before_llm Transform）
• 重试策略、超时控制                            • Token 裁剪（before_llm Transform）
• 流式数据收集                                  • 输入安全扫描（before_llm Intercept）
• Token 用量统计                                • 输出护栏校验（after_llm Intercept）
• 工具调用格式转换（tool_calls 序列化/反序列化）    • 消息持久化（Runtime 自身）
                                               • 工具调度执行（Step Loop + Tool Execute）
```

---

## 2. 接口定义

### 2.1 抽象接口

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from lania_agent_runtime.context import RuntimeContext


class LLMExecutor(ABC):
    """
    Execute 原语的 LLM 特化。

    语义: 完全接管 "messages → LLM API → LLMResponse" 的往返。
    约束: 无副作用，不写 ctx.messages，结果通过 return 传回。
    """

    @abstractmethod
    async def execute(self, ctx: RuntimeContext) -> "LLMResponse":
        """
        执行 LLM 调用。

        输入: ctx.messages（已序列化的消息数组，[0] 为 system message）
        输出: LLMResponse（LLM 回复内容 + tool_calls + 用量统计）
        """
        ...
```

### 2.2 可选的流式接口

```python
class StreamableLLMExecutor(LLMExecutor, ABC):
    """
    支持流式的 LLMExecutor 扩展接口。
    非流式 executor 不需要实现此接口。
    """

    @abstractmethod
    async def execute_stream(
        self, ctx: RuntimeContext,
    ) -> tuple["AsyncStreamCollector", "LLMResponse"]:
        """
        流式执行 LLM 调用。

        返回:
          - collector: 异步流收集器，Runtime 可逐 chunk 触发 onStreamChunk hook
          - final_response: 完整组装后的 LLMResponse（流结束才可用）
        """
        ...
```

### 2.3 工厂/构造接口

```python
@dataclass
class LLMExecutorConfig:
    """LLMExecutor 构造参数"""
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 60.0
    max_retries: int = 3
    retry_backoff_base: float = 1.0
    retry_backoff_max: float = 30.0
    api_key: str = ""          # 安全约束：不进 Runtime，仅构造时使用
    api_base: str = ""         # OpenAI-compatible base URL
    stream: bool = False       # 是否默认启用流式
```

---

## 3. 数据模型

### 3.1 LLMResponse（输出）

```python
class FinishReason(str, Enum):
    """LLM 调用结束原因枚举——统一各文档和 LoopStrategy 的判断引用"""
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    ERROR = "error"


@dataclass
class LLMResponse:
    """LLM 调用的统一返回格式"""
    content: str                         # 文本回复（tool_calls 时可能为空）
    tool_calls: list["ToolCall"]         # LLM 请求调用的工具列表
    usage: "LLMUsage"                    # Token 消耗统计
    finish_reason: FinishReason           # 枚举值：STOP / TOOL_CALLS / LENGTH / ERROR
    model: str                           # 实际使用的模型名


@dataclass
class LLMUsage:
    """Token 用量"""
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ToolCall:
    """LLM 返回的工具调用请求"""
    id: str                              # tool_call_id
    name: str                            # 工具名
    arguments: dict[str, Any]            # 解析后的参数 dict
    raw_arguments: str                   # 原始 JSON 字符串（用于日志/审计）
```

### 3.2 LLMMessage（输入结构，Runtime 侧定义）

```python
@dataclass
class LLMMessage:
    """单条消息，LLMExecutor 消费的输入格式"""
    role: str                            # "system" | "user" | "assistant" | "tool"
    content: str | None                  # 文本内容
    tool_calls: list[ToolCall] | None = None   # assistant 消息可能带 tool_calls
    tool_call_id: str | None = None            # tool 消息对应
    name: str | None = None                    # tool 消息对应
```

### 3.3 LLMProvider（内部封装）

```python
@dataclass
class LLMProviderResponse:
    """Provider 原始响应的统一包装"""
    content: str
    tool_calls: list[dict] | None        # provider 原始格式
    usage: dict                          # provider 原始格式
    finish_reason: str
    model: str


class LLMProvider(ABC):
    """
    LLM Provider 适配器接口。

    目的：隔离不同 LLM SDK 的差异，使 LLMExecutor 不依赖具体 SDK。
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> LLMProviderResponse | AsyncIterator[dict]:
        """调用 LLM API"""
        ...
```

---

## 4. 核心实现

### 4.1 OpenAI LLMExecutor 实现

```python
import asyncio
import json
from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError


class OpenAILLMExecutor(LLMExecutor):
    """
    OpenAI / OpenAI-compatible API 的 LLMExecutor 实现。

    支持:
      - GPT-4o / GPT-4 / GPT-3.5 / DeepSeek / Qwen 等兼容 API
      - Function calling / tool_calls
      - 流式与非流式
      - 指数退避重试
    """

    def __init__(
        self,
        config: LLMExecutorConfig,
        provider: LLMProvider | None = None,
    ):
        self._config = config
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.api_base or None,
            timeout=config.timeout,
        )

    async def execute(self, ctx: RuntimeContext) -> LLMResponse:
        messages = self._extract_messages(ctx)
        params = self._merge_params(ctx)
        tools_schema = self._get_tools_schema(ctx)

        last_error = None
        for attempt in range(self._config.max_retries + 1):
            try:
                raw = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=params.model,
                        messages=messages,
                        temperature=params.temperature,
                        max_tokens=params.max_tokens,
                        tools=tools_schema,
                    ),
                    timeout=self._config.timeout,
                )
                return self._to_response(raw, params.model)

            except (APITimeoutError, APIError, RateLimitError) as e:
                last_error = e
                if attempt < self._config.max_retries:
                    backoff = min(
                        self._config.retry_backoff_base * (2 ** attempt),
                        self._config.retry_backoff_max,
                    )
                    await asyncio.sleep(backoff)
                    continue

                raise LLMExecutionError(
                    last_error=last_error,
                    consecutive_errors=ctx.error_state.consecutive_errors,
                    model=params.model,
                )

    async def execute_stream(
        self, ctx: RuntimeContext,
    ) -> tuple["AsyncStreamCollector", "LLMResponse"]:
        messages = self._extract_messages(ctx)
        params = self._merge_params(ctx)
        tools_schema = self._get_tools_schema(ctx)

        stream = await self._client.chat.completions.create(
            model=params.model,
            messages=messages,
            temperature=params.temperature,
            max_tokens=params.max_tokens,
            tools=tools_schema,
            stream=True,
            stream_options={"include_usage": True},
        )
        collector = AsyncStreamCollector()
        async for chunk in stream:
            collector.collect(chunk)

        return collector, self._to_response(
            collector.assemble(), params.model,
        )

    # ── 内部方法 ──

    def _extract_messages(self, ctx: RuntimeContext) -> list[dict]:
        """从 ctx.messages 提取 LLM API 格式的消息"""
        return [
            self._serialize_message(msg) for msg in ctx.messages
        ]

    def _serialize_message(self, msg) -> dict:
        """单条消息序列化为 OpenAI API 格式"""
        d = {"role": msg["role"]}
        if msg.get("content"):
            d["content"] = msg["content"]
        if msg.get("tool_calls"):
            d["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                    },
                }
                for tc in msg["tool_calls"]
            ]
        if msg.get("tool_call_id"):
            d["tool_call_id"] = msg["tool_call_id"]
            d["content"] = msg.get("content", "")
        return d

    def _merge_params(self, ctx: RuntimeContext) -> LLMExecutorConfig:
        """ctx 配置覆盖默认配置。

        ⚠️ RuntimeContext 不包含 llm_config 字段。
        LLM 配置通过 LLMExecutorConfig 在构造时注入，
        运行时不动态修改。如需按 step 调整参数，
        请在 before_llm Transform 中通过 ctx.services 传递。
        """
        return self._config

    def _get_tools_schema(self, ctx: RuntimeContext) -> list[dict] | None:
        """
        从 Runtime 获取已注册工具的 JSON Schema。

        ⚠️ RuntimeContext 不直接持有 tools_schema。
        工具 schema 由 ToolDispatcher 在每次 before_llm Transform 阶段
        注入到 ctx.context_payload 或通过 ctx.services["tool_dispatcher"] 获取。
        详见 tool-mcp-skill-design.md §7.3。
        """
        dispatcher = ctx.services.get("tool_dispatcher")
        if dispatcher is None:
            return None
        return dispatcher.all_tools()  # None = 不传 tools

    def _to_response(self, raw, model: str) -> LLMResponse:
        """OpenAI 原始响应 → 统一 LLMResponse"""
        choice = raw.choices[0]
        raw_tool_calls = choice.message.tool_calls or []

        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=[
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                    raw_arguments=tc.function.arguments,
                )
                for tc in raw_tool_calls
            ],
            usage=LLMUsage(
                prompt_tokens=raw.usage.prompt_tokens,
                completion_tokens=raw.usage.completion_tokens,
            ),
            finish_reason=choice.finish_reason or "error",
            model=raw.model or model,
        )
```

### 4.2 流收集器

```python
class AsyncStreamCollector:
    """
    流式数据收集器。
    逐步从 stream chunk 中累加 content + tool_calls delta，
    最终 assemble() 出完整的原始响应用于 _to_response()。
    """

    def __init__(self):
        self._content_chunks: list[str] = []
        self._tool_call_chunks: dict[int, dict] = {}
        self._usage: dict = {}

    def collect(self, chunk) -> None:
        """收集一个 chunk。"""
        delta = chunk.choices[0].delta if chunk.choices else None
        if not delta:
            # 最后一个 usage chunk
            if hasattr(chunk, "usage") and chunk.usage:
                self._usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                }
            return

        if delta.content:
            self._content_chunks.append(delta.content)

        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in self._tool_call_chunks:
                    self._tool_call_chunks[idx] = {
                        "id": "",
                        "function": {"name": "", "arguments": ""},
                    }
                tc = self._tool_call_chunks[idx]
                if tc_delta.id:
                    tc["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tc["function"]["name"] += tc_delta.function.name
                    if tc_delta.function.arguments:
                        tc["function"]["arguments"] += tc_delta.function.arguments

    def assemble(self):
        """组装为 OpenAI 原始响应格式（模拟非流式响应）。"""
        # 这里返回一个结构上兼容非流式响应的对象
        # 实际实现可以返回一个 SimpleNamespace
        ...

    @property
    def full_content(self) -> str:
        return "".join(self._content_chunks)

    @property
    def tool_calls(self) -> list[dict]:
        return [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            for tc in sorted(self._tool_call_chunks.values(), key=lambda x: x["id"])
        ]
```

### 4.3 其他 Provider 实现示例

```python
class AnthropicLLMExecutor(LLMExecutor):
    """Anthropic Claude API 实现"""

    def __init__(self, config: LLMExecutorConfig):
        # Anthropic SDK 初始化 + 消息格式转换
        ...

    async def execute(self, ctx: RuntimeContext) -> LLMResponse:
        # messages 格式转换 (OpenAI → Anthropic)
        # 调用 Anthropic API
        # 响应转换 (Anthropic → LLMResponse)
        ...
```

---

## 5. 完整数据流链路

### 5.1 全景图

```
用户输入 "帮我查下北京的天气"
    │
    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  AgentRuntime.run(user_input)                                            │
│                                                                          │
│  ── Step 1: 用户消息入库 ──                                              │
│  ctx.messages.append({"role": "user", "content": user_input})            │
│                                                                          │
│  ┌─ Step Loop ──────────────────────────────────────────────────────┐    │
│  │                                                                   │    │
│  │  [before_step]       Transform: MemoryRecallHook                  │    │
│  │    ctx.contextPayload.memories = memory.recall(session_id, ...)    │    │
│  │    ctx.contextPayload.tone_instruction = pattern.communication     │    │
│  │    ctx.contextPayload.entity_profile = entity.read("user", ...)    │    │
│  │                                                                   │    │
│  │  [before_step]       Intercept: BudgetControl                     │    │
│  │    检查 ctx.budget.stepCount < stepLimit → allow / block          │    │
│  │                                                                   │    │
│  │  [Router._next()]    → return "llm_step"                          │    │
│  │                                                                   │    │
│  │  ── LLM 调用段 ──                                                 │    │
│  │                                                                   │    │
│  │  [before_llm]        Transform: ContextAssembly                   │    │
│  │    ctx.contextPayload.injectedContext = assemble(query, ...)       │    │
│  │                                                                   │    │
│  │  [before_llm]        Transform: RAGRetrieval                      │    │
│  │    ctx.contextPayload.ragDocuments = rag.search(query)            │    │
│  │                                                                   │    │
│  │  [before_llm]        Transform: TokenManager                      │    │
│  │    裁剪 ctx.contextPayload.* 各字段至 budget 内                    │    │
│  │                                                                   │    │
│  │  [before_llm]        Intercept: InputGuardrails                   │    │
│  │    读 ctx.messages[-1]（用户消息）→ 安检 → allow                  │    │
│  │                                                                   │    │
│  │  [before_llm]        Intercept: RateLimiting                      │    │
│  │    查询配额 → 有配额 → allow                                      │    │
│  │                                                                   │    │
│  │  ═══════════════ Runtime: serialize() ═══════════════            │    │
│  │  messages[0] = serialize_context_payload(ctx.contextPayload)      │    │
│  │    ├─ system prompt 模板                                           │    │
│  │    ├─ tone_instruction（来自行为模式）                              │    │
│  │    ├─ entity_profile（来自实体画像）                                │    │
│  │    ├─ 记忆摘要 N 条（来自情景记忆，已裁剪）                         │    │
│  │    ├─ RAG 文档 K 条（来自 RAG 检索，已裁剪）                        │    │
│  │    └─ injected_context（来自其他 Transform）                       │    │
│  │  messages[1..] = ctx.messages[1..]（历史对话，不变）               │    │
│  │                                                                   │    │
│  │  ═══════════════ llm_executor.execute(ctx) ═══════════════       │    │
│  │  read:   ctx.messages（已序列化的完整数组）                         │    │
│  │  call:   OpenAI / Claude / ... API(messages, tools=tools_schema)  │    │
│  │  return: LLMResponse = {                                          │    │
│  │    content: "北京的天气是晴天，24°C",                              │    │
│  │    tool_calls: [ToolCall(name="get_weather", args={...})],        │    │
│  │    usage: { prompt_tokens: 520, completion_tokens: 30 },          │    │
│  │    finish_reason: "tool_calls",                                   │    │
│  │  }                                                                │    │
│  │                                                                   │    │
│  │  ═══════════════ Runtime 接管返回值 ═══════════════              │    │
│  │  ctx.messages.append({                                            │    │
│  │    role: "assistant",                                             │    │
│  │    content: "北京的天气是晴天，24°C",                              │    │
│  │    tool_calls: [{ id: "call_1", name: "get_weather", ... }],     │    │
│  │  })                                                               │    │
│  │  ctx.budget.tokenUsed += 550                                      │    │
│  │                                                                   │    │
│  │  [after_llm]        Intercept: OutputGuardrails                   │    │
│  │    读 ctx.messages[-1] → 校验 → allow                             │    │
│  │                                                                   │    │
│  │  [after_llm]        Intercept: Groundedness                       │    │
│  │    事实检查 → allow                                                │    │
│  │                                                                   │    │
│  │  [after_llm]        Observe: Tracing / Audit                      │    │
│  │    写 OpenTelemetry span + 审计日志                                │    │
│  │                                                                   │    │
│  │  ── Tool 调用段（因为 finish_reason == "tool_calls"）──           │    │
│  │                                                                   │    │
│  │  [before_tool]      Intercept: ToolGuardrails                     │    │
│  │    检查 get_weather 参数 → allow                                   │    │
│  │                                                                   │    │
│  │  [Tool Execute]     get_weather(city="北京") → {温度: 24, 天气:晴}│    │
│  │                                                                   │    │
│  │  Runtime: ctx.messages.append({role:"tool", content:"{...}"})     │    │
│  │                                                                   │    │
│  │  [after_tool]       Transform: BudgetControl                      │    │
│  │    ctx.budget.tokenUsed += tool_token_cost                         │    │
│  │                                                                   │    │
│  │  ── Step 结束 ──                                                  │    │
│  │                                                                   │    │
│  │  [after_step]       Transform: MemoryCommitHook                   │    │
│  │    gate.evaluate(user_msg, assistant_msg) → should_record=True     │    │
│  │    memory.commit(session_id, user_id, step_context)                │    │
│  │      → Layer 2: 写入情景记忆                                      │    │
│  │      → Layer 3: 异步提取实体并 upsert                              │    │
│  │      → Layer 5: 行为模式采样                                       │    │
│  │                                                                   │    │
│  │  [after_step]       Transform: Replan (如需)                      │    │
│  │    ctx.setPlan(new_plan)                                           │    │
│  │                                                                   │    │
│  │  Runtime: ctx.budget.stepCount++                                   │    │
│  │                                                                   │    │
│  │  [Router._next()]    → finish_reason="stop" → 结束循环            │    │
│  │                                                                   │    │
│  └───────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  返回: ctx.messages[-1].content → "北京的天气是晴天，24°C"               │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
    │
    ▼
用户看到: "北京的天气是晴天，24°C"
```

### 5.2 按角色职责分离

| 环节 | 角色 | 读写什么 |
|------|------|---------|
| `before_step` | Transform (Memory) | **写** `ctx.contextPayload.memories, .tone_instruction, .entity_profile` |
| `before_llm` | Transform (Context/RAG/Token) | **读** `ctx.contextPayload`，**写** `.ragDocuments, .injectedContext`，**裁剪** `.memories` |
| `before_llm` | Intercept (Guardrails) | **读** `ctx.messages[-1]`，return allow/block |
| **`Runtime`** | serialize() | **读** `ctx.contextPayload` 所有字段，**写** `messages[0]` |
| **`llm_executor`** | Execute | **读** `ctx.messages`，return `LLMResponse` |
| **`Runtime`** | 后处理 | **读** `LLMResponse`，**写** `ctx.messages.append(response)` + `ctx.budget.tokenUsed` |
| `after_llm` | Intercept (Guardrails) | **读** `ctx.messages[-1]`，return allow/block/modified |
| `after_llm` | Observe (Tracing) | **读** `ctx` 全部字段（只读） |
| `after_step` | Transform (Memory) | **读** `ctx.messages[-2:]`，**写** 外部持久化存储 |
| `after_step` | Router (Replan) | **读** `ctx.plan` + recent steps，**写** `ctx.plan`（如需） |

### 5.3 关键数据流动画（按时间序）

```
时间 →
──────

ctx.messages          ctx.contextPayload          外部持久化
─────────────────     ────────────────────        ───────────
                      {}                           SQLite DB
                                                      │
① user入栈: [{user}]  {}                              │
                                                      │
② before_step:       {memories: [...],               │
  MemoryRecall         tone: "..."} ←──── memory.recall()
                                                      │
③ before_llm:        {memories: [...],               │
  RAG                  ragDocs: [...],                │
                       tone: "..."}                   │
                                                      │
④ before_llm:        {memories: [裁剪后],             │
  TokenManager         ragDocs: [裁剪后],             │
                       tone: "..."}                   │
                                                      │
⑤ serialize():                                       │
  messages[0] = system prompt（含记忆+语气+RAG）       │
  messages[1] = {user}                                │
                                                      │
⑥ llm_executor:                                      │
  读 messages → LLM API                              │
  return LLMResponse                                  │
                                                      │
⑦ Runtime后处理:                                      │
  messages追加:                                       │
  [{system},{user},{assistant+tool_calls}]            │
                                                      │
⑧ after_tool后:                                      │
  messages追加:                                       │
  [{system},{user},{assistant},{tool}]                │
                                                      │
⑨ after_step:                                        │
  MemoryCommit                            ────→ episodic.write()
                                              ──→ entity.upsert()
                                                      │
⑩ Router._next() → stop                               │
                                                      │
返回 messages[-1].content 给用户
```

### 5.4 Hook 通信矩阵

```
                读 contextPayload    写 contextPayload    读 messages    写 messages    return 阻断
                ─────────────────    ─────────────────    ───────────    ───────────    ────────────
before_step     —                    memories, tone       —              —              —
  Transform                          entity_profile

before_llm      memories, tone,      ragDocuments,        messages[-1]   —              allow/block
  Transform      entity_profile       injectedContext      (用户消息)
                  （读已有，继续加）     （裁剪也是写）

before_llm      —                    —                     messages[-1]   —              allow/block
  Intercept                                                   (用户消息)

── serialize: 读全部 contextPayload → 写 messages[0] ──

llm_executor    —                    —                     messages 全量  —              return LLMResponse
                                                           [0..n]

── Runtime: 读 LLMResponse → 写 messages.append + budget ──

after_llm       —                    —                     messages[-1]   —              allow/block/modified
  Intercept                                                   (assistant)

after_step      —                    —                     messages[-2:]  —              —
  Transform                                                   (user+assistant)
```

---

## 6. 外部 API 设计

### 6.1 设计目标

外部 API 是 Runtime 与外界（用户、服务、其他系统）的边界，需要解决三个问题：

1. **输入**：外部如何把消息发给 Runtime
2. **输出**：Runtime 如何把回复返回给外部
3. **生命周期**：Session 的创建、暂停、恢复、销毁

### 6.2 核心接口

```python
class AgentRuntime:
    """
    Agent Runtime 外部接口。

    使用方式:
      runtime = AgentRuntime(session_id="s1", agent_id="a1", ...)
      result = await runtime.run("帮我查天气")
      print(result.content)
    """

    def __init__(
        self,
        session_id: str,
        agent_id: str,
        llm_executor: LLMExecutor,
        tool_executor: ToolExecutor,
        services: dict[str, Any] | None = None,
        hooks: HookRegistry | None = None,
    ):
        ...

    # ── 核心入口 ──

    async def run(
        self,
        user_input: str,
        *,
        user_id: str | None = None,
        attachments: list[Attachment] | None = None,
    ) -> "RunResult":
        """
        同步式入口：用户输入 → Runtime 处理 → 完整回复。

        内部执行的完整链路:
          (参见第 5 节: 用户 message → before_step → before_llm
                         → llm_executor → after_llm → [tool 循环]
                         → after_step → 返回)

        返回:
          RunResult: 助理回复 + 完整会话上下文
        """
        # 1. 用户消息入栈
        self._ctx.messages.append({
            "role": "user",
            "content": user_input,
            "attachments": attachments or [],
        })

        # 2. 驱动 Step Loop（见第 5 节完整链路）
        await self._step_loop()

        # 3. 收集结果返回
        return self._collect_result()

    # ── 流式入口 ──

    async def run_stream(
        self,
        user_input: str,
        *,
        user_id: str | None = None,
        attachments: list[Attachment] | None = None,
    ) -> AsyncIterator["StreamEvent"]:
        """
        流式入口：用户输入 → Runtime 处理 → 逐块推送。

        产出 StreamEvent 序列:
          StreamEvent(type="text", content="北京")
          StreamEvent(type="text", content="的天气")
          StreamEvent(type="tool_start", name="get_weather")
          StreamEvent(type="tool_end",   name="get_weather")
          StreamEvent(type="done", result=RunResult(...))

        使用方式:
          async for event in runtime.run_stream("帮我查天气"):
              if event.type == "text":
                  print(event.content, end="")
        """
        ...

    # ── 会话控制 ──

    async def resume(self, resume_token: str, approval: bool = True) -> "RunResult":
        """
        恢复暂停的会话（Human approval 恢复）。
        """
        ...

    async def destroy(self):
        """
        销毁会话。触发 session_end hooks（评估、审计、清理）。
        """
        ...

    @property
    def status(self) -> RuntimeStatus:
        ...

    def get_session_state(self) -> "SessionSnapshot":
        """当前会话快照（调试/监控用）"""
        ...
```

### 6.3 数据模型

```python
@dataclass
class RunResult:
    """run() 的返回结果"""
    content: str                         # 助理文本回复
    session_id: str                      # 会话 ID
    messages: list[dict]                 # 完整对话历史
    tool_calls: list[ToolCall]           # 本轮调用的工具
    usage: LLMUsage                      # 本轮累计 token
    finish_reason: str                   # "stop" | "tool_calls" | "length"


@dataclass
class StreamEvent:
    """流式事件"""
    type: str                            # "text" | "tool_start" | "tool_end" | "error" | "done"
    content: str | None                  # 文本片段
    name: str | None                     # 工具名
    error: str | None                    # 错误信息
    metadata: dict | None                # 附加信息


@dataclass
class SessionSnapshot:
    """会话快照"""
    session_id: str
    status: RuntimeStatus
    step_count: int
    message_count: int
    total_tokens: int
    duration_seconds: float
    last_error: str | None
```

### 6.4 集成模式

#### FastAPI Web 服务

```python
from fastapi import FastAPI, StreamingResponse
from pydantic import BaseModel

app = FastAPI()

class ChatRequest(BaseModel):
    message: str
    session_id: str
    user_id: str | None = None

@app.post("/chat")
async def chat(req: ChatRequest, runtime: AgentRuntime):
    result = await runtime.run(req.message, user_id=req.user_id)
    return {"content": result.content, "session_id": result.session_id}

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, runtime: AgentRuntime):
    async def event_stream():
        async for event in runtime.run_stream(req.message):
            if event.type == "text":
                yield f"data: {json.dumps({'text': event.content})}\n\n"
            elif event.type == "done":
                yield f"data: {json.dumps({'done': True})}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

#### CLI 交互

```python
async def cli():
    runtime = AgentRuntime(session_id=str(uuid4()), ...)
    while True:
        user_input = input("> ")
        if user_input.lower() == "exit":
            await runtime.destroy(); break
        result = await runtime.run(user_input)
        print(f"Agent: {result.content}")
```

### 6.5 多轮会话管理

Runtime 内部持有 `ctx.messages`，外部调用方只需持续调 `run()`：

```python
runtime = AgentRuntime(session_id="s1", ...)

result1 = await runtime.run("我的名字是张三")
# messages: [{user}, {assistant: "好的张三！"}]

result2 = await runtime.run("我叫什么名字？")
# messages: [{user}, {assistant}, {user}, {assistant: "您叫张三"}]
# ↑ Runtime 记住了历史
```

### 6.6 外部 API → 内部链路的完整映射

```
run("你好")
    │
    └─→ ctx.messages.append({role:"user", content:"你好"})
         │
         ▼
       [before_step]  →  MemoryRecall 写 contextPayload
       [before_llm]    →  各 Transform/Intercept
       [serialize]     →  contextPayload → messages[0]
       [llm_executor]  →  return LLMResponse
       [Runtime]       →  messages.append({role:"assistant", ...})
       [after_llm]     →  各 Intercept/Observe
       [after_step]    →  MemoryCommit 写外部存储
       [Router]        →  finish_reason="stop"
         │
         ▼
    return RunResult(content="你好！", messages=[...], usage=...)
```

---

## 7. 流式支持

### 6.1 流式数据流

```
llm_executor.execute_stream(ctx)
    │
    ├─ 初始化 stream = openai.chat.completions.create(stream=True)
    │
    ├─ Step Loop 逐个处理 chunk:
    │     for each chunk in stream:
    │       collector.collect(chunk)                     ← 收集数据
    │       [onStreamChunk] Observe/Transform(chunk, ctx) ← Hook 点
    │
    ├─ 流结束后:
    │     response = collector.assemble()
    │     return collector, response
    │
    └─ Runtime 使用 collector 逐 chunk 返回给前端
       Runtime 使用 response 写 messages 和 after_llm 校验
```

### 6.2 流式 Hook 点

```python
class AgentRuntime:
    def on_stream_chunk(self, observer: Observer): ...
    def on_stream_chunk(self, transformer: Transformer[StreamChunk]): ...
```

用途：
- **Observe**：前端推送（逐字显示）
- **Transform**：实时修改流内容（脱敏、过滤）

---

## 8. 错误与重试

### 7.1 错误分类

```
LLM API 错误
    ├── 可重试（瞬态）
    │     ├─ APITimeoutError    → 重试
    │     ├─ RateLimitError     → 退避后重试
    │     └─ InternalServerError → 重试
    │
    ├── 不可重试（立即失败）
    │     ├─ AuthenticationError  → 密钥问题，不应重试
    │     ├─ BadRequestError      → 请求格式错，不应重试
    │     └─ ContextLengthExceeded → Token 超限，需要裁剪后重试
    │
    └── 非 LLM 错误
          ├─ ctx 快照过期（并发问题）
          └─ messages 格式不合法
```

### 7.2 重试策略

```python
@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff_base: float = 1.0        # 指数退避基数
    backoff_max: float = 30.0        # 最大退避秒数
    retryable_errors: tuple = (
        APITimeoutError,
        RateLimitError,
        InternalServerError,
    )


class OpenAILLMExecutor(LLMExecutor):
    async def execute(self, ctx: RuntimeContext) -> LLMResponse:
        for attempt in range(self._config.max_retries + 1):
            try:
                return await self._do_execute(ctx)
            except self._retryable_errors as e:
                if attempt == self._config.max_retries:
                    raise LLMExecutionError(
                        last_error=e,
                        consecutive_errors=ctx.error_state.consecutive_errors,
                    )
                await asyncio.sleep(self._backoff(attempt))
                continue

    def _backoff(self, attempt: int) -> float:
        return min(
            self._config.retry_backoff_base * (2 ** attempt),
            self._config.retry_backoff_max,
        )
```

### 7.3 错误传播路径

```
llm_executor 内部重试耗尽
    │
    ├─ raise LLMExecutionError
    │
    └─ Runtime 捕获 → [on_error] Hook
          │
          ├─ Error Intercept: 决定 retry / skip / escalate
          ├─ Error Router: 决定 next_step_id
          └─ ctx.errorState.consecutiveErrors += 1
                ctx.errorState.lastError = error
```

---

## 9. 测试策略

### 8.1 单元测试

```python
class TestOpenAILLMExecutor:
    """使用 mock LLM Provider，不调用真实 API"""

    async def test_basic_text_response(self):
        """正常文本回复"""
        executor = OpenAILLMExecutor(config, client=mock_client)
        response = await executor.execute(ctx_with_user_message)
        assert response.content == "expected content"
        assert response.tool_calls == []
        assert response.finish_reason == "stop"

    async def test_tool_call_response(self):
        """LLM 请求工具调用"""
        executor = OpenAILLMExecutor(config, client=mock_client)
        response = await executor.execute(ctx_with_user_message)
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"

    async def test_retry_on_timeout(self):
        """超时后重试成功"""
        mock_client = MockClient(
            side_effect=[APITimeoutError(), valid_response()]
        )
        executor = OpenAILLMExecutor(config, client=mock_client)
        response = await executor.execute(ctx)
        assert response.content == "最终成功"

    async def test_retry_exhausted(self):
        """重试耗尽后抛出异常"""
        mock_client = MockClient(side_effect=APITimeoutError())
        executor = OpenAILLMExecutor(config, client=mock_client)
        with pytest.raises(LLMExecutionError):
            await executor.execute(ctx)
```

### 8.2 集成测试

```python
class TestLLMExecutorIntegration:
    """使用真实 LLM API（需配置 API Key）"""

    async def test_openai_real_call(self):
        """真实调用 GPT-4o-mini，验证往返"""
        executor = OpenAILLMExecutor(LLMExecutorConfig(
            model="gpt-4o-mini",
            api_key=os.environ["OPENAI_API_KEY"],
        ))
        ctx = create_test_context(messages=[
            {"role": "system", "content": "你是一个助手"},
            {"role": "user", "content": "说'hello'"},
        ])
        response = await executor.execute(ctx)
        assert "hello" in response.content.lower()
```

### 8.3 全链路测试

```python
class TestFullChain:
    """
    完整的 Runtime → Hook → LLMExecutor → Runtime 链路。

    使用 mock LLMExecutor 替换真实 LLM，测试治理组件的协同。
    """

    async def test_guardrails_block_then_recover(self):
        """输入护栏 block → on_error → 重试 → 成功"""
        runtime = AgentRuntime(
            llm_executor=MockLLMExecutor(),
            hooks=[InputGuardrails(), ErrorRecoveryHook()],
        )
        result = await runtime.run("恶意输入")
        # 验证: block → error → retry → success
        ...

    async def test_memory_recall_before_llm(self):
        """MemoryRecall 在 before_step 写入 contextPayload，
           serialize() 将其合并到 system message，
           llm_executor 收到包含记忆的 messages"""
        ...

    async def test_memory_commit_after_step(self):
        """MemoryCommit 在 after_step 读取 messages[-2:]，
           写入外部存储"""
        ...
```

---

## 10. 附录：文件清单

```
docs/llm-executor-design.md           ← 本文档
docs/agent-runtime-design.md           ← 父文档：Runtime 架构
docs/memory-system-design.md           ← 父文档：记忆系统

src/llm/
├── __init__.py                        # 导出 LLMExecutor, LLMResponse, ...
├── _interfaces.py                     # LLMExecutor 抽象基类
├── _models.py                         # LLMResponse, ToolCall, LLMUsage, LLMMessage
├── _config.py                         # LLMExecutorConfig
├── _providers/
│   ├── __init__.py
│   ├── _base.py                       # LLMProvider 抽象接口
│   ├── _openai.py                     # OpenAI SDK 适配
│   └── _anthropic.py                  # Anthropic SDK 适配
├── _executors/
│   ├── __init__.py
│   ├── _openai.py                     # OpenAILLMExecutor
│   ├── _anthropic.py                  # AnthropicLLMExecutor
│   └── _stream.py                     # AsyncStreamCollector
├── _errors.py                         # LLMExecutionError
└── _retry.py                          # RetryPolicy
```
