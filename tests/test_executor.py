"""Tests for LLMExecutor."""

from typing import Any
from unittest.mock import MagicMock

from openai import AsyncOpenAI

import pytest

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.executor import (
    AsyncStreamCollector,
    LLMExecutionError,
    LLMExecutor,
    LLMExecutorBase,
)
from lania_agent_runtime.models import LLMExecutorConfig


class TestLLMExecutorConfig:
    """Test LLMExecutorConfig."""

    def test_default_config(self) -> None:
        cfg = LLMExecutorConfig()
        assert cfg.model == "deepseek-chat"
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096
        assert cfg.max_retries == 3

    def test_custom_config(self) -> None:
        cfg = LLMExecutorConfig(
            model="gpt-4",
            temperature=0.5,
            max_tokens=2048,
        )
        assert cfg.model == "gpt-4"
        assert cfg.temperature == 0.5
        assert cfg.max_tokens == 2048


class TestLLMExecutor:
    """Test LLMExecutor."""

    def _make_executor(self, **kwargs: Any) -> tuple[LLMExecutorConfig, AsyncOpenAI, LLMExecutor]:
        cfg = LLMExecutorConfig(**kwargs)
        client = MagicMock(spec=AsyncOpenAI)
        executor = LLMExecutor(client=client, config=cfg)
        return cfg, client, executor

    def test_init_with_config(self) -> None:
        cfg = LLMExecutorConfig()
        client = MagicMock(spec=AsyncOpenAI)
        executor = LLMExecutor(client=client, config=cfg)
        assert executor._config.model == "deepseek-chat"

    def test_init_with_default_config(self) -> None:
        client = MagicMock(spec=AsyncOpenAI)
        executor = LLMExecutor(client=client)
        assert executor._config.model == "deepseek-chat"

    def test_init_without_client(self) -> None:
        """设计文档 §4.1: 无 client 时内部构造 AsyncOpenAI 客户端."""
        executor = LLMExecutor(config=LLMExecutorConfig(api_key="test-key"))
        assert executor._client is not None
        assert executor._config.model == "deepseek-chat"
        assert executor._config.api_key == "test-key"

    def test_extract_messages(self) -> None:
        ctx = RuntimeContext(session_id="s1", agent_id="a1")
        ctx.append_message({"role": "user", "content": "hello"})
        _, _, executor = self._make_executor()
        messages = executor._extract_messages(ctx)
        assert len(messages) >= 1
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "hello"

    def test_serialize_message_simple(self) -> None:
        _, _, executor = self._make_executor()
        result = executor._serialize_message({"role": "user", "content": "hi"})
        assert result["role"] == "user"
        assert result["content"] == "hi"

    def test_serialize_message_with_tool_call(self) -> None:
        _, _, executor = self._make_executor()
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "get_weather",
                    "arguments": {"city": "Beijing"},
                    "function": {"name": "get_weather", "arguments": '{"city": "Beijing"}'},
                }
            ],
        }
        result = executor._serialize_message(msg)
        assert result["role"] == "assistant"
        assert "tool_calls" in result
        assert result["tool_calls"][0]["function"]["name"] == "get_weather"

    def test_serialize_message_with_tool_call_id(self) -> None:
        _, _, executor = self._make_executor()
        msg = {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{"temp": 24}',
        }
        result = executor._serialize_message(msg)
        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_1"

    def test_serialize_message_without_tool_call_id_fallback(self) -> None:
        _, _, executor = self._make_executor()
        msg = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {"name": "test", "arguments": "{}"},
                }
            ],
        }
        result = executor._serialize_message(msg)
        # Should not crash, tool_calls[0]["id"] should be found via .get
        assert "tool_calls" in result

    def test_merge_params(self) -> None:
        ctx = RuntimeContext()
        _, _, executor = self._make_executor(model="test-model", temperature=0.5, max_tokens=2048)
        merged = executor._merge_params(ctx)
        assert merged.model == "test-model"
        assert merged.temperature == 0.5
        assert merged.max_tokens == 2048

    def test_get_tools_schema_none(self) -> None:
        ctx = RuntimeContext()
        _, _, executor = self._make_executor()
        schema = executor._get_tools_schema(ctx)
        assert schema is None

    def test_get_tools_schema_with_data(self) -> None:
        ctx = RuntimeContext()
        ctx.set_tools_schema([{"name": "test"}])
        _, _, executor = self._make_executor()
        schema = executor._get_tools_schema(ctx)
        assert schema == [{"name": "test"}]

    def test_to_response_with_empty_tool_calls(self) -> None:
        _, _, executor = self._make_executor()

        class MockChoice:
            class MockMessage:
                content = "Hello"
                tool_calls = []

            finish_reason = "stop"
            message = MockMessage()

        class MockUsage:
            prompt_tokens = 10
            completion_tokens = 5

        class MockResponse:
            choices = [MockChoice()]
            usage = MockUsage()
            model = "deepseek-chat"

        response = executor._to_response(MockResponse(), "deepseek-chat")
        assert response.content == "Hello"
        assert response.tool_calls == []
        assert response.usage.prompt_tokens == 10
        assert response.usage.completion_tokens == 5
        assert response.finish_reason == "stop"


