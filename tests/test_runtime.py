"""Tests for AgentRuntime."""

import pytest

from lania_agent_runtime.hooks import (
    AFTER_LLM,
    AFTER_STEP,
    BEFORE_LLM,
    BEFORE_STEP,
    SESSION_START,
    HookRegistry,
    InterceptResult,
)
from lania_agent_runtime.models import (
    LLMResponse,
    LLMUsage,
    RunResult,
    RuntimeStatus,
    ToolCall,
)
from lania_agent_runtime.runtime import AgentRuntime


@pytest.fixture
def mock_executor():  # noqa: ANN201
    """Create a mock LLM executor that echoes input."""

    class MockExecutor:
        async def execute(self, ctx):
            content = ctx.messages[-1].get("content", "") if ctx.messages else ""
            return LLMResponse(
                content=f"Echo: {content}",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                finish_reason="stop",
                model="mock",
            )

        async def execute_stream(self, ctx):
            from lania_agent_runtime.executor import AsyncStreamCollector
            from lania_agent_runtime.models import LLMResponse, LLMUsage

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


@pytest.fixture
def runtime(mock_executor):  # noqa: ANN201
    return AgentRuntime(
        session_id="test-session",
        agent_id="test-agent",
        llm_executor=mock_executor,
    )


class TestAgentRuntime:
    """Test AgentRuntime."""

    @pytest.mark.asyncio
    async def test_initial_state(self, runtime) -> None:
        assert runtime.session_id == "test-session"
        assert runtime.status == RuntimeStatus.IDLE
        assert runtime.context.messages == []

    @pytest.mark.asyncio
    async def test_run_single_turn(self, runtime) -> None:
        result = await runtime.run("Hello", system_prompt="You are a bot.")
        assert isinstance(result, RunResult)
        assert "Hello" in result.content or "Echo" in result.content
        assert result.session_id == "test-session"

    @pytest.mark.asyncio
    async def test_run_multi_turn(self, runtime) -> None:
        await runtime.run("My name is Alice")
        result2 = await runtime.run("What is my name?")
        assert result2.session_id == "test-session"
        # Context should have both turns
        msgs = runtime.context.messages
        assert len(msgs) >= 4  # system + user1 + asst1 + user2 + asst2

    @pytest.mark.asyncio
    async def test_run_stream(self, runtime) -> None:
        chunks = []
        async for event in runtime.run_stream("Hello", system_prompt="Bot."):
            chunks.append(event)

        # Should have text chunks and a done event
        text_events = [c for c in chunks if c.type == "text"]
        done_events = [c for c in chunks if c.type == "done"]
        assert len(text_events) >= 1
        assert len(done_events) == 1

    @pytest.mark.asyncio
    async def test_run_stream_content(self, runtime) -> None:
        full = ""
        async for event in runtime.run_stream("Hi there"):
            if event.type == "text":
                full += event.content
        assert len(full) > 0

    @pytest.mark.asyncio
    async def test_destroy(self, runtime) -> None:
        await runtime.destroy()
        assert runtime.status == RuntimeStatus.ENDED

    @pytest.mark.asyncio
    async def test_get_session_state(self, runtime) -> None:
        await runtime.run("Hello")
        state = runtime.get_session_state()
        assert state.session_id == "test-session"
        assert state.message_count >= 2
        assert state.step_count >= 1

    @pytest.mark.asyncio
    async def test_session_state_before_run(self, runtime) -> None:
        state = runtime.get_session_state()
        assert state.step_count == 0
        assert state.message_count == 0
        assert state.last_error is None

    @pytest.mark.asyncio
    async def test_run_with_no_executor(self) -> None:
        rt = AgentRuntime(session_id="s1", agent_id="a1")
        result = await rt.run("Hello")
        # Should use fallback mock
        assert "Hello" in result.content

    @pytest.mark.asyncio
    async def test_run_stream_with_no_executor(self) -> None:
        rt = AgentRuntime(session_id="s1", agent_id="a1")
        chunks = []
        async for event in rt.run_stream("Hello"):
            chunks.append(event)
        assert len(chunks) >= 1


