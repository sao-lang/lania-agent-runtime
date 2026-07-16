"""Tests for executor streaming."""

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import AsyncOpenAI

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.executor import LLMExecutor, LLMExecutorConfig


@pytest.fixture
def ctx():  # noqa: ANN201
    ctx = RuntimeContext(session_id="s1", agent_id="a1")
    ctx.append_message({"role": "user", "content": "hello"})
    ctx.context_payload.system_prompt = "You are a bot."
    return ctx


class _MockAsyncIterator:
    """Helper to create async iterators from a list of chunks."""

    def __init__(self, chunks) -> None:
        self._chunks = chunks
        self._index = 0

    def __aiter__(self) -> AsyncIterator:
        return self

    async def __anext__(self) -> Any:

        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


class TestExecutorStream:
    """Test executor streaming."""

    def _make_executor(self, mock_client: MagicMock, **kwargs: Any) -> LLMExecutor:
        cfg = LLMExecutorConfig(**kwargs)
        return LLMExecutor(client=mock_client, config=cfg)

    @pytest.mark.asyncio
    async def test_execute_stream_text_only(self, ctx) -> None:
        """Test streaming with text chunks only."""
        chunks = []
        for text in ["Hello", " ", "World", "!"]:
            delta = MagicMock()
            delta.content = text
            delta.tool_calls = None
            choice = MagicMock()
            choice.delta = delta
            chunk = MagicMock()
            chunk.choices = [choice]
            chunks.append(chunk)

        # Final usage chunk
        last_chunk = MagicMock()
        last_chunk.choices = []
        usage = MagicMock()
        usage.prompt_tokens = 10
        usage.completion_tokens = 5
        last_chunk.usage = usage
        chunks.append(last_chunk)

        mock_create = AsyncMock(return_value=_MockAsyncIterator(chunks))
        mock_client = MagicMock(spec=AsyncOpenAI)
        mock_client.chat.completions.create = mock_create

        executor = self._make_executor(mock_client)
        collected = []
        async for chunk_text in executor.execute_stream(ctx):
            collected.append(chunk_text)
        assert "".join(collected) == "Hello World!"

    @pytest.mark.asyncio
    async def test_execute_stream_with_tool_calls(self, ctx) -> None:
        """Test streaming with tool call deltas."""
        # Text chunk
        delta1 = MagicMock()
        delta1.content = "Let me check"
        delta1.tool_calls = None
        choice1 = MagicMock()
        choice1.delta = delta1
        chunk1 = MagicMock()
        chunk1.choices = [choice1]

        # Tool call delta
        delta2 = MagicMock()
        delta2.content = None
        tc_delta = MagicMock()
        func = MagicMock()
        func.name = None
        func.arguments = '{"city": "Bei'
        tc_delta.function = func
        delta2.tool_calls = [tc_delta]
        choice2 = MagicMock()
        choice2.delta = delta2
        chunk2 = MagicMock()
        chunk2.choices = [choice2]

        # Tool call continuation
        delta3 = MagicMock()
        delta3.content = None
        tc_delta3 = MagicMock()
        func3 = MagicMock()
        func3.name = None
        func3.arguments = 'jing"}'
        tc_delta3.function = func3
        delta3.tool_calls = [tc_delta3]
        choice3 = MagicMock()
        choice3.delta = delta3
        chunk3 = MagicMock()
        chunk3.choices = [choice3]

        # Final chunk
        last_chunk = MagicMock()
        last_chunk.choices = []

        mock_create = AsyncMock(
            return_value=_MockAsyncIterator([chunk1, chunk2, chunk3, last_chunk])
        )
        mock_client = MagicMock(spec=AsyncOpenAI)
        mock_client.chat.completions.create = mock_create

        executor = self._make_executor(mock_client)
        collected = []
        async for chunk_text in executor.execute_stream(ctx):
            collected.append(chunk_text)
        full = "".join(collected)
        assert "Let me check" in full
        assert "Beijing" in full or "jing" in full

    @pytest.mark.asyncio
    async def test_execute_stream_empty_choices(self, ctx) -> None:
        """Test streaming with empty choices (only usage chunk)."""
        usage_chunk = MagicMock()
        usage_chunk.choices = []
        usage = MagicMock()
        usage.prompt_tokens = 5
        usage.completion_tokens = 3
        usage_chunk.usage = usage

        mock_create = AsyncMock(return_value=_MockAsyncIterator([usage_chunk]))
        mock_client = MagicMock(spec=AsyncOpenAI)
        mock_client.chat.completions.create = mock_create

        executor = self._make_executor(mock_client)
        collected = []
        async for chunk_text in executor.execute_stream(ctx):
            collected.append(chunk_text)
        assert collected == []

    @pytest.mark.asyncio
    async def test_execute_stream_tools_schema(self, ctx) -> None:
        """Test streaming with tools schema set."""
        ctx.set_tools_schema([{"name": "test_tool", "parameters": {"type": "object"}}])

        delta = MagicMock()
        delta.content = "Using tool"
        delta.tool_calls = None
        choice = MagicMock()
        choice.delta = delta
        chunk = MagicMock()
        chunk.choices = [choice]

        last_chunk = MagicMock()
        last_chunk.choices = []

        mock_create = AsyncMock(return_value=_MockAsyncIterator([chunk, last_chunk]))
        mock_client = MagicMock(spec=AsyncOpenAI)
        mock_client.chat.completions.create = mock_create

        executor = self._make_executor(mock_client)
        collected = []
        async for chunk_text in executor.execute_stream(ctx):
            collected.append(chunk_text)
        assert "tool" in "".join(collected)
