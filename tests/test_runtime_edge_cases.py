"""Tests for runtime edge cases."""

import pytest

from lania_agent_runtime.hooks import (
    AFTER_TOOL,
    BEFORE_TOOL,
    ON_ERROR,
    HookRegistry,
    InterceptResult,
)
from lania_agent_runtime.memory.base import MemoryService
from lania_agent_runtime.memory.sqlite_store import SQLiteMemoryStore
from lania_agent_runtime.models import (
    LLMResponse,
    LLMUsage,
    RuntimeStatus,
    ToolCall,
)
from lania_agent_runtime.runtime import AgentRuntime


@pytest.fixture
def mock_executor():  # noqa: ANN201
    class MockExecutor:
        def __init__(self) -> None:
            self.call_count = 0

        async def execute(self, ctx):
            self.call_count += 1
            content = ctx.messages[-1].get("content", "") if ctx.messages else ""
            return LLMResponse(
                content=f"Echo: {content}",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                finish_reason="stop" if self.call_count < 3 else "stop",
                model="mock",
            )

        async def execute_stream(self, ctx):
            from lania_agent_runtime.executor import AsyncStreamCollector

            content = ctx.messages[-1].get("content", "") if ctx.messages else ""
            text = f"Echo: {content}"
            collector = AsyncStreamCollector()
            collector._content_chunks = [text]
            response = LLMResponse(
                content=text,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                finish_reason="stop",
                model="mock",
            )
            return collector, response

    return MockExecutor()


