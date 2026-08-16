"""
Runtime 层覆盖率补测。

覆盖 RuntimeContext 受限 writer、HelperMixin 响应提取、Controller 属性、
Builder 自动接线、RuntimeConfig 解析分支、HookRegistry 增删改、StepRunner
序列化/拦截/工具分支，以及 Runtime 流式与步进决策路径。
"""

from __future__ import annotations

from typing import Any

import pytest

from src.context._budget import TokenManager
from src.context._config import ContextConfig
from src.context._manager import ContextManager
from src.context._models import SelectionDecision
from src.context._selector import Selector
from src.runtime._runtime import AgentRuntime
from src.runtime._types import (
    AllowAction,
    BlockAction,
    BudgetSnapshot,
    HookPoint,
    PauseAction,
    PrimitiveType,
    RuntimeStatus,
)
from src.runtime.config._runtime_config import RuntimeConfig
from src.runtime.context._context import RuntimeContext
from src.runtime.context._payload import ContextPayload
from src.runtime.hooks._registry import HookRegistry
from src.runtime.llm._models import FinishReason, LLMResponse, LLMUsage, ToolCall
from src.runtime.loops._types import StepStatus
from src.tools import ToolRegistry


def make_llm(content: str = "ok", finish_reason: FinishReason = FinishReason.STOP):
    """构造返回固定内容的 async LLM executor。"""

    async def mock_llm(ctx: Any) -> LLMResponse:
        return LLMResponse(
            content=content,
            finish_reason=finish_reason,
            usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
        )

    return mock_llm


class TestRuntimeContextWriters:
    """RuntimeContext 受限 writer 未覆盖分支。"""

    def test_writers_raise_without_callbacks(self) -> None:
        ctx = RuntimeContext()
        with pytest.raises(RuntimeError, match="set_messages"):
            ctx.set_messages([{}])
        with pytest.raises(RuntimeError, match="set_step_index"):
            ctx.set_step_index(1)
        with pytest.raises(RuntimeError, match="set_budget"):
            ctx.set_budget(BudgetSnapshot())
        with pytest.raises(RuntimeError, match="set_pause_state"):
            ctx.set_pause_state({})

    def test_writers_with_callbacks(self) -> None:
        calls: dict[str, Any] = {}

        def on_messages(messages: list[dict]) -> None:
            calls["messages"] = messages

        def on_step(step: int) -> None:
            calls["step"] = step

        def on_budget(snapshot: BudgetSnapshot) -> None:
            calls["budget"] = snapshot

        def on_pause(state: dict) -> None:
            calls["pause"] = state

        ctx = RuntimeContext(
            _set_messages_callback=on_messages,
            _set_step_index_callback=on_step,
            _set_budget_callback=on_budget,
            _set_pause_state_callback=on_pause,
        )
        ctx.set_messages([{"role": "user", "content": "hi"}])
        ctx.set_step_index(3)
        ctx.set_budget(BudgetSnapshot(token_used=9))
        ctx.set_pause_state({"is_paused": True, "pending_approvals": [], "resume_token": "t"})
        assert calls["messages"][0]["content"] == "hi"
        assert calls["step"] == 3
        assert calls["budget"].token_used == 9
        assert calls["pause"]["is_paused"] is True