class TestLLMExecutionError:
    """Test LLMExecutionError."""

    def test_default_message(self) -> None:
        err = LLMExecutionError(model="test-model")
        assert "test-model" in str(err)
        assert err.last_error is None

    def test_with_cause(self) -> None:
        cause = ValueError("API error")
        err = LLMExecutionError(
            "Custom message",
            last_error=cause,
            consecutive_errors=3,
            model="gpt-4",
        )
        assert "Custom message" in str(err)
        assert err.last_error is cause
        assert err.consecutive_errors == 3

    def test_is_runtime_error(self) -> None:
        assert issubclass(LLMExecutionError, RuntimeError)


class TestLLMExecutorBase:
    """Test LLMExecutorBase abstract class."""

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            LLMExecutorBase()  # type: ignore

    @pytest.mark.asyncio
    async def test_execute_stream_not_implemented(self) -> None:
        class MinimalExecutor(LLMExecutorBase):
            async def execute(self, ctx):  # noqa: ANN201
                return None

        executor = MinimalExecutor()
        coro = executor.execute_stream(None)  # type: ignore
        with pytest.raises(NotImplementedError):
            await coro


class TestAsyncStreamCollector:
    """Test AsyncStreamCollector."""

    def _make_chunk(self, content: str | None = None, tool_calls: list | None = None,
                    usage: tuple[int, int] | None = None) -> MagicMock:
        chunk = MagicMock()
        if content is not None or tool_calls is not None:
            delta = MagicMock()
            delta.content = content
            delta.tool_calls = tool_calls
            choice = MagicMock()
            choice.delta = delta
            chunk.choices = [choice]
        else:
            chunk.choices = []
        if usage:
            usage_obj = MagicMock()
            usage_obj.prompt_tokens = usage[0]
            usage_obj.completion_tokens = usage[1]
            chunk.usage = usage_obj
        return chunk

    def test_collect_text(self) -> None:
        collector = AsyncStreamCollector()
        collector.collect(self._make_chunk(content="Hello"))
        collector.collect(self._make_chunk(content=" World"))
        assert collector.full_content == "Hello World"
        assert collector.tool_calls == []

    def test_collect_empty(self) -> None:
        collector = AsyncStreamCollector()
        assert collector.full_content == ""
        assert collector.tool_calls == []

    def test_collect_usage_only(self) -> None:
        collector = AsyncStreamCollector()
        collector.collect(self._make_chunk(content="Hi"))
        collector.collect(self._make_chunk(usage=(10, 5)))
        assert collector.full_content == "Hi"
        assert collector.usage == {"prompt_tokens": 10, "completion_tokens": 5}

    def test_collect_tool_calls(self) -> None:
        collector = AsyncStreamCollector()

        # First delta: tool call start
        tc1 = MagicMock()
        tc1.index = 0
        tc1.id = "call_1"
        tc1.function = MagicMock()
        tc1.function.name = "get_weather"
        tc1.function.arguments = '{"city": "Bei'

        collector.collect(self._make_chunk(tool_calls=[tc1]))

        # Second delta: tool call continuation
        tc2 = MagicMock()
        tc2.index = 0
        tc2.id = None
        tc2.function = MagicMock()
        tc2.function.name = None
        tc2.function.arguments = 'jing"}'

        collector.collect(self._make_chunk(content="Let me check", tool_calls=[tc2]))

        assert "Let me check" in collector.full_content
        assert len(collector.tool_calls) == 1
        assert collector.tool_calls[0]["id"] == "call_1"
        assert collector.tool_calls[0]["function"]["arguments"] == '{"city": "Beijing"}'

    def test_assemble_text_only(self) -> None:
        collector = AsyncStreamCollector()
        collector.collect(self._make_chunk(content="Hi there"))
        collector.collect(self._make_chunk(usage=(5, 3)))

        assembled = collector.assemble()
        assert assembled.choices[0].message.content == "Hi there"
        assert assembled.choices[0].message.tool_calls == []
        assert assembled.choices[0].finish_reason == "stop"
        assert assembled.usage.prompt_tokens == 5

    def test_assemble_tool_call(self) -> None:
        collector = AsyncStreamCollector()
        tc = MagicMock()
        tc.index = 0
        tc.id = "call_1"
        tc.function = MagicMock()
        tc.function.name = "get_weather"
        tc.function.arguments = '{"city": "Beijing"}'
        collector.collect(self._make_chunk(tool_calls=[tc]))

        assembled = collector.assemble()
        assert assembled.choices[0].message.content == ""
        assert len(assembled.choices[0].message.tool_calls) == 1
        assert assembled.choices[0].message.tool_calls[0].id == "call_1"
        assert assembled.choices[0].message.tool_calls[0].function.name == "get_weather"
        assert assembled.choices[0].finish_reason == "tool_calls"


