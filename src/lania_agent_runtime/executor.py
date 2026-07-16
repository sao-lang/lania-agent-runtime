"""LLM Executor - Execute primitive for LLM calls.

Supports OpenAI-compatible APIs (DeepSeek, OpenAI, etc.)
with streaming and non-streaming modes.
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.models import LLMExecutorConfig, LLMResponse, LLMUsage, ToolCall
from lania_agent_runtime.provider import LLMProvider, OpenAIProvider


# ═══════════════════════════════════════════════════════════════
#  Custom Errors
# ═══════════════════════════════════════════════════════════════


class LLMExecutionError(RuntimeError):
    """Raised when LLM execution fails after exhausting retries."""

    def __init__(
        self,
        message: str = "",
        *,
        last_error: Exception | None = None,
        consecutive_errors: int = 0,
        model: str = "",
    ) -> None:
        self.last_error = last_error
        self.consecutive_errors = consecutive_errors
        self.model = model
        super().__init__(message or f"LLM call failed (model={model})")


# ═══════════════════════════════════════════════════════════════
#  Async Stream Collector
# ═══════════════════════════════════════════════════════════════


class AsyncStreamCollector:
    """
    Accumulates streaming chunks from an OpenAI-compatible stream.

    Collects content chunks, tool call deltas, and usage info,
    then can assemble() into a mock response object compatible
    with `_to_response()`.
    """

    def __init__(self) -> None:
        self._content_chunks: list[str] = []
        self._tool_call_chunks: dict[int, dict[str, Any]] = {}
        self._usage: dict[str, int] = {}

    def collect(self, chunk: Any) -> None:  # noqa: ANN401
        """Collect a single streaming chunk."""
        if not chunk.choices:
            # Usage-only chunk (final)
            if hasattr(chunk, "usage") and chunk.usage:
                self._usage = {
                    "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(chunk.usage, "completion_tokens", 0),
                }
            return

        delta = chunk.choices[0].delta
        if not delta:
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

    @property
    def full_content(self) -> str:
        """Get the complete accumulated text content."""
        return "".join(self._content_chunks)

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        """Get assembled tool calls in OpenAI-compatible format."""
        return [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            for tc in sorted(
                self._tool_call_chunks.values(),
                key=lambda x: x.get("id", ""),
            )
        ]

    @property
    def usage(self) -> dict[str, int]:
        """Get token usage."""
        return dict(self._usage)

    def assemble(self) -> Any:  # noqa: ANN401
        """Assemble into a mock OpenAI response compatible with _to_response()."""
        from types import SimpleNamespace

        tc_list = self.tool_calls
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=self.full_content,
                        tool_calls=[
                            SimpleNamespace(
                                id=tc["id"],
                                function=SimpleNamespace(
                                    name=tc["function"]["name"],
                                    arguments=tc["function"]["arguments"],
                                ),
                            )
                            for tc in tc_list
                        ] if tc_list else [],
                    ),
                    finish_reason="tool_calls" if tc_list else "stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=self._usage.get("prompt_tokens", 0),
                completion_tokens=self._usage.get("completion_tokens", 0),
            ),
            model="",
        )


# ═══════════════════════════════════════════════════════════════
#  Abstract Base
# ═══════════════════════════════════════════════════════════════


class LLMExecutorBase(ABC):
    """
    Abstract base class for LLM executors.

    设计文档: llm-executor-design.md §2.1
    All concrete executors must implement ``execute()``.
    Streaming-capable executors implement ``execute_stream()``
    returning ``(AsyncStreamCollector, LLMResponse)``.
    """

    @abstractmethod
    async def execute(self, ctx: RuntimeContext) -> LLMResponse:
        """Execute non-streaming LLM call."""
        ...

    async def execute_stream(
        self, ctx: RuntimeContext,
    ) -> tuple[AsyncStreamCollector, LLMResponse]:
        """Execute streaming LLM call.

        设计文档: llm-executor-design.md §2.2
        统一返回 (collector, response) 元组.
        """
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════
#  OpenAI Executor
# ═══════════════════════════════════════════════════════════════


class LLMExecutor(LLMExecutorBase):
    """LLM Executor using OpenAI-compatible API.

    设计文档: llm-executor-design.md §4.1
    内部构造 ``AsyncOpenAI`` 客户端(config.api_key / config.api_base),
    或通过 provider / client 参数注入。

    支持:
      - Non-streaming and streaming execution
      - Tool/function calling
      - Exponential backoff retry with configurable timeout
    """

    def __init__(
        self,
        config: LLMExecutorConfig | None = None,
        *,
        client: AsyncOpenAI | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self._config = config or LLMExecutorConfig()
        self._provider = provider

        if client is not None:
            # 向后兼容: 外部注入 client (测试/迁移场景)
            self._client = client
        elif provider is not None:
            # 通过 Provider 抽象获取底层 client
            if isinstance(provider, OpenAIProvider):
                self._client = provider.client
            else:
                self._client = AsyncOpenAI(
                    api_key=self._config.api_key or None,
                    base_url=self._config.api_base or None,
                    timeout=self._config.timeout,
                )
        else:
            # 设计文档 §4.1: 从 config 内部构造 AsyncOpenAI 客户端
            kwargs: dict[str, Any] = {
                "api_key": self._config.api_key or None,
                "base_url": self._config.api_base or None,
                "timeout": self._config.timeout,
            }
            if self._config.extra_headers:
                kwargs["extra_headers"] = self._config.extra_headers
            self._client = AsyncOpenAI(**kwargs)

    # ── Public API ──

    async def execute(self, ctx: RuntimeContext) -> LLMResponse:
        """Execute non-streaming LLM call with timeout and retry."""
        messages = self._extract_messages(ctx)
        params = self._merge_params(ctx)
        tools_schema = self._get_tools_schema(ctx)

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                kwargs = self._build_kwargs(params, messages, tools_schema)
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(**kwargs),
                    timeout=self._config.timeout,
                )
                return self._to_response(response, params.model)

            except (APITimeoutError, APIError, RateLimitError) as e:
                last_error = e
                if attempt < self._config.max_retries:
                    backoff = min(
                        self._config.retry_backoff_base * (2**attempt),
                        self._config.retry_backoff_max,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise LLMExecutionError(
                    message=(
                        f"LLM call failed after {self._config.max_retries} retries: {e}"
                    ),
                    last_error=last_error,
                    consecutive_errors=ctx.error_state.consecutive_errors,
                    model=params.model,
                ) from last_error

    async def execute_stream(
        self, ctx: RuntimeContext,
    ) -> tuple[AsyncStreamCollector, LLMResponse]:
        """Execute streaming LLM call.

        设计文档: llm-executor-design.md §2.2
        统一返回 (collector, response) — 收集全部 chunk 后组装完整响应.
        """
        messages = self._extract_messages(ctx)
        params = self._merge_params(ctx)
        tools_schema = self._get_tools_schema(ctx)

        kwargs = self._build_kwargs(params, messages, tools_schema, stream=True)
        collector = AsyncStreamCollector()

        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            collector.collect(chunk)

        assembled = collector.assemble()
        assembled.model = params.model
        response = self._to_response(assembled, params.model)
        return collector, response

    # 向后兼容别名
    async def execute_stream_collected(
        self, ctx: RuntimeContext,
    ) -> tuple[AsyncStreamCollector, LLMResponse]:
        """Deprecated: use execute_stream() instead."""
        return await self.execute_stream(ctx)

    # ── Internal methods ──

    def _build_kwargs(
        self,
        params: LLMExecutorConfig,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]] | None,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Build the keyword arguments for the OpenAI API call."""
        kwargs: dict[str, Any] = {
            "model": params.model,
            "messages": messages,
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
        }
        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
        if tools_schema:
            kwargs["tools"] = tools_schema
        if self._config.extra_headers:
            kwargs["extra_headers"] = self._config.extra_headers
        return kwargs

    def _extract_messages(self, ctx: RuntimeContext) -> list[dict[str, Any]]:
        """Extract messages from context."""
        return ctx.serialize_messages()

    def _serialize_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Serialize a single message to OpenAI API format."""
        d: dict[str, Any] = {"role": msg.get("role", "user")}
        if msg.get("content"):
            d["content"] = msg["content"]
        if msg.get("tool_calls"):
            d["tool_calls"] = [
                self._serialize_tool_call(tc) for tc in msg["tool_calls"]
            ]
        if msg.get("tool_call_id"):
            d["tool_call_id"] = msg["tool_call_id"]
            d["content"] = msg.get("content", "")
        return d

    def _serialize_tool_call(self, tc: dict[str, Any]) -> dict[str, Any]:
        """Serialize a single tool call to OpenAI function format."""
        tc_id = tc.get("id", "")
        function_info = tc.get("function", {})
        name = tc.get("name", function_info.get("name", ""))
        raw_args = tc.get("arguments", function_info.get("arguments", {}))
        if isinstance(raw_args, dict):
            raw_args = json.dumps(raw_args)
        return {
            "id": tc_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": raw_args,
            },
        }

    def _merge_params(self, ctx: RuntimeContext) -> LLMExecutorConfig:
        """Merge context config over base config.

        设计文档: llm-executor-design.md §4.1
        优先使用 ctx.llm_config 中的覆盖值, 回退到 self._config.
        """
        ctx_cfg = ctx.llm_config
        if ctx_cfg is None:
            return LLMExecutorConfig(
                model=self._config.model,
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                timeout=self._config.timeout,
                max_retries=self._config.max_retries,
                retry_backoff_base=self._config.retry_backoff_base,
                retry_backoff_max=self._config.retry_backoff_max,
            )
        return LLMExecutorConfig(
            model=ctx_cfg.model or self._config.model,
            temperature=ctx_cfg.temperature if ctx_cfg.temperature != 0.7 else self._config.temperature,  # noqa: E501
            max_tokens=ctx_cfg.max_tokens or self._config.max_tokens,
            timeout=ctx_cfg.timeout or self._config.timeout,
            max_retries=ctx_cfg.max_retries or self._config.max_retries,
            retry_backoff_base=ctx_cfg.retry_backoff_base or self._config.retry_backoff_base,
            retry_backoff_max=ctx_cfg.retry_backoff_max or self._config.retry_backoff_max,
        )

    def _get_tools_schema(self, ctx: RuntimeContext) -> list[dict[str, Any]] | None:
        """Get tool schemas from context."""
        return ctx.tools_schema

    def _to_response(self, raw: Any, model: str) -> LLMResponse:  # noqa: ANN401
        """Convert OpenAI raw response to LLMResponse."""
        choice = raw.choices[0]
        raw_tool_calls = choice.message.tool_calls or []

        tool_calls = []
        for tc in raw_tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, AttributeError, TypeError):
                args = {}
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                    raw_arguments=tc.function.arguments,
                )
            )

        usage = LLMUsage()
        if raw.usage:
            usage.prompt_tokens = getattr(raw.usage, "prompt_tokens", 0)
            usage.completion_tokens = getattr(raw.usage, "completion_tokens", 0)

        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
            model=getattr(raw, "model", model),
        )
