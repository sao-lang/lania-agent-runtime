"""Tests for executor retry and error handling."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import AsyncOpenAI

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.executor import LLMExecutor
from lania_agent_runtime.models import LLMExecutorConfig


@pytest.fixture
def ctx():  # noqa: ANN201
    ctx = RuntimeContext(session_id="s1", agent_id="a1")
    ctx.append_message({"role": "user", "content": "hello"})
    ctx.context_payload.system_prompt = "You are a bot."
    return ctx


def _make_mock_choice(content="Hello", finish_reason="stop"):
    """Create a mock OpenAI response choice."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = []

    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = finish_reason
    return choice


def _make_mock_usage(prompt=10, completion=5):
    usage = MagicMock()
    usage.prompt_tokens = prompt
    usage.completion_tokens = completion
    return usage


def _make_executor(cfg: LLMExecutorConfig, mock_client: MagicMock) -> LLMExecutor:
    return LLMExecutor(config=cfg, client=mock_client)


class TestExecutorRetry:
    """Test executor retry and error paths."""

    @pytest.mark.asyncio
    async def test_execute_success(self, ctx) -> None:
        """Test successful execute call."""
        cfg = LLMExecutorConfig(max_retries=0)

        mock_resp = MagicMock()
        mock_resp.choices = [_make_mock_choice(content="Hello!")]
        mock_resp.usage = _make_mock_usage()
        mock_resp.model = "deepseek-chat"

        mock_create = AsyncMock(return_value=mock_resp)
        mock_client = MagicMock(spec=AsyncOpenAI)
        mock_client.chat.completions.create = mock_create

        executor = _make_executor(cfg, mock_client)
        response = await executor.execute(ctx)
        assert response.content == "Hello!"
        assert response.usage.prompt_tokens == 10
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_execute_retry_then_success(self, ctx) -> None:
        """Test retry on transient error then success."""
        cfg = LLMExecutorConfig(
            max_retries=2,
            retry_backoff_base=0.01,
            retry_backoff_max=0.1,
        )

        from openai import APITimeoutError

        call_count = 0

        async def mock_create(**kwargs: Any):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                import httpx

                raise APITimeoutError(httpx.Request("GET", "https://api.deepseek.com"))
            mock_resp = MagicMock()
            mock_resp.choices = [_make_mock_choice(content="OK after retry")]
            mock_resp.usage = _make_mock_usage()
            mock_resp.model = "deepseek"
            return mock_resp

        mock_client = MagicMock(spec=AsyncOpenAI)
        mock_client.chat.completions.create = mock_create

        executor = _make_executor(cfg, mock_client)
        response = await executor.execute(ctx)
        assert "retry" in response.content
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_execute_max_retries_exceeded(self, ctx) -> None:
        """Test that execute raises after exhausting retries."""
        cfg = LLMExecutorConfig(
            max_retries=1,
            retry_backoff_base=0.01,
            retry_backoff_max=0.1,
        )

        import httpx
        from openai import APITimeoutError

        call_count = 0
        request = httpx.Request("GET", "https://api.deepseek.com")

        async def always_fail(**kwargs: Any):
            nonlocal call_count
            call_count += 1
            raise APITimeoutError(request)

        mock_client = MagicMock(spec=AsyncOpenAI)
        mock_client.chat.completions.create = always_fail

        executor = _make_executor(cfg, mock_client)
        with pytest.raises(RuntimeError, match="LLM call failed"):
            await executor.execute(ctx)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_execute_non_retryable_error(self, ctx) -> None:
        """Test non-retryable error (not APIError subclass)."""
        cfg = LLMExecutorConfig(max_retries=2)

        async def raise_error(**kwargs: Any):
            raise ValueError("unexpected")

        mock_client = MagicMock(spec=AsyncOpenAI)
        mock_client.chat.completions.create = raise_error

        executor = _make_executor(cfg, mock_client)
        with pytest.raises(ValueError):
            await executor.execute(ctx)

    @pytest.mark.asyncio
    async def test_execute_rate_limit_then_success(self, ctx) -> None:
        """Test that RateLimitError triggers retry."""
        cfg = LLMExecutorConfig(
            max_retries=2,
            retry_backoff_base=0.01,
        )

        import httpx
        from openai import APIError

        call_count = 0
        request = httpx.Request("GET", "https://api.deepseek.com")

        class MockRateLimitError(APIError):
            def __init__(self) -> None:
                super().__init__("rate limited", request=request, body=None)

        async def rate_limit_then_ok(**kwargs: Any):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise MockRateLimitError()
            mock_resp = MagicMock()
            mock_resp.choices = [_make_mock_choice(content="Rate limit recovered")]
            mock_resp.usage = _make_mock_usage()
            mock_resp.model = "deepseek"
            return mock_resp

        mock_client = MagicMock(spec=AsyncOpenAI)
        mock_client.chat.completions.create = rate_limit_then_ok

        executor = _make_executor(cfg, mock_client)
        response = await executor.execute(ctx)
        assert response is not None
        assert call_count == 2