class TestLLMExecutorNewFeatures:
    """Test new LLMExecutor features."""

    def _make_executor(self, **kwargs: Any) -> tuple[LLMExecutorConfig, MagicMock, LLMExecutor]:
        cfg = LLMExecutorConfig(**kwargs)
        client = MagicMock(spec=AsyncOpenAI)
        executor = LLMExecutor(client=client, config=cfg)
        return cfg, client, executor

    def test_config_with_timeout(self) -> None:
        cfg = LLMExecutorConfig(timeout=60.0)
        assert cfg.timeout == 60.0

    def test_config_with_extra_headers(self) -> None:
        cfg = LLMExecutorConfig(extra_headers={"X-Custom": "value"})
        assert cfg.extra_headers["X-Custom"] == "value"

    def test_build_kwargs_no_tools(self) -> None:
        _, _, executor = self._make_executor()
        params = LLMExecutorConfig(model="test", temperature=0.5, max_tokens=100)
        kwargs = executor._build_kwargs(params, [{"role": "user", "content": "hi"}], None)
        assert kwargs["model"] == "test"
        assert kwargs["temperature"] == 0.5
        assert kwargs["max_tokens"] == 100
        assert "tools" not in kwargs
        assert "stream" not in kwargs

    def test_build_kwargs_with_tools(self) -> None:
        _, _, executor = self._make_executor()
        tools = [{"name": "test_tool"}]
        kwargs = executor._build_kwargs(
            LLMExecutorConfig(), [{"role": "user", "content": "hi"}], tools
        )
        assert kwargs["tools"] == tools

    def test_build_kwargs_stream(self) -> None:
        _, _, executor = self._make_executor()
        kwargs = executor._build_kwargs(
            LLMExecutorConfig(), [{"role": "user", "content": "hi"}], None, stream=True
        )
        assert kwargs["stream"] is True
        assert kwargs["stream_options"] == {"include_usage": True}

    def test_serialize_tool_call_with_dict_args(self) -> None:
        _, _, executor = self._make_executor()
        tc = {"id": "call_1", "name": "get_weather", "arguments": {"city": "Beijing"}}
        result = executor._serialize_tool_call(tc)
        assert result["id"] == "call_1"
        assert result["function"]["name"] == "get_weather"
        assert result["function"]["arguments"] == '{"city": "Beijing"}'

    def test_serialize_tool_call_with_function_wrapper(self) -> None:
        _, _, executor = self._make_executor()
        tc = {
            "id": "call_1",
            "function": {"name": "get_weather", "arguments": '{"city": "Beijing"}'},
        }
        result = executor._serialize_tool_call(tc)
        assert result["id"] == "call_1"
        assert result["function"]["name"] == "get_weather"

    def test_serialize_tool_call_minimal(self) -> None:
        _, _, executor = self._make_executor()
        tc = {"id": "call_1"}
        result = executor._serialize_tool_call(tc)
        assert result["id"] == "call_1"
        assert result["type"] == "function"

    def test_serialize_message_with_tool_calls(self) -> None:
        _, _, executor = self._make_executor()
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "get_weather", "arguments": {"city": "Beijing"},
                 "function": {"name": "get_weather", "arguments": '{"city": "Beijing"}'}}
            ],
        }
        result = executor._serialize_message(msg)
        assert result["role"] == "assistant"
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["function"]["name"] == "get_weather"
