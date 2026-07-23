"""
OpenAI Provider 实现——OpenAIProvider。

基于 openai.AsyncOpenAI SDK 实现 LLMProvider 接口。
支持：
  - GPT-4o / GPT-4 / GPT-3.5 / DeepSeek / Qwen 等兼容 API
  - Function calling / tool_calls
  - 流式与非流式
  - 自定义 base_url 和 extra_headers
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from src.runtime.llm._providers._base import LLMProvider, LLMProviderResponse


class OpenAIProvider(LLMProvider):
    """OpenAI / OpenAI-compatible API 的 Provider 适配。

    将 OpenAI SDK 的调用封装为统一的 LLMProvider 接口，
    使 LLMExecutor 不直接依赖 OpenAI SDK 的类型。

    Attributes:
        _client: AsyncOpenAI 客户端实例。
        _default_model: 默认模型名。
    """

    # OpenAI SDK 中可重试的异常类型
    RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
        APITimeoutError,
        RateLimitError,
        APIError,
    )

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        timeout: float = 60.0,
        max_retries: int = 0,
        extra_headers: dict[str, str] | None = None,
        default_model: str = "gpt-4o",
    ) -> None:
        """初始化 OpenAIProvider。

        Args:
            api_key: OpenAI API 密钥。
            api_base: 自定义 base URL（用于兼容 API）。
            timeout: 请求超时秒数。
            max_retries: SDK 内置重试次数（默认 0，由 LLMExecutor 控制重试）。
            extra_headers: 额外的 HTTP 请求头。
            default_model: 默认模型名。
        """
        self._default_model = default_model
        self._client = AsyncOpenAI(
            api_key=api_key or None,
            base_url=api_base or None,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=extra_headers,
        )

    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> LLMProviderResponse | AsyncIterator[dict]:
        """调用 OpenAI Chat Completion API。

        Args:
            messages: 符合 OpenAI API 格式的消息列表。
            model: 模型名称（为空时使用 default_model）。
            temperature: 采样温度。
            max_tokens: 最大输出 token 数。
            tools: 工具的 JSON Schema 列表。
            stream: 是否启用流式模式。
            kwargs: 额外参数传给 OpenAI API（如 response_format, stop 等）。

        Returns:
            stream=False 时返回 LLMProviderResponse；
            stream=True 时返回 AsyncIterator[dict]，每项为一个 chunk。

        Raises:
            APITimeoutError: 请求超时。
            RateLimitError: 触发限流。
            APIError: 其他 API 错误。
        """
        params: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }
        if tools:
            params["tools"] = tools

        if stream:
            return self._stream_chat(params)

        response = await self._client.chat.completions.create(**params)
        return self._to_provider_response(response)

    async def _stream_chat(self, params: dict[str, Any]) -> AsyncIterator[dict]:
        """流式调用——逐 chunk 产出字典。

        Args:
            params: API 请求参数。

        Yields:
            每个 chunk 的字典表示。
        """
        params["stream"] = True
        params["stream_options"] = {"include_usage": True}

        stream = await self._client.chat.completions.create(**params)
        async for chunk in stream:
            yield chunk.to_dict()

    def _to_provider_response(self, response: Any) -> LLMProviderResponse:
        """OpenAI 原始响应 → LLMProviderResponse。

        Args:
            response: OpenAI ChatCompletion 响应对象。

        Returns:
            统一的 LLMProviderResponse。
        """
        choice = response.choices[0]
        raw_tool_calls = getattr(choice.message, "tool_calls", None) or []

        tool_calls_list: list[dict] = []
        for tc in raw_tool_calls:
            tool_calls_list.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
            )

        usage_raw = getattr(response, "usage", None)
        usage: dict[str, Any] = {}
        if usage_raw:
            usage = {
                "prompt_tokens": getattr(usage_raw, "prompt_tokens", 0),
                "completion_tokens": getattr(usage_raw, "completion_tokens", 0),
            }

        return LLMProviderResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls_list or None,
            usage=usage,
            finish_reason=choice.finish_reason or "error",
            model=getattr(response, "model", "") or self._default_model,
        )