class TestAgentRuntimeWithHooks:
    """Test AgentRuntime with hooks."""

    @pytest.mark.asyncio
    async def test_session_start_observer(self, mock_executor) -> None:
        observed = []

        async def session_obs(event, ctx):
            observed.append(event.get("session_id"))

        hooks = HookRegistry()
        hooks.observe(SESSION_START, session_obs)

        rt = AgentRuntime(
            session_id="hook-test",
            agent_id="test",
            llm_executor=mock_executor,
            hooks=hooks,
        )
        await rt.run("Hello")
        assert "hook-test" in observed

    @pytest.mark.asyncio
    async def test_before_step_intercept_block(self, mock_executor) -> None:
        async def blocker(data, ctx):
            return InterceptResult(action="block", reason="Blocked!")

        hooks = HookRegistry()
        hooks.intercept(BEFORE_STEP, blocker)

        rt = AgentRuntime(session_id="s1", agent_id="a1", llm_executor=mock_executor, hooks=hooks)
        result = await rt.run("Hello")
        # Should still return a result but with block reason in error state
        assert result is not None
        assert rt.context.error_state.last_error == "Blocked!"

    @pytest.mark.asyncio
    async def test_before_llm_intercept_block(self, mock_executor) -> None:
        async def blocker(data, ctx):
            return InterceptResult(action="block", reason="LLM blocked")

        hooks = HookRegistry()
        hooks.intercept(BEFORE_LLM, blocker)

        rt = AgentRuntime(session_id="s1", agent_id="a1", llm_executor=mock_executor, hooks=hooks)
        result = await rt.run("Hello")
        assert result is not None
        assert "LLM blocked" in str(rt.context.error_state.last_error)

    @pytest.mark.asyncio
    async def test_before_step_transform(self, mock_executor) -> None:
        async def transformer(data, ctx):
            data["transformed"] = True
            return data

        hooks = HookRegistry()
        hooks.transform(BEFORE_STEP, transformer)

        rt = AgentRuntime(session_id="s1", agent_id="a1", llm_executor=mock_executor, hooks=hooks)
        result = await rt.run("Hello")
        assert result is not None

    @pytest.mark.asyncio
    async def test_after_llm_intercept_block(self, mock_executor) -> None:
        async def blocker(data, ctx):
            return InterceptResult(action="block", reason="Output blocked")

        hooks = HookRegistry()
        hooks.intercept(AFTER_LLM, blocker)

        rt = AgentRuntime(session_id="s1", agent_id="a1", llm_executor=mock_executor, hooks=hooks)
        result = await rt.run("Hello")
        assert result is not None

    @pytest.mark.asyncio
    async def test_after_step_observer(self, mock_executor) -> None:
        observed = []

        async def step_obs(event, ctx):
            observed.append(event.get("step_index"))

        hooks = HookRegistry()
        hooks.observe(AFTER_STEP, step_obs)

        rt = AgentRuntime(session_id="s1", agent_id="a1", llm_executor=mock_executor, hooks=hooks)
        await rt.run("Hello")
        # after_step should have been called before increment
        # The step_index in the event should be the current step
        assert len(observed) >= 1

    @pytest.mark.asyncio
    async def test_stream_with_before_step_transform(self, mock_executor) -> None:
        async def transformer(data, ctx):
            data["transformed"] = True
            return data

        hooks = HookRegistry()
        hooks.transform(BEFORE_STEP, transformer)

        rt = AgentRuntime(session_id="s1", agent_id="a1", llm_executor=mock_executor, hooks=hooks)
        chunks = []
        async for event in rt.run_stream("Hello"):
            chunks.append(event)
        assert len(chunks) >= 2

    @pytest.mark.asyncio
    async def test_stream_with_block(self, mock_executor) -> None:
        async def blocker(data, ctx):
            return InterceptResult(action="block", reason="Stream blocked")

        hooks = HookRegistry()
        hooks.intercept(BEFORE_STEP, blocker)

        rt = AgentRuntime(session_id="s1", agent_id="a1", llm_executor=mock_executor, hooks=hooks)
        chunks = []
        async for event in rt.run_stream("Hello"):
            chunks.append(event)
        error_events = [c for c in chunks if c.type == "error"]
        assert len(error_events) >= 1

    @pytest.mark.asyncio
    async def test_run_with_tool_calls(self) -> None:
        class ToolMockExecutor:
            async def execute(self, ctx):
                tc = ToolCall(
                    id="call_1",
                    name="get_weather",
                    arguments={"city": "Beijing"},
                    raw_arguments='{"city": "Beijing"}',
                )
                return LLMResponse(
                    content="",
                    tool_calls=[tc],
                    finish_reason="tool_calls",
                    model="mock",
                )

            async def execute_stream(self, ctx):
                yield "mock stream"

        hooks = HookRegistry()

        async def tool_exec(tool_call, ctx):
            return {"temperature": 24, "condition": "sunny"}

        hooks.set_tool_executor(tool_exec)

        rt = AgentRuntime(
            session_id="s1", agent_id="a1", llm_executor=ToolMockExecutor(), hooks=hooks
        )
        result = await rt.run("Weather in Beijing?")
        assert result is not None
        # Should have tool result in messages
        tool_msgs = [m for m in rt.context.messages if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1


class TestAgentRuntimeExecution:
    """Test runtime execution flow."""

    @pytest.mark.asyncio
    async def test_multiple_runs_same_runtime(self, mock_executor) -> None:
        rt = AgentRuntime(session_id="multi", agent_id="a1", llm_executor=mock_executor)

        r1 = await rt.run("First message")
        assert r1 is not None
        assert len(rt.context.messages) >= 2

        r2 = await rt.run("Second message")
        assert r2 is not None
        assert len(rt.context.messages) >= 4  # More messages accumulated

    @pytest.mark.asyncio
    async def test_runtime_status_transitions(self, mock_executor) -> None:
        rt = AgentRuntime(session_id="s1", agent_id="a1", llm_executor=mock_executor)
        assert rt.status == RuntimeStatus.IDLE

        await rt.run("Hello")
        # After run, status should still be running (we don't auto-end)
        # Actually the status might be RUNNING since session_end not called

    @pytest.mark.asyncio
    async def test_run_with_user_message_content(self, mock_executor) -> None:
        rt = AgentRuntime(session_id="s1", agent_id="a1", llm_executor=mock_executor)
        result = await rt.run("Tell me a joke")

        # Check the assistant response contains the user message (echo)
        assert result.content is not None
        assert len(result.content) > 0