class TestHelperMixinCoverage:
    """HelperMixin 未覆盖分支。"""

    async def test_update_context_payload_impl(self) -> None:
        runtime = AgentRuntime(system_prompt="旧")
        runtime._update_context_payload_impl(lambda p: ContextPayload(system_prompt="新"))
        assert runtime._context_payload.system_prompt == "新"

    async def test_set_budget_and_pause_impl(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        ctx = runtime._build_context()
        ctx.set_budget(BudgetSnapshot(token_used=5, token_limit=100))
        assert runtime._budget.token_used == 5
        assert runtime._budget.token_limit == 100
        ctx.set_pause_state(
            {
                "is_paused": True,
                "pending_approvals": [{"id": "a1"}],
                "resume_token": "tok",
            }
        )
        assert runtime._pause_state["is_paused"] is True
        assert runtime._pause_state["resume_token"] == "tok"

    async def test_extract_response_variants(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        assert runtime._extract_response("plain") == "plain"
        assert runtime._extract_response({"content": "c"}) == "c"
        assert runtime._extract_response({"response": "r"}) == "r"
        assert runtime._extract_response({"other": 1}) == "{'other': 1}"
        assert runtime._extract_response(123) == "123"

    async def test_make_result_with_tool_calls(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        runtime._messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "回复"},
        ]
        runtime._last_llm_response = LLMResponse(
            content="回复",
            finish_reason=FinishReason.STOP,
            tool_calls=[ToolCall(id="c1", name="search", arguments={})],
        )
        result = runtime._make_result()
        assert result.content == "回复"
        assert result.tool_calls[0].name == "search"


class TestControllerProperties:
    """RuntimeController 属性补测。"""

    async def test_properties(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        ctl = runtime._controller
        assert ctl.plan is None
        ctl.plan = {"steps": ["llm"]}
        assert ctl.plan == {"steps": ["llm"]}
        assert ctl.hooks is runtime._hooks
        assert ctl.serializer is runtime._serializer
        assert ctl.last_llm_response is None
        response = LLMResponse(content="x", finish_reason=FinishReason.STOP)
        ctl.last_llm_response = response
        assert ctl.last_llm_response is response


class TestBuilderCoverage:
    """RuntimeBuilder 未覆盖分支。"""

    async def test_build_creates_hooks_for_tools_and_memory(self) -> None:
        from src.memory import MemoryService
        from src.memory._backends._sqlite import SQLitePersistence

        persistence = SQLitePersistence(":memory:")
        memory = MemoryService(persistence)
        try:
            runtime = AgentRuntime.builder().tool_registry(ToolRegistry()).memory(memory).build()
            names = {h.name for h in runtime._hooks.list()}
            assert "_tools_schema_refresh" in names
            assert "_context_assembler" in names
            assert "_memory_commit" in names
        finally:
            await memory.close()
            await persistence.close()


class TestRuntimeConfigCoverage:
    """RuntimeConfig 未覆盖分支。"""

    def test_from_dict_non_dict_field_raises(self) -> None:
        with pytest.raises(TypeError, match="应为 dict"):
            RuntimeConfig.from_dict({"llm": "gpt-4o"})

    def test_from_env_nested(self, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_SERVICES__WEATHER__API_KEY", "abc")
        config = RuntimeConfig.from_env()
        assert config.services["weather"]["api_key"] == "abc"

    def test_from_env_single_underscore_section(self, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_LLM_MODEL", "gpt-4o")
        config = RuntimeConfig.from_env()
        assert config.llm["model"] == "gpt-4o"

    def test_from_yaml_non_dict_raises(self, tmp_path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("just-a-string\n", encoding="utf-8")
        with pytest.raises(ValueError, match="顶层必须为字典"):
            RuntimeConfig.from_yaml(path)

    def test_from_yaml_missing_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            RuntimeConfig.from_yaml(tmp_path / "nope.yaml")


class TestHookRegistryCoverage:
    """HookRegistry 增删改补测。"""

    async def test_enable_disable_replace_remove(self) -> None:
        registry = HookRegistry()

        async def handler(data: Any, ctx: Any) -> Any:
            return data

        handler_id = registry.register(
            HookPoint.AFTER_LLM, handler, primitive=PrimitiveType.TRANSFORM
        )
        registry.enable(handler_id)
        assert registry.list(HookPoint.AFTER_LLM)[0].enabled is True
        registry.disable(handler_id)
        assert registry.list(HookPoint.AFTER_LLM)[0].enabled is False

        async def new_handler(data: Any, ctx: Any) -> Any:
            return data

        registry.replace(handler_id, new_handler)
        assert registry.list(HookPoint.AFTER_LLM)[0].handler is new_handler
        registry.remove(handler_id)
        assert registry.list(HookPoint.AFTER_LLM) == []

    async def test_copy(self) -> None:
        registry = HookRegistry()

        async def handler(data: Any, ctx: Any) -> Any:
            return data

        registry.register(HookPoint.AFTER_LLM, handler, primitive=PrimitiveType.TRANSFORM)
        copied = registry.copy()
        assert len(copied.list()) == 1

    async def test_unknown_ops_raise(self) -> None:
        registry = HookRegistry()
        with pytest.raises(KeyError):
            registry.remove("nope")
        with pytest.raises(KeyError):
            registry.enable("nope")
        with pytest.raises(KeyError):
            registry.disable("nope")
        with pytest.raises(KeyError):
            registry.replace("nope", lambda d, c: d)


class TestStepRunnerCoverage:
    """StepRunner 未覆盖分支。"""

    async def test_tool_step_none_result(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_tool(ctx: Any) -> None:
            return None

        runtime.set_tool_executor(mock_tool)
        await runtime._step_runner.run_tool_step({}, [], runtime._controller)
        assert runtime._controller.messages == []

    async def test_llm_only_assembled_messages(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        runtime.set_llm_executor(make_llm())
        runtime._context_payload.assembled_messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = await runtime._step_runner.run_llm_only(
            runtime._build_context(), runtime._controller
        )
        assert result is not None
        assert runtime._controller.messages[0]["role"] == "system"
        assert runtime._context_payload.assembled_messages is None

    async def test_llm_only_dirty_replace_system(self) -> None:
        runtime = AgentRuntime(system_prompt="新系统")
        runtime.set_llm_executor(make_llm())
        runtime._controller.messages = [
            {"role": "system", "content": "旧系统"},
            {"role": "user", "content": "hi"},
        ]
        runtime._context_payload.mark_dirty()
        result = await runtime._step_runner.run_llm_only(
            runtime._build_context(), runtime._controller
        )
        assert result is not None
        assert runtime._controller.messages[0]["content"] == "新系统"
        assert runtime._controller.messages[1]["content"] == "hi"

    async def test_llm_only_dirty_prepend_system(self) -> None:
        runtime = AgentRuntime(system_prompt="新系统")
        runtime.set_llm_executor(make_llm())
        runtime._controller.messages = [{"role": "user", "content": "hi"}]
        runtime._context_payload.mark_dirty()
        result = await runtime._step_runner.run_llm_only(
            runtime._build_context(), runtime._controller
        )
        assert result is not None
        assert runtime._controller.messages[0]["role"] == "system"
        assert runtime._controller.messages[1]["content"] == "hi"

    async def test_llm_only_serializer_empty(self) -> None:
        runtime = AgentRuntime(system_prompt="")
        runtime.set_llm_executor(make_llm())
        runtime._controller.messages = []
        runtime._context_payload.mark_dirty()
        runtime._step_runner._serializer = _EmptySerializer()
        result = await runtime._step_runner.run_llm_only(
            runtime._build_context(), runtime._controller
        )
        assert result is not None

    async def test_llm_only_allow_action_modified(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        runtime.set_llm_executor(make_llm("原文"))

        @runtime.on(HookPoint.AFTER_LLM, primitive=PrimitiveType.INTERCEPT)
        async def modify(data: Any, ctx: Any) -> AllowAction:
            return AllowAction(
                modified=LLMResponse(content="改写", finish_reason=FinishReason.STOP)
            )

        result = await runtime._step_runner.run_llm_only(
            runtime._build_context(), runtime._controller
        )
        assert result is not None
        assert runtime._controller.messages[-1]["content"] == "改写"

    async def test_run_step_no_executor(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        step_result = await runtime._step_runner.run_step(
            runtime._build_context(), runtime._controller
        )
        assert step_result.status == StepStatus.ERROR
        assert "未设置" in (step_result.error or "")

    async def test_run_step_after_llm_blocked(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        runtime.set_llm_executor(make_llm())

        @runtime.on(HookPoint.AFTER_LLM, primitive=PrimitiveType.INTERCEPT)
        async def block(data: Any, ctx: Any) -> BlockAction:
            return BlockAction(reason="阻断")

        step_result = await runtime._step_runner.run_step(
            runtime._build_context(), runtime._controller
        )
        assert step_result.status == StepStatus.BLOCKED

    async def test_run_step_allow_action_modified_variants(self) -> None:
        for modified in (
            LLMResponse(content="llm改", finish_reason=FinishReason.STOP),
            {"role": "assistant", "content": "dict改"},
            "str改",
        ):
            runtime = AgentRuntime(system_prompt="助手")
            runtime.set_llm_executor(make_llm("原文"))

            @runtime.on(HookPoint.AFTER_LLM, primitive=PrimitiveType.INTERCEPT)
            async def modify(data: Any, ctx: Any, m: Any = modified) -> AllowAction:
                return AllowAction(modified=m)

            step_result = await runtime._step_runner.run_step(
                runtime._build_context(), runtime._controller
            )
            assert step_result.status == StepStatus.SUCCESS
            assert runtime._controller.messages[-1]["role"] == "assistant"

    async def test_run_step_before_tool_pause(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_llm(ctx: Any) -> LLMResponse:
            return LLMResponse(
                content="",
                finish_reason=FinishReason.TOOL_CALLS,
                tool_calls=[ToolCall(id="c1", name="search", arguments={})],
            )

        runtime.set_llm_executor(mock_llm)

        @runtime.on(HookPoint.BEFORE_TOOL, primitive=PrimitiveType.INTERCEPT)
        async def pause(data: Any, ctx: Any) -> PauseAction:
            return PauseAction(approval_id="a1")

        step_result = await runtime._step_runner.run_step(
            runtime._build_context(), runtime._controller
        )
        assert step_result.status == StepStatus.PAUSED

    async def test_run_step_tool_results_variants(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_llm(ctx: Any) -> LLMResponse:
            return LLMResponse(
                content="",
                finish_reason=FinishReason.TOOL_CALLS,
                tool_calls=[ToolCall(id="c1", name="search", arguments={})],
            )

        async def mock_tool(ctx: Any) -> list:
            return [None, {"role": "tool", "tool_call_id": "c1", "content": "dict"}, "str结果"]

        runtime.set_llm_executor(mock_llm)
        runtime.set_tool_executor(mock_tool)
        step_result = await runtime._step_runner.run_step(
            runtime._build_context(), runtime._controller
        )
        assert step_result.status == StepStatus.SUCCESS
        contents = [
            m.get("content") for m in runtime._controller.messages if m.get("role") == "tool"
        ]
        assert "dict" in contents
        assert "str结果" in contents


class _EmptySerializer:
    """返回空列表的序列化器替身。"""

    async def serialize(self, payload: Any) -> list:
        return []


class TestRuntimeCoverage:
    """Runtime 未覆盖分支。"""

    async def test_run_stream_basic(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        runtime.set_llm_executor(make_llm("你好"))
        events = [e async for e in runtime.run_stream("hello")]
        assert any(e.type == "done" for e in events)
        assert runtime.status == RuntimeStatus.ENDED

    async def test_run_stream_error(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def bad_llm(ctx: Any) -> LLMResponse:
            raise RuntimeError("boom")

        runtime.set_llm_executor(bad_llm)
        events = [e async for e in runtime.run_stream("hello")]
        assert any(e.type == "error" for e in events)
        assert runtime.status == RuntimeStatus.ERROR

    async def test_get_next_step_paths(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        ctx = runtime._build_context()

        async def router(c: Any) -> str:
            return "custom"

        runtime._router = router
        assert await runtime._get_next_step(ctx) == "custom"
        runtime._router = None

        runtime._plan = {"steps": ["llm", "end"]}
        assert await runtime._get_next_step(ctx) == "llm"
        runtime._step_index = 2
        assert await runtime._get_next_step(ctx) == "end"
        runtime._plan = None

        runtime._last_llm_response = LLMResponse(
            content="",
            finish_reason=FinishReason.TOOL_CALLS,
            tool_calls=[ToolCall(id="c1", name="t", arguments={})],
        )
        runtime._messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "t"}}],
            }
        ]
        assert await runtime._get_next_step(ctx) == "tool"
        runtime._messages.append({"role": "tool", "tool_call_id": "c1", "content": "r"})
        assert await runtime._get_next_step(ctx) == "llm"

        runtime._last_llm_response = LLMResponse(content="stop", finish_reason=FinishReason.STOP)
        assert await runtime._get_next_step(ctx) == "end"
        runtime._last_llm_response = None
        runtime._llm_executor = make_llm()
        assert await runtime._get_next_step(ctx) == "llm"

    async def test_has_pending_tool_calls(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        assert runtime._has_pending_tool_calls() is False
        runtime._messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "t"}}],
            }
        ]
        assert runtime._has_pending_tool_calls() is True
        runtime._messages.append({"role": "tool", "tool_call_id": "c1", "content": "r"})
        assert runtime._has_pending_tool_calls() is False

    async def test_execute_step_llm(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        runtime.set_llm_executor(make_llm("ok"))
        await runtime._execute_step("llm", runtime._build_context())
        assert runtime._messages[-1]["role"] == "assistant"


class TestBudgetAndSelectorCoverage:
    """预算与选取器剩余分支。"""

    async def test_sum_payload_tokens(self) -> None:
        payload = ContextPayload(
            system_prompt="sys",
            memories=["m"],
            rag_documents=["d"],
            injected_context=["c"],
            history=[{"role": "user", "content": "h"}],
            tool_results=["r"],
        )
        total = TokenManager()._sum_payload_tokens(payload)
        assert total > 0

    async def test_selector_sliding_window_inner_tool_loop(self) -> None:
        selector = Selector()
        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b", "tool_calls": [{"id": "c1"}]},
                {"role": "tool", "tool_call_id": "c1", "content": "r1"},
                {"role": "assistant", "content": "c", "tool_calls": [{"id": "c2"}]},
            )
        )
        decision = await selector.select(ctx, ContextConfig(preserve_turns=10))
        assert decision.preserve_message_count >= 1

    async def test_selector_skip_middle_and_open_turn(self) -> None:
        selector = Selector()
        ctx = RuntimeContext(
            messages=(
                {"role": "assistant", "content": "a"},
                {"role": "assistant", "content": "b"},
                {"role": "user", "content": "c"},
            )
        )
        decision = await selector.select(ctx, ContextConfig(preserve_turns=10))
        assert decision.preserve_message_count >= 1

    async def test_selector_other_role_with_open_turn(self) -> None:
        selector = Selector()
        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "a"},
                {"role": "meta", "content": "x"},
                {"role": "tool", "content": "r"},
            )
        )
        decision = await selector.select(ctx, ContextConfig(preserve_turns=10))
        assert decision is not None

    async def test_selector_standalone_assistant_open_turn(self) -> None:
        selector = Selector()
        ctx = RuntimeContext(messages=({"role": "assistant", "content": "a"},))
        decision = await selector.select(ctx, ContextConfig(preserve_turns=10))
        assert decision.keep_from_index == 0

    async def test_context_manager_raw_messages_true_branch(self) -> None:
        manager = ContextManager(memory=AnyRecall())
        ctx = RuntimeContext(
            messages=(
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            )
        )
        decision = SelectionDecision(keep_from_index=0)
        raw = manager._get_raw_messages(ctx, decision)
        assert len(raw) == 2


class AnyRecall:
    """满足 MemoryRecallProtocol 的替身。"""

    async def recall_raw(self, **kwargs: Any) -> Any:
        from src.memory._types import RecallResult

        return RecallResult()