class TestRuntimeErrorHandling:
    """Test runtime error handling paths."""

    @pytest.mark.asyncio
    async def test_llm_executor_raises_error(self) -> None:
        class FailingExecutor:
            async def execute(self, ctx):
                msg = "LLM API failure"
                raise RuntimeError(msg)

            async def execute_stream(self, ctx):
                msg = "LLM stream failure"
                raise RuntimeError(msg)

        hooks = HookRegistry()
        rt = AgentRuntime(
            session_id="s1",
            agent_id="a1",
            llm_executor=FailingExecutor(),
            hooks=hooks,
        )

        result = await rt.run("Hello")
        assert result is not None

    @pytest.mark.asyncio
    async def test_before_tool_intercept_block(self, mock_executor) -> None:
        async def blocker(data, ctx):
            return InterceptResult(action="block", reason="Tool blocked")

        hooks = HookRegistry()
        hooks.intercept(BEFORE_TOOL, blocker)

        class ToolCallExecutor:
            async def execute(self, ctx):
                tc = ToolCall(
                    id="call_1",
                    name="test_tool",
                    arguments={},
                    raw_arguments="{}",
                )
                return LLMResponse(
                    content="",
                    tool_calls=[tc],
                    finish_reason="tool_calls",
                    model="mock",
                )

            async def execute_stream(self, ctx):
                yield "test"

        async def tool_exec(tc, ctx):
            return {"status": "done"}

        hooks.set_tool_executor(tool_exec)

        rt = AgentRuntime(
            session_id="s1",
            agent_id="a1",
            llm_executor=ToolCallExecutor(),
            hooks=hooks,
        )
        result = await rt.run("Run tool")
        assert result is not None

    @pytest.mark.asyncio
    async def test_tool_executor_raises_error(self) -> None:
        class ToolCallExecutor:
            async def execute(self, ctx):
                tc = ToolCall(
                    id="call_1",
                    name="failing_tool",
                    arguments={},
                    raw_arguments="{}",
                )
                return LLMResponse(
                    content="",
                    tool_calls=[tc],
                    finish_reason="tool_calls",
                    model="mock",
                )

            async def execute_stream(self, ctx):
                yield "test"

        async def failing_tool(tc, ctx):
            msg = "Tool execution failed"
            raise RuntimeError(msg)

        hooks = HookRegistry()
        hooks.set_tool_executor(failing_tool)

        rt = AgentRuntime(
            session_id="s1",
            agent_id="a1",
            llm_executor=ToolCallExecutor(),
            hooks=hooks,
        )
        result = await rt.run("Run failing tool")
        assert result is not None
        # Should have tool message with error
        tool_msgs = [m for m in rt.context.messages if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1

    @pytest.mark.asyncio
    async def test_stream_llm_executor_raises_error(self) -> None:
        class FailingStreamExecutor:
            async def execute(self, ctx):
                return LLMResponse(content="ok")

            async def execute_stream(self, ctx):
                msg = "Stream error"
                raise RuntimeError(msg)

        rt = AgentRuntime(
            session_id="s1",
            agent_id="a1",
            llm_executor=FailingStreamExecutor(),
        )
        chunks = [e async for e in rt.run_stream("Hello")]
        error_chunks = [c for c in chunks if c.type == "error"]
        assert len(error_chunks) >= 1

    @pytest.mark.asyncio
    async def test_stream_before_llm_block(self, mock_executor) -> None:
        async def blocker(data, ctx):
            return InterceptResult(action="block", reason="LLM blocked in stream")

        hooks = HookRegistry()
        hooks.intercept("before_llm", blocker)

        rt = AgentRuntime(
            session_id="s1",
            agent_id="a1",
            llm_executor=mock_executor,
            hooks=hooks,
        )
        chunks = [e async for e in rt.run_stream("Hello")]
        error_chunks = [c for c in chunks if c.type == "error"]
        assert len(error_chunks) >= 1

    @pytest.mark.asyncio
    async def test_multiple_runs_with_session_start(self, mock_executor) -> None:
        rt = AgentRuntime(
            session_id="multi-run",
            agent_id="a1",
            llm_executor=mock_executor,
        )

        # First run should trigger session_start
        await rt.run("First")
        assert len(rt.context.messages) >= 2

        # Second run should not trigger session_start again
        await rt.run("Second")
        assert len(rt.context.messages) >= 4

        # Third run
        r3 = await rt.run("Third")
        assert r3 is not None

    @pytest.mark.asyncio
    async def test_status_transitions(self, mock_executor) -> None:
        rt = AgentRuntime(
            session_id="status-test",
            agent_id="a1",
            llm_executor=mock_executor,
        )
        assert rt.status == RuntimeStatus.IDLE

        await rt.run("Hi")
        assert rt.status == RuntimeStatus.RUNNING

        await rt.destroy()
        assert rt.status == RuntimeStatus.ENDED

    @pytest.mark.asyncio
    async def test_on_error_hook_triggered(self) -> None:
        class FailingExecutor:
            async def execute(self, ctx):
                msg = "Deliberate error"
                raise RuntimeError(msg)

            async def execute_stream(self, ctx):
                yield ""

        errors_caught = []

        async def error_obs(event, ctx):
            errors_caught.append(event.get("error"))

        hooks = HookRegistry()
        hooks.observe(ON_ERROR, error_obs)

        rt = AgentRuntime(
            session_id="error-test",
            agent_id="a1",
            llm_executor=FailingExecutor(),
            hooks=hooks,
        )
        await rt.run("Trigger error")
        assert len(errors_caught) >= 1

    @pytest.mark.asyncio
    async def test_system_prompt_only_added_once(self, mock_executor) -> None:
        rt = AgentRuntime(
            session_id="sys-prompt",
            agent_id="a1",
            llm_executor=mock_executor,
        )
        await rt.run("First", system_prompt="Custom system prompt")
        sys_msgs = [m for m in rt.context.messages if m.get("role") == "system"]
        assert len(sys_msgs) == 1

        # Second call should not add another system prompt
        await rt.run("Second")
        sys_msgs = [m for m in rt.context.messages if m.get("role") == "system"]
        assert len(sys_msgs) == 1

    @pytest.mark.asyncio
    async def test_after_tool_observer(self, mock_executor) -> None:
        observed = []

        async def tool_obs(event, ctx):
            tc = event.get("tool_call")
            observed.append(tc.name if hasattr(tc, "name") else str(tc))

        hooks = HookRegistry()
        hooks.observe(AFTER_TOOL, tool_obs)

        class ToolCallExecutor:
            async def execute(self, ctx):
                tc = ToolCall(
                    id="call_1",
                    name="test_tool",
                    arguments={},
                    raw_arguments="{}",
                )
                return LLMResponse(
                    content="",
                    tool_calls=[tc],
                    finish_reason="tool_calls",
                    model="mock",
                )

            async def execute_stream(self, ctx):
                yield "test"

        async def tool_exec(tc, ctx):
            return {"result": "done"}

        hooks.set_tool_executor(tool_exec)

        rt = AgentRuntime(
            session_id="s1",
            agent_id="a1",
            llm_executor=ToolCallExecutor(),
            hooks=hooks,
        )
        await rt.run("Call tool")
        assert "test_tool" in observed


@pytest.mark.asyncio
async def test_runtime_with_memory_service(mock_executor) -> None:  # noqa: ANN201
    """Test runtime with memory service integration."""
    store = SQLiteMemoryStore()
    await store.initialize()
    memory = MemoryService(store=store)

    rt = AgentRuntime(
        session_id="mem-test",
        agent_id="a1",
        llm_executor=mock_executor,
        memory=memory,
    )

    result = await rt.run("Hello with memory", system_prompt="Bot.")
    assert result is not None
    assert "Hello" in result.content

    # Check memory was committed
    payload = await memory.recall("mem-test")
    assert len(payload.memories) >= 1

    await store.close()
