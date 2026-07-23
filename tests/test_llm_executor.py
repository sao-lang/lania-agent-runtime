"""
LLMExecutor 单元测试。

使用 mock Provider，不调用真实 API。
覆盖：正常文本回复、工具调用、重试、流式、错误路径、边界条件。
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.runtime.context._context import RuntimeContext
from src.runtime.llm._config import LLMExecutorConfig
from src.runtime.llm._errors import LLMExecutionError
from src.runtime.llm._executors._openai import OpenAILLMExecutor
from src.runtime.llm._executors._stream import AsyncStreamCollector
from src.runtime.llm._models import FinishReason, LLMResponse, LLMUsage, ToolCall
from src.runtime.llm._providers._base import LLMProvider, LLMProviderResponse
from src.runtime.llm._retry import RetryPolicy

# ============ Fixtures ============


@pytest.fixture
def mock_provider() -> AsyncMock:
    """返回一个自动 mock 的 LLMProvider。"""
    return AsyncMock(spec=LLMProvider)


@pytest.fixture
def base_config() -> LLMExecutorConfig:
    """基础配置（无 api_key）。"""
    return LLMExecutorConfig(
        model="gpt-4o-mini",
        temperature=0.7,
        max_tokens=256,
        timeout=5.0,
        max_retries=2,
        retry_backoff_base=0.01,
        retry_backoff_max=0.1,
    )


@pytest.fixture
def executor(base_config: LLMExecutorConfig, mock_provider: AsyncMock) -> OpenAILLMExecutor:
    """预配置的 OpenAILLMExecutor。"""
    return OpenAILLMExecutor(config=base_config, provider=mock_provider)


@pytest.fixture
def simple_ctx() -> RuntimeContext:
    """简易 RuntimeContext（含一条 user message）。"""
    return RuntimeContext(
        session_id="test-session",
        agent_id="test-agent",
        step_index=1,
        messages=(
            {"role": "system", "content": "你是一个助手"},
            {"role": "user", "content": "你好"},
        ),
    )


@pytest.fixture
def ctx_with_tool_result() -> RuntimeContext:
    """包含工具结果的 RuntimeContext。"""
    return RuntimeContext(
        session_id="test-session",
        agent_id="test-agent",
        step_index=2,
        messages=(
            {"role": "system", "content": "你是一个助手"},
            {"role": "user", "content": "北京天气"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city":"北京"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"temperature": 24, "condition": "晴"}',
            },
        ),
    )


# ============ Helper: Mock OpenAI 响应 ============


def make_mock_choice(
    content: str = "",
    tool_calls: list[dict] | None = None,
    finish_reason: str = "stop",
) -> MagicMock:
    """创建模拟的 OpenAI Choice 对象。"""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason
    return choice


def make_mock_usage(prompt_tokens: int = 10, completion_tokens: int = 20) -> MagicMock:
    """创建模拟的 OpenAI Usage 对象。"""
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    return usage


def make_mock_openai_response(
    content: str = "你好！有什么可以帮助你的吗？",
    tool_calls: list[MagicMock] | None = None,
    finish_reason: str = "stop",
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 15,
    completion_tokens: int = 10,
) -> MagicMock:
    """创建模拟的 OpenAI ChatCompletion 响应。"""
    response = MagicMock()
    response.choices = [make_mock_choice(content, tool_calls, finish_reason)]
    response.usage = make_mock_usage(prompt_tokens, completion_tokens)
    response.model = model
    return response


def make_mock_tool_call(
    id: str = "call_abc123",
    name: str = "get_weather",
    arguments: str = '{"city": "北京"}',
) -> MagicMock:
    """创建模拟的 OpenAI ToolCall 对象。"""
    tc = MagicMock()
    tc.id = id
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


# ============ 数据模型测试 ============


class TestLLMUsage:
    """LLMUsage 数据模型测试。"""

    def test_total_tokens(self) -> None:
        """total_tokens 返回 prompt + completion。"""
        usage = LLMUsage(prompt_tokens=100, completion_tokens=50)
        assert usage.total_tokens == 150

    def test_total_tokens_zero(self) -> None:
        """默认值全为零。"""
        usage = LLMUsage()
        assert usage.total_tokens == 0


class TestToolCall:
    """ToolCall 数据模型测试。"""

    def test_create_tool_call(self) -> None:
        """创建 ToolCall 实例。"""
        tc = ToolCall(
            id="call_1",
            name="get_weather",
            arguments={"city": "北京"},
            raw_arguments='{"city": "北京"}',
        )
        assert tc.id == "call_1"
        assert tc.name == "get_weather"
        assert tc.arguments["city"] == "北京"

    def test_default_values(self) -> None:
        """默认值为空字符串/空字典。"""
        tc = ToolCall()
        assert tc.id == ""
        assert tc.name == ""
        assert tc.arguments == {}
        assert tc.raw_arguments == ""


class TestFinishReason:
    """FinishReason 枚举测试。"""

    def test_values(self) -> None:
        """枚举值正确。"""
        assert FinishReason.STOP.value == "stop"
        assert FinishReason.TOOL_CALLS.value == "tool_calls"
        assert FinishReason.LENGTH.value == "length"
        assert FinishReason.ERROR.value == "error"


class TestLLMResponse:
    """LLMResponse 数据模型测试。"""

    def test_text_response(self) -> None:
        """纯文本回复。"""
        resp = LLMResponse(
            content="你好！",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
            finish_reason=FinishReason.STOP,
            model="gpt-4o",
        )
        assert resp.content == "你好！"
        assert resp.tool_calls == []
        assert resp.usage.total_tokens == 15
        assert resp.finish_reason == FinishReason.STOP

    def test_tool_call_response(self) -> None:
        """工具调用回复。"""
        tc = ToolCall(id="c1", name="get_weather", arguments={"city": "北京"})
        resp = LLMResponse(
            content="",
            tool_calls=[tc],
            finish_reason=FinishReason.TOOL_CALLS,
        )
        assert resp.content == ""
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_weather"
        assert resp.finish_reason == FinishReason.TOOL_CALLS

    def test_default_values(self) -> None:
        """默认值测试。"""
        resp = LLMResponse()
        assert resp.content == ""
        assert resp.tool_calls == []
        assert resp.finish_reason == FinishReason.STOP


# ============ RetryPolicy 测试 ============


class TestRetryPolicy:
    """RetryPolicy 测试。"""

    def test_get_backoff_exponential(self) -> None:
        """退避时间指数增长。"""
        policy = RetryPolicy(backoff_base=1.0, backoff_max=30.0)
        assert policy.get_backoff(0) == 1.0
        assert policy.get_backoff(1) == 2.0
        assert policy.get_backoff(2) == 4.0

    def test_get_backoff_capped(self) -> None:
        """退避时间被 backoff_max 限制。"""
        policy = RetryPolicy(backoff_base=1.0, backoff_max=5.0)
        assert policy.get_backoff(3) == 5.0  # 2^3=8 > 5

    def test_is_retryable_positive(self) -> None:
        """可重试异常返回 True。"""
        policy = RetryPolicy(retryable_exceptions=(ValueError, KeyError))
        assert policy.is_retryable(ValueError("test"))
        assert policy.is_retryable(KeyError("test"))

    def test_is_retryable_negative(self) -> None:
        """不可重试异常返回 False。"""
        policy = RetryPolicy(retryable_exceptions=(ValueError,))
        assert not policy.is_retryable(TypeError("test"))

    def test_to_dict(self) -> None:
        """序列化为字典。"""
        policy = RetryPolicy(max_retries=5, backoff_base=2.0)
        d = policy.to_dict()
        assert d["max_retries"] == 5
        assert d["backoff_base"] == 2.0


# ============ LLMProviderResponse 测试 ============


class TestLLMProviderResponse:
    """LLMProviderResponse 测试。"""

    def test_default_values(self) -> None:
        """默认值测试。"""
        resp = LLMProviderResponse()
        assert resp.content == ""
        assert resp.tool_calls is None
        assert resp.finish_reason == "stop"

    def test_with_tool_calls(self) -> None:
        """带工具调用。"""
        resp = LLMProviderResponse(
            content="",
            tool_calls=[{"id": "c1", "type": "function", "function": {"name": "test"}}],
            finish_reason="tool_calls",
        )
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1


# ============ AsyncStreamCollector 测试 ============


class TestAsyncStreamCollector:
    """AsyncStreamCollector 测试。"""

    def test_collect_content(self) -> None:
        """累加文本 chunks。"""
        collector = AsyncStreamCollector()
        collector.collect({"choices": [{"delta": {"content": "北京"}}]})
        collector.collect({"choices": [{"delta": {"content": "的天气"}}]})
        collector.collect({"choices": [{"delta": {"content": "是晴天"}}]})
        assert collector.full_content == "北京的天气是晴天"

    def test_collect_empty_delta(self) -> None:
        """空 delta 不报错。"""
        collector = AsyncStreamCollector()
        collector.collect({"choices": [{"delta": {}}]})
        assert collector.full_content == ""

    def test_collect_usage_chunk(self) -> None:
        """最后一个 usage chunk 处理。"""
        collector = AsyncStreamCollector()
        collector.collect({"usage": {"prompt_tokens": 10, "completion_tokens": 20}})
        assert collector.usage_dict["prompt_tokens"] == 10
        assert collector.usage_dict["completion_tokens"] == 20

    def test_collect_tool_calls(self) -> None:
        """工具调用 delta 累加。"""
        collector = AsyncStreamCollector()
        collector.collect(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "get_", "arguments": ""},
                                }
                            ]
                        }
                    }
                ]
            }
        )
        collector.collect(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {
                                        "name": "weather",
                                        "arguments": '{"city": "北京"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        )
        assert len(collector.tool_calls) == 1
        assert collector.tool_calls[0]["function"]["name"] == "get_weather"
        assert "北京" in collector.tool_calls[0]["function"]["arguments"]

    def test_assemble_content(self) -> None:
        """assemble() 生成兼容的响应字典。"""
        collector = AsyncStreamCollector()
        collector.collect({"choices": [{"delta": {"content": "你好"}}]})
        collector.collect({"usage": {"prompt_tokens": 5, "completion_tokens": 3}})
        assembled = collector.assemble()
        assert assembled["choices"][0]["message"]["content"] == "你好"
        assert assembled["usage"]["prompt_tokens"] == 5
        assert assembled["choices"][0]["finish_reason"] == "stop"

    def test_assemble_with_tool_calls(self) -> None:
        """带工具调用的 assemble。"""
        collector = AsyncStreamCollector()
        collector.collect(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '{"city":"北京"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        )
        assembled = collector.assemble()
        assert assembled["choices"][0]["finish_reason"] == "tool_calls"
        assert (
            assembled["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"
        )

    def test_to_json(self) -> None:
        """JSON 序列化。"""
        collector = AsyncStreamCollector()
        collector.collect({"choices": [{"delta": {"content": "test"}}]})
        js = collector.to_json()
        assert "test" in js

    def test_no_choices(self) -> None:
        """choices 为 None 不报错。"""
        collector = AsyncStreamCollector()
        collector.collect({})
        assert collector.full_content == ""
        assert collector.tool_calls == []


# ============ OpenAILLMExecutor: execute() 测试 ============


class TestOpenAILLMExecutorExecute:
    """OpenAILLMExecutor.execute() 单元测试。"""

    @pytest.mark.asyncio
    async def test_basic_text_response(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """正常文本回复。"""
        mock_resp = make_mock_openai_response(content="你好！有什么可以帮助你的吗？")
        executor._provider.chat = AsyncMock(return_value=mock_resp)

        response = await executor.execute(simple_ctx)

        assert isinstance(response, LLMResponse)
        assert response.content == "你好！有什么可以帮助你的吗？"
        assert response.tool_calls == []
        assert response.finish_reason == FinishReason.STOP
        assert response.usage.total_tokens == 25

        # 验证 provider 被正确调用
        executor._provider.chat.assert_awaited_once()
        call_args = executor._provider.chat.await_args
        assert call_args is not None
        assert call_args.kwargs["model"] == "gpt-4o-mini"
        assert call_args.kwargs["stream"] is False
        assert len(call_args.kwargs["messages"]) == 2

    @pytest.mark.asyncio
    async def test_tool_call_response(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """LLM 请求工具调用。"""
        mock_tc = make_mock_tool_call(id="call_1", name="get_weather", arguments='{"city": "北京"}')
        mock_resp = make_mock_openai_response(
            content="",
            tool_calls=[mock_tc],
            finish_reason="tool_calls",
            completion_tokens=15,
        )
        executor._provider.chat = AsyncMock(return_value=mock_resp)

        response = await executor.execute(simple_ctx)

        assert response.content == ""
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments == {"city": "北京"}
        assert response.finish_reason == FinishReason.TOOL_CALLS
        assert response.usage.completion_tokens == 15

    @pytest.mark.asyncio
    async def test_with_tools_schema(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """携带 tools schema 调用。"""
        mock_resp = make_mock_openai_response(content="好的")
        executor._provider.chat = AsyncMock(return_value=mock_resp)

        # 通过 services 注入 tools_schema
        tools_schema = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "获取天气",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                },
            }
        ]
        ctx_with_tools = RuntimeContext(
            session_id="test",
            agent_id="test",
            messages=({"role": "user", "content": "hi"},),
            services={"tools_schema": tools_schema},
        )
        await executor.execute(ctx_with_tools)

        executor._provider.chat.assert_awaited_once()
        call_kwargs = executor._provider.chat.await_args.kwargs
        assert call_kwargs["tools"] == tools_schema

    @pytest.mark.asyncio
    async def test_with_dispatcher(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """通过 tool_dispatcher 获取 schema。"""
        mock_resp = make_mock_openai_response(content="ok")
        executor._provider.chat = AsyncMock(return_value=mock_resp)

        dispatcher = MagicMock()
        dispatcher.all_tools = MagicMock(
            return_value=[{"type": "function", "function": {"name": "test"}}]
        )

        ctx_with_dispatcher = RuntimeContext(
            session_id="test",
            agent_id="test",
            messages=({"role": "user", "content": "hi"},),
            services={"tool_dispatcher": dispatcher},
        )
        await executor.execute(ctx_with_dispatcher)

        executor._provider.chat.assert_awaited_once()
        call_kwargs = executor._provider.chat.await_args.kwargs
        assert call_kwargs["tools"] == [{"type": "function", "function": {"name": "test"}}]

    @pytest.mark.asyncio
    async def test_retry_then_success(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """重试后成功。"""
        from openai import APITimeoutError

        mock_success = make_mock_openai_response(content="最终成功")
        executor._provider.chat = AsyncMock(side_effect=[APITimeoutError("timeout"), mock_success])

        response = await executor.execute(simple_ctx)

        assert response.content == "最终成功"
        assert executor._provider.chat.await_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """重试耗尽后抛出 LLMExecutionError。"""
        from openai import APITimeoutError

        executor._provider.chat = AsyncMock(side_effect=APITimeoutError("always timeout"))

        with pytest.raises(LLMExecutionError) as exc_info:
            await executor.execute(simple_ctx)

        assert "LLM 执行失败" in str(exc_info.value)
        assert exc_info.value.model == "gpt-4o-mini"
        # max_retries=2, 所以共 3 次调用（1 次原始 + 2 次重试）
        assert executor._provider.chat.await_count == 3

    @pytest.mark.asyncio
    async def test_rate_limit_retry(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """限流错误也触发重试。"""
        from openai import APIStatusError

        class MockRateLimitError(APIStatusError):
            def __init__(self) -> None:
                import httpx

                response = httpx.Response(
                    429, request=httpx.Request("POST", "https://api.openai.com")
                )
                super().__init__("rate limited", response=response, body={"error": "rate_limited"})

        mock_success = make_mock_openai_response(content="成功了")
        executor._provider.chat = AsyncMock(side_effect=[MockRateLimitError(), mock_success])

        response = await executor.execute(simple_ctx)
        assert response.content == "成功了"

    @pytest.mark.asyncio
    async def test_serialize_message_with_tool_calls(self, executor: OpenAILLMExecutor) -> None:
        """序列化带 tool_calls 的消息。"""
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "get_weather",
                    "arguments": {"city": "北京"},
                }
            ],
        }
        result = executor._serialize_message(msg)
        assert result["role"] == "assistant"
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["function"]["name"] == "get_weather"

    @pytest.mark.asyncio
    async def test_serialize_tool_result(self, executor: OpenAILLMExecutor) -> None:
        """序列化 tool 结果消息。"""
        msg = {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{"result": "ok"}',
        }
        result = executor._serialize_message(msg)
        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_1"
        assert result["content"] == '{"result": "ok"}'

    @pytest.mark.asyncio
    async def test_parse_finish_reason_stop(self, executor: OpenAILLMExecutor) -> None:
        """parse: stop。"""
        assert executor._parse_finish_reason("stop") == FinishReason.STOP

    @pytest.mark.asyncio
    async def test_parse_finish_reason_tool_calls(self, executor: OpenAILLMExecutor) -> None:
        """parse: tool_calls。"""
        assert executor._parse_finish_reason("tool_calls") == FinishReason.TOOL_CALLS

    @pytest.mark.asyncio
    async def test_parse_finish_reason_function_call(self, executor: OpenAILLMExecutor) -> None:
        """兼容旧版 function_call → tool_calls。"""
        assert executor._parse_finish_reason("function_call") == FinishReason.TOOL_CALLS

    @pytest.mark.asyncio
    async def test_parse_finish_reason_unknown(self, executor: OpenAILLMExecutor) -> None:
        """未知原因 → ERROR。"""
        assert executor._parse_finish_reason("unknown_reason") == FinishReason.ERROR

    @pytest.mark.asyncio
    async def test_get_tools_schema_from_services(self, executor: OpenAILLMExecutor) -> None:
        """从 services 获取 tools_schema。"""
        schema = [{"type": "function", "function": {"name": "test"}}]
        ctx = RuntimeContext(
            session_id="t", agent_id="t", messages=(), services={"tools_schema": schema}
        )
        result = executor._get_tools_schema(ctx)
        assert result == schema

    @pytest.mark.asyncio
    async def test_get_tools_schema_none(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """无 schema 时返回 None。"""
        assert executor._get_tools_schema(simple_ctx) is None

    @pytest.mark.asyncio
    async def test_length_finish_reason(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """被截断的回复。"""
        mock_resp = make_mock_openai_response(
            content="部分内容",
            finish_reason="length",
        )
        executor._provider.chat = AsyncMock(return_value=mock_resp)

        response = await executor.execute(simple_ctx)
        assert response.content == "部分内容"
        assert response.finish_reason == FinishReason.LENGTH


# ============ OpenAILLMExecutor: execute_stream() 测试 ============


class TestOpenAILLMExecutorStream:
    """OpenAILLMExecutor.execute_stream() 单元测试。"""

    @pytest.mark.asyncio
    async def test_stream_content(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """流式文本内容收集。"""

        async def mock_stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict]:
            chunks = [
                {"choices": [{"delta": {"content": "北京"}}]},
                {"choices": [{"delta": {"content": "晴天"}}]},
                {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
            ]
            for c in chunks:
                yield c

        executor._provider.chat = AsyncMock(return_value=mock_stream())

        collector, response = await executor.execute_stream(simple_ctx)

        assert collector.full_content == "北京晴天"
        assert response.content == "北京晴天"
        assert response.usage.total_tokens == 15

    @pytest.mark.asyncio
    async def test_stream_tool_calls(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """流式工具调用收集。"""

        async def mock_stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict]:
            chunks = [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "function": {"name": "get_", "arguments": ""},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {
                                            "name": "weather",
                                            "arguments": '{"city": "北京"}',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                {"usage": {"prompt_tokens": 10, "completion_tokens": 3}},
            ]
            for c in chunks:
                yield c

        executor._provider.chat = AsyncMock(return_value=mock_stream())

        collector, response = await executor.execute_stream(simple_ctx)

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments["city"] == "北京"
        assert response.finish_reason == FinishReason.TOOL_CALLS

    @pytest.mark.asyncio
    async def test_stream_model_name(
        self, executor: OpenAILLMExecutor, simple_ctx: RuntimeContext
    ) -> None:
        """流式模式下 model 名称正确传递。"""

        async def mock_stream(*args: Any, **kwargs: Any) -> AsyncIterator[dict]:
            yield {"choices": [{"delta": {"content": "hi"}}], "model": "gpt-4o-mini"}
            yield {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}

        executor._provider.chat = AsyncMock(return_value=mock_stream())

        _, response = await executor.execute_stream(simple_ctx)
        assert response.model == "gpt-4o-mini"


# ============ LLMExecutorConfig 测试 ============


class TestLLMExecutorConfig:
    """LLMExecutorConfig 测试。"""

    def test_default_values(self) -> None:
        """默认值。"""
        config = LLMExecutorConfig()
        assert config.model == "gpt-4o"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.stream is False

    def test_from_dict(self) -> None:
        """从字典构造。"""
        config = LLMExecutorConfig.from_dict(
            {
                "model": "deepseek-chat",
                "temperature": 0.3,
                "api_key": "sk-test",
                "stream": True,
            }
        )
        assert config.model == "deepseek-chat"
        assert config.temperature == 0.3
        assert config.api_key == "sk-test"
        assert config.stream is True

    def test_from_dict_partial(self) -> None:
        """部分字段从字典构造，其余用默认值。"""
        config = LLMExecutorConfig.from_dict({"model": "gpt-4o-mini"})
        assert config.model == "gpt-4o-mini"
        assert config.temperature == 0.7  # 默认值


# ============ LLMExecutionError 测试 ============


class TestLLMExecutionError:
    """LLMExecutionError 测试。"""

    def test_create_error(self) -> None:
        """创建错误实例。"""
        err = LLMExecutionError(
            last_error=ValueError("API key invalid"),
            consecutive_errors=3,
            model="gpt-4o",
        )
        assert "LLM 执行失败" in str(err)
        assert "gpt-4o" in str(err)
        assert err.consecutive_errors == 3

    def test_create_error_no_last(self) -> None:
        """无 last_error 时。"""
        err = LLMExecutionError(model="gpt-4o")
        assert err.last_error is None

    def test_to_dict(self) -> None:
        """转换为字典。"""
        err = LLMExecutionError(
            last_error=RuntimeError("timeout"),
            consecutive_errors=2,
            model="gpt-4o",
        )
        d = err.to_dict()
        assert d["error_type"] == "LLMExecutionError"
        assert d["model"] == "gpt-4o"
        assert d["consecutive_errors"] == 2


# ============ Runtime 集成适配测试 ============


class TestRuntimeIntegration:
    """AgentRuntime 集成适配测试。"""

    @pytest.mark.asyncio
    async def test_new_executor_in_runtime(self) -> None:
        """新的 LLMExecutor 可以正常注入 AgentRuntime 并执行。"""
        from src.runtime import AgentRuntime

        # 创建一个返回 LLMResponse 的 mock executor
        class MockLLMExecutor:
            async def execute(self, ctx: RuntimeContext) -> LLMResponse:
                return LLMResponse(
                    content="我是 mock 回复",
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                    finish_reason=FinishReason.STOP,
                )

        runtime = AgentRuntime(
            system_prompt="你是助手",
            llm_executor=MockLLMExecutor(),
        )
        result = await runtime.run("你好")
        assert "mock 回复" in result.content

    @pytest.mark.asyncio
    async def test_legacy_fn_still_works(self) -> None:
        """旧接口 ExecutorFn 仍然兼容。"""
        from src.runtime import AgentRuntime

        async def old_style_executor(ctx: Any) -> dict:
            return {"role": "assistant", "content": "旧接口回复"}

        runtime = AgentRuntime(
            system_prompt="助手",
            llm_executor=old_style_executor,
        )
        result = await runtime.run("hi")
        assert "旧接口回复" in result.content

    @pytest.mark.asyncio
    async def test_builder_auto_creates_executor(self) -> None:
        """Builder 在有 api_key 时自动创建 LLMExecutor。"""
        from src.runtime import AgentRuntime

        # 不传 api_key，不会自动创建
        runtime = AgentRuntime.builder().system_prompt("助手").llm(model="gpt-4o").build()
        # 没有 api_key，不会自动创建 executor
        assert runtime._llm_executor is None
        # llm_config 保存在 services 中
        assert "llm_config" in runtime._services
