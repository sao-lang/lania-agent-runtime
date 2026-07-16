"""Tests for HookRegistry."""

import pytest

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.hooks import (
    AFTER_LLM,
    AFTER_STEP,
    AFTER_TOOL,
    ALL_HOOK_POINTS,
    BEFORE_LLM,
    BEFORE_STEP,
    BEFORE_TOOL,
    ON_ERROR,
    ON_STREAM_CHUNK,
    SESSION_END,
    SESSION_START,
    HookRegistry,
    InterceptResult,
)


@pytest.fixture
def ctx():  # noqa: ANN201
    return RuntimeContext(session_id="test", agent_id="test")


@pytest.fixture
def registry():  # noqa: ANN201
    return HookRegistry()


class TestHookRegistry:
    """Test HookRegistry."""

    def test_all_hook_points_exist(self, registry) -> None:
        for point in ALL_HOOK_POINTS:
            hooks = registry.get_hooks_at(point)
            assert hooks == []

    def test_register_observe(self, registry, ctx) -> None:
        async def observer(event, c):
            event["observed"] = True

        registry.observe(SESSION_START, observer, "test_observer")
        hooks = registry.get_hooks_at(SESSION_START)
        assert len(hooks) == 1
        assert hooks[0]["type"] == "observe"

    @pytest.mark.asyncio
    async def test_run_observers(self, registry, ctx) -> None:
        results = []

        async def obs1(event, c):
            results.append("obs1")

        async def obs2(event, c):
            results.append("obs2")

        registry.observe(SESSION_START, obs1)
        registry.observe(SESSION_START, obs2)

        await registry.run_observers(SESSION_START, {}, ctx)
        assert results == ["obs1", "obs2"]

    def test_register_transform(self, registry) -> None:
        async def transformer(data, c):
            return data + 1

        registry.transform(BEFORE_STEP, transformer)
        hooks = registry.get_hooks_at(BEFORE_STEP)
        assert len(hooks) == 1
        assert hooks[0]["type"] == "transform"

    @pytest.mark.asyncio
    async def test_run_transformers_pipeline(self, registry, ctx) -> None:
        async def add_one(data, c):
            return data + 1

        async def double(data, c):
            return data * 2

        registry.transform(BEFORE_STEP, add_one)
        registry.transform(BEFORE_STEP, double)

        result = await registry.run_transformers(BEFORE_STEP, 1, ctx)
        assert result == 4  # (1 + 1) * 2

    def test_register_intercept(self, registry) -> None:
        async def guard(data, c):
            return InterceptResult(action="allow")

        registry.intercept(BEFORE_LLM, guard)
        hooks = registry.get_hooks_at(BEFORE_LLM)
        assert len(hooks) == 1
        assert hooks[0]["type"] == "intercept"

    @pytest.mark.asyncio
    async def test_run_interceptors_allow(self, registry, ctx) -> None:
        async def guard(data, c):
            return InterceptResult(action="allow")

        registry.intercept(BEFORE_LLM, guard)
        result = await registry.run_interceptors(BEFORE_LLM, {}, ctx)
        assert result.action == "allow"

    @pytest.mark.asyncio
    async def test_run_interceptors_block(self, registry, ctx) -> None:
        async def guard1(data, c):
            return InterceptResult(action="allow")

        async def guard2(data, c):
            return InterceptResult(action="block", reason="blocked!")

        async def guard3(data, c):
            return InterceptResult(action="allow")

        registry.intercept(BEFORE_LLM, guard1)
        registry.intercept(BEFORE_LLM, guard2)
        registry.intercept(BEFORE_LLM, guard3)

        result = await registry.run_interceptors(BEFORE_LLM, {}, ctx)
        assert result.action == "block"
        assert result.reason == "blocked!"

    @pytest.mark.asyncio
    async def test_run_interceptors_pause(self, registry, ctx) -> None:
        async def guard(data, c):
            return InterceptResult(action="pause", approval_id="approval_1")

        registry.intercept(BEFORE_TOOL, guard)
        result = await registry.run_interceptors(BEFORE_TOOL, {}, ctx)
        assert result.action == "pause"
        assert result.approval_id == "approval_1"

    def test_set_and_run_router(self, registry, ctx) -> None:
        async def router(c):
            return "next_step"

        registry.set_router(router)
        assert registry.has_router() is True

    @pytest.mark.asyncio
    async def test_router_none(self, registry, ctx) -> None:
        result = await registry.run_router(ctx)
        assert result == "end"

    @pytest.mark.asyncio
    async def test_router_custom(self, registry, ctx) -> None:
        async def router(c):
            return "llm_step"

        registry.set_router(router)
        result = await registry.run_router(ctx)
        assert result == "llm_step"

    def test_set_llm_executor(self, registry) -> None:
        async def executor(c):
            return "response"

        registry.set_llm_executor(executor)
        assert registry.has_llm_executor() is True

    @pytest.mark.asyncio
    async def test_run_llm_executor(self, registry, ctx) -> None:
        async def executor(c):
            return {"content": "hello"}

        registry.set_llm_executor(executor)
        result = await registry.run_llm_executor(ctx)
        assert result["content"] == "hello"

    @pytest.mark.asyncio
    async def test_run_llm_executor_not_set(self, registry, ctx) -> None:
        with pytest.raises(RuntimeError, match="LLM executor not set"):
            await registry.run_llm_executor(ctx)

    def test_set_tool_executor(self, registry) -> None:
        async def executor(tc, c):
            return {"result": "done"}

        registry.set_tool_executor(executor)

    @pytest.mark.asyncio
    async def test_run_tool_executor(self, registry, ctx) -> None:
        async def executor(tc, c):
            return {"result": "done"}

        registry.set_tool_executor(executor)
        result = await registry.run_tool_executor({"name": "test"}, ctx)
        assert result["result"] == "done"

    @pytest.mark.asyncio
    async def test_run_tool_executor_not_set(self, registry, ctx) -> None:
        with pytest.raises(RuntimeError, match="Tool executor not set"):
            await registry.run_tool_executor({"name": "test"}, ctx)

    def test_set_loop_executor(self, registry) -> None:
        async def executor(c):
            pass

        registry.set_loop_executor(executor)

    @pytest.mark.asyncio
    async def test_run_loop_executor(self, registry, ctx) -> None:
        async def executor(c):
            return "loop_done"

        registry.set_loop_executor(executor)
        result = await registry.run_loop_executor(ctx)
        assert result == "loop_done"

    def test_register_invalid_point(self, registry) -> None:
        with pytest.raises(ValueError, match="Unknown hook point"):
            registry.register("invalid_point", "observe", lambda e, c: None)

    def test_get_hooks_at_empty(self, registry) -> None:
        hooks = registry.get_hooks_at(BEFORE_LLM)
        assert hooks == []

    def test_mixed_hooks_at_same_point(self, registry) -> None:
        async def obs(e, c):
            pass

        async def tf(data, c):
            return data

        async def ic(data, c):
            return InterceptResult(action="allow")

        registry.observe(BEFORE_STEP, obs)
        registry.transform(BEFORE_STEP, tf)
        registry.intercept(BEFORE_STEP, ic)

        hooks = registry.get_hooks_at(BEFORE_STEP)
        assert len(hooks) == 3
        types = [h["type"] for h in hooks]
        assert types == ["observe", "transform", "intercept"]

    def test_register_with_custom_name(self, registry) -> None:
        async def obs(e, c):
            pass

        registry.observe(SESSION_START, obs, "my_custom_name")
        hooks = registry.get_hooks_at(SESSION_START)
        assert hooks[0]["name"] == "my_custom_name"

    def test_all_hook_points_listed(self) -> None:
        expected = [
            SESSION_START,
            SESSION_END,
            BEFORE_STEP,
            AFTER_STEP,
            BEFORE_LLM,
            AFTER_LLM,
            BEFORE_TOOL,
            AFTER_TOOL,
            ON_ERROR,
            ON_STREAM_CHUNK,
        ]
        assert ALL_HOOK_POINTS == expected
