"""LLM Provider abstraction layer.

设计文档: llm-executor-design.md §3.3
目的：隔离不同 LLM SDK 的差异，使 LLMExecutor 不依赖具体 SDK。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from openai import AsyncOpenAI


# ═══════════════════════════════════════════════════════════════
#  Data Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class LLMProviderResponse:
    """Provider 原始响应的统一包装。

    设计文档: llm-executor-design.md §3.3
    将不同 provider 的原始响应格式化为统一结构。
    """

    content: str
    tool_calls: list[dict] | None = None  # provider 原始格式
    usage: dict = field(default_factory=dict)  # provider 原始格式
    finish_reason: str = "stop"
    model: str = ""


# ═══════════════════════════════════════════════════════════════
#  Abstract Interface
# ═══════════════════════════════════════════════════════════════


class LLMProvider(ABC):
    """LLM Provider 适配器接口。

    设计文档: llm-executor-design.md §3.3
    隔离不同 LLM SDK 的差异，使 LLMExecutor 不依赖具体 SDK。
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> LLMProviderResponse | AsyncIterator[dict]:
        """调用 LLM API。

        返回 LLMProviderResponse（非流式）或 AsyncIterator[dict]（流式）。
        """
        ...


# ═══════════════════════════════════════════════════════════════
#  OpenAI Provider 实现
# ═══════════════════════════════════════════════════════════════


class OpenAIProvider(LLMProvider):
    """OpenAI / OpenAI-compatible API 的 Provider 实现。

    支持:
      - GPT-4o / GPT-4 / GPT-3.5 / DeepSeek / Qwen 等兼容 API
      - Function calling / tool_calls
      - 流式与非流式
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        timeout: float = 120.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "api_key": api_key or None,
            "base_url": api_base or None,
            "timeout": timeout,
        }
        if extra_headers:
            kwargs["extra_headers"] = extra_headers
        self._client = AsyncOpenAI(**kwargs)

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> LLMProviderResponse | AsyncIterator[dict]:
        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            create_kwargs["tools"] = tools
        if stream:
            create_kwargs["stream"] = True
            create_kwargs["stream_options"] = {"include_usage": True}

        if stream:
            return self._stream_chat(create_kwargs)

        raw = await self._client.chat.completions.create(**create_kwargs)
        return self._to_provider_response(raw)

    async def _stream_chat(self, kwargs: dict[str, Any]) -> AsyncIterator[dict]:
        """Streaming chat: yields raw dict chunks."""
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            yield chunk  # type: ignore[misc]

    def _to_provider_response(self, raw: Any) -> LLMProviderResponse:  # noqa: ANN401
        """Convert OpenAI raw response to LLMProviderResponse."""
        choice = raw.choices[0]
        content = choice.message.content or ""

        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]

        usage = {}
        if raw.usage:
            usage = {
                "prompt_tokens": getattr(raw.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(raw.usage, "completion_tokens", 0),
            }

        return LLMProviderResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
            model=getattr(raw, "model", ""),
        )

    @property
    def client(self) -> AsyncOpenAI:
        """暴露底层 client，用于测试和特殊场景。"""
        return self._client
