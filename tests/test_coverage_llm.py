"""
LLM 层覆盖率补测。

覆盖 OpenAIProvider 的 chat/流式/响应映射、OpenAILLMExecutor 的
重试/序列化/参数合并/tools schema/响应转换分支，以及 AsyncStreamCollector
的 usage chunk / tool_calls delta / 组装逻辑。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import APIError

from src.runtime.context._context import RuntimeContext
from src.runtime.llm._config import LLMExecutorConfig
from src.runtime.llm._errors import LLMExecutionError
from src.runtime.llm._executors._openai import OpenAILLMExecutor
from src.runtime.llm._executors._stream import AsyncStreamCollector
from src.runtime.llm._models import FinishReason
from src.runtime.llm._providers._openai import OpenAIProvider


def make_provider_response(
    content: str = "hi",
    tool_calls: list | None = None,
    finish_reason: str = "stop",
) -> SimpleNamespace:
    """构造 OpenAI SDK 风格的响应对象。"""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        model="gpt-4o",
    )


def make_tool_call(
    tc_id: str = "c1",
    name: str = "search",
    arguments: str = "{}",
) -> SimpleNamespace:
    """构造 OpenAI SDK 风格的工具调用对象。"""
    return SimpleNamespace(
        id=tc_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def make_ctx(
    messages: tuple = ({"role": "user", "content": "hi"},),
    services: dict | None = None,
) -> RuntimeContext:
    """构造测试用 RuntimeContext。"""
    return RuntimeContext(messages=messages, services=services or {})


class TestOpenAIProvider:
    """OpenAIProvider 补测。"""

    def test_default_model_used_when_empty(self) -> None:
        provider = OpenAIProvider(api_key="k")
        provider._client = MagicMock()
        provider._client.chat.completions.create = AsyncMock(return_value=make_provider_response())
        import asyncio

        response = asyncio.run(provider.chat([], "", 0.1, 100))
        assert response.model == "gpt-4o"

    def test_chat_with_tools(self) -> None:
        provider = OpenAIProvider(api_key="k")
        provider._client = MagicMock()
        provider._client.chat.completions.create = AsyncMock(return_value=make_provider_response())
        import asyncio

        response = asyncio.run(provider.chat([], "gpt-4o", 0.1, 100, tools=[{"type": "function"}]))
        assert response.content == "hi"
        assert response.usage == {"prompt_tokens": 10, "completion_tokens": 5}

    def test_chat_maps_tool_calls(self) -> None:
        provider = OpenAIProvider(api_key="k")
        provider._client = MagicMock()
        provider._client.chat.completions.create = AsyncMock(
            return_value=make_provider_response(tool_calls=[make_tool_call(arguments='{"q": "x"}')])
        )
        import asyncio

        response = asyncio.run(provider.chat([], "gpt-4o", 0.1, 100))
        assert response.tool_calls == [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "x"}'},
            }
        ]

    def test_chat_stream_returns_iterator(self) -> None:
        provider = OpenAIProvider(api_key="k")
        provider._client = MagicMock()

        async def fake_stream() -> AsyncIterator[Any]:
            yield SimpleNamespace(to_dict=lambda: {"choices": [{"delta": {"content": "x"}}]})

        provider._client.chat.completions.create = AsyncMock(return_value=fake_stream())
        import asyncio

        result = asyncio.run(provider.chat([], "gpt-4o", 0.1, 100, stream=True))
        assert hasattr(result, "__aiter__")

    async def test_stream_chat_yields_chunks(self) -> None:
        provider = OpenAIProvider(api_key="k")
        provider._client = MagicMock()

        async def fake_stream() -> AsyncIterator[Any]:
            yield SimpleNamespace(to_dict=lambda: {"choice": "x"})

        provider._client.chat.completions.create = AsyncMock(return_value=fake_stream())

        chunks = provider._stream_chat({"model": "m"})
        collected = await _collect(chunks)
        assert collected == [{"choice": "x"}]


async def _collect(iterator: AsyncIterator[Any]) -> list[Any]:
    """异步收集生成器全部元素。"""
    return [item async for item in iterator]


class TestOpenAILLMExecutor:
    """OpenAILLMExecutor 补测。"""

    def make_executor(
        self,
        provider: Any,
        config: LLMExecutorConfig | None = None,
    ) -> OpenAILLMExecutor:
        return OpenAILLMExecutor(
            config or LLMExecutorConfig(model="gpt-4o", api_key="k"),
            provider=provider,
        )

    async def test_retry_exhausted_raises(self) -> None:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=APIError(message="boom", request=MagicMock(), body=None)
        )
        executor = self.make_executor(
            provider, LLMExecutorConfig(model="m", api_key="k", max_retries=0)
        )
        with pytest.raises(LLMExecutionError):
            await executor.execute(make_ctx())

    async def test_serialize_tool_message(self) -> None:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
                model="m",
            )
        )
        executor = self.make_executor(provider)
        msg = executor._serialize_message({"role": "tool", "content": None})
        assert msg["content"] == ""

    async def test_encode_arguments_dict(self) -> None:
        executor = self.make_executor(AsyncMock())
        encoded = executor._encode_arguments({"function": {"arguments": {"q": "x"}}})
        assert encoded == '{"q": "x"}'

    async def test_merge_params_overrides(self) -> None:
        executor = self.make_executor(AsyncMock())
        ctx = make_ctx(services={"llm_config_overrides": {"model": "deepseek", "max_tokens": 42}})
        merged = executor._merge_params(ctx)
        assert merged.model == "deepseek"
        assert merged.max_tokens == 42
        assert merged.api_key == "k"

    async def test_get_tools_schema_via_dispatcher(self) -> None:
        dispatcher = MagicMock()
        dispatcher.all_tools = MagicMock(return_value=[{"name": "t"}])
        executor = self.make_executor(AsyncMock())
        schema = executor._get_tools_schema(make_ctx(services={"tool_dispatcher": dispatcher}))
        assert schema == [{"name": "t"}]

    async def test_to_response_sdk_with_tool_calls(self) -> None:
        executor = self.make_executor(AsyncMock())
        raw = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        tool_calls=[make_tool_call(arguments='{"a": 1}')],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=None,
            model="m",
        )
        response = executor._to_response(raw, "m")
        assert response.finish_reason == FinishReason.TOOL_CALLS
        assert response.tool_calls[0].arguments == {"a": 1}

    async def test_to_response_dict_empty_choices(self) -> None:
        executor = self.make_executor(AsyncMock())
        response = executor._to_response({}, "m")
        assert response.model == "m"
        assert response.content == ""

    async def test_dict_to_response_invalid_arguments_json(self) -> None:
        executor = self.make_executor(AsyncMock())
        raw = {
            "choices": [
                {
                    "message": {
                        "content": "x",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "function": {"name": "f", "arguments": "not-json"},
                            }
                        ],
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1},
            "model": "m",
        }
        response = executor._to_response(raw, "m")
        assert response.tool_calls[0].arguments == {"_raw": "not-json"}

    async def test_parse_finish_reason_compat(self) -> None:
        executor = self.make_executor(AsyncMock())
        assert executor._parse_finish_reason("function_call") == FinishReason.TOOL_CALLS
        assert executor._parse_finish_reason("unknown") == FinishReason.ERROR
        assert executor._parse_finish_reason("STOP") == FinishReason.STOP

    async def test_execute_stream_with_tool_deltas(self) -> None:
        provider = AsyncMock()

        async def fake_stream() -> AsyncIterator[dict]:
            yield {"choices": [{"delta": {"content": "你好"}}]}
            yield {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "c1",
                                    "function": {"name": "search", "arguments": '{"q":'},
                                }
                            ]
                        }
                    }
                ]
            }
            yield {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": "1}"},
                                }
                            ]
                        }
                    }
                ]
            }
            yield {"usage": {"prompt_tokens": 10, "completion_tokens": 2}, "model": "m"}

        provider.chat = AsyncMock(return_value=fake_stream())
        executor = self.make_executor(provider)
        collector, response = await executor.execute_stream(make_ctx())
        assert collector.full_content == "你好"
        assert collector.tool_calls[0]["function"]["arguments"] == '{"q":1}'
        assert response.finish_reason == FinishReason.TOOL_CALLS
        assert response.usage.prompt_tokens == 10


class TestAsyncStreamCollector:
    """AsyncStreamCollector 补测。"""

    def test_usage_chunk_only(self) -> None:
        collector = AsyncStreamCollector()
        collector.collect({"usage": {"prompt_tokens": 3, "completion_tokens": 4}, "model": "m"})
        assert collector.usage_dict == {"prompt_tokens": 3, "completion_tokens": 4}
        assert collector.full_content == ""
        assert collector.to_json() != ""

    def test_empty_delta_chunk(self) -> None:
        collector = AsyncStreamCollector()
        collector.collect({"choices": [{"delta": {}}]})
        assert collector.full_content == ""

    def test_tool_call_delta_accumulation(self) -> None:
        collector = AsyncStreamCollector()
        collector.collect(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [{"index": 0, "id": "c1", "function": {"name": "se"}}]
                        }
                    }
                ]
            }
        )
        collector.collect(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "arch"}}]}}]}
        )
        collector.collect(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [{"index": 0, "function": {"arguments": '{"q": "x"}'}}]
                        }
                    }
                ]
            }
        )
        assembled = collector.assemble()
        assert collector.tool_calls[0]["function"]["name"] == "search"
        assert assembled["choices"][0]["finish_reason"] == "tool_calls"
