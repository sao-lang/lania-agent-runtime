"""Tests for executor edge cases."""

from typing import Any
from unittest.mock import MagicMock

from openai import AsyncOpenAI

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.executor import LLMExecutor
from lania_agent_runtime.models import LLMExecutorConfig


class TestLLMExecutorEdgeCases:
    """Test LLMExecutor edge cases."""

    def _make_executor(self, **kwargs: Any) -> tuple[LLMExecutorConfig, AsyncOpenAI, LLMExecutor]:
        cfg = LLMExecutorConfig(**kwargs)
        client = MagicMock(spec=AsyncOpenAI)
        executor = LLMExecutor(config=cfg, client=client)
        return cfg, client, executor

    def test_init_without_client(self) -> None:
        """设计文档 §4.1: 无 client 时内部构造 AsyncOpenAI 客户端."""
        executor = LLMExecutor(config=LLMExecutorConfig(api_key="test-key"))
        assert executor._client is not None
        assert executor._config.model == "deepseek-chat"
        assert executor._config.api_key == "test-key"

    def test_client_is_used_directly(self) -> None:
        client = MagicMock(spec=AsyncOpenAI)
        executor = LLMExecutor(client=client)
        assert executor._client is client

    def test_provider_injection(self) -> None:
        """Test provider injection via OpenAIProvider."""
        from lania_agent_runtime.provider import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")
        executor = LLMExecutor(config=LLMExecutorConfig(), provider=provider)
        assert executor._provider is provider
        assert executor._client is provider.client

    def test_serialize_message_tool_call_fallback(self) -> None:
        _, _, executor = self._make_executor()
        # Test with minimal tool call data
        msg = {
            "role": "assistant",
            "tool_calls": [{"id": "call_1"}],
        }
        result = executor._serialize_message(msg)
        assert result["role"] == "assistant"

    def test_serialize_message_tool_call_with_name_fallback(self) -> None:
        _, _, executor = self._make_executor()
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "name": "simple_tool",
                    "arguments": {"key": "value"},
                }
            ],
        }
        result = executor._serialize_message(msg)
        assert result["role"] == "assistant"

    def test_merge_params_overrides(self) -> None:
        ctx = RuntimeContext()
        _, _, executor = self._make_executor(
            model="default-model",
            temperature=0.5,
            max_tokens=1000,
        )
        merged = executor._merge_params(ctx)
        assert merged.model == "default-model"
        assert merged.temperature == 0.5

    def test_to_response_with_missing_usage(self) -> None:
        _, _, executor = self._make_executor()

        class MockChoiceMessage:
            content = "Test"
            tool_calls = []

        class MockChoice:
            finish_reason = "stop"
            message = MockChoiceMessage()

        class MockResponse:
            choices = [MockChoice()]
            usage = None

        response = executor._to_response(MockResponse(), "mock-model")
        assert response.content == "Test"
        assert response.usage.prompt_tokens == 0
        assert response.usage.completion_tokens == 0
        assert response.model == "mock-model"  # falls back to param

    def test_to_response_with_direct_model_attr(self) -> None:
        """Test when response has no model attribute but model param is passed."""
        _, _, executor = self._make_executor()

        class MockChoiceMessage:
            content = "Hi"
            tool_calls = []

        class MockChoice:
            finish_reason = "stop"
            message = MockChoiceMessage()

        class MockResponse:
            choices = [MockChoice()]
            usage = None
            # No 'model' attribute

        response = executor._to_response(MockResponse(), "fallback-model")
        assert response.content == "Hi"
        assert response.model == "fallback-model"
        assert response.usage.total_tokens == 0
        assert response.finish_reason == "stop"

    def test_to_response_with_invalid_json_tool_args(self) -> None:
        _, _, executor = self._make_executor()

        class MockToolCall:
            id = "call_1"

            class Function:
                name = "test"
                arguments = "{invalid json}"

            function = Function()

        class MockChoiceMessage:
            content = ""
            tool_calls = [MockToolCall()]

        class MockChoice:
            finish_reason = "tool_calls"
            message = MockChoiceMessage()

        class MockUsage:
            prompt_tokens = 5
            completion_tokens = 3

        class MockResponse:
            choices = [MockChoice()]
            usage = MockUsage()
            model = "test-model"

        response = executor._to_response(MockResponse(), "test-model")
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].arguments == {}  # Invalid JSON -> empty dict
