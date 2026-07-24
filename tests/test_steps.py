"""
测试 StepRunner 和 AgentRuntime 的新功能（BEFORE_SERIALIZE, ON_STREAM_CHUNK）。
"""

from __future__ import annotations

from src.runtime._control import RuntimeController
from src.runtime._runtime import AgentRuntime
from src.runtime._steps._step_runner import StepRunner
from src.runtime._types import BlockAction, HookPoint, PauseAction, PrimitiveType
from src.runtime.hooks._registry import HookRegistry


class TestBeforeSerialize:
    """测试 BEFORE_SERIALIZE 钩子点。"""

    async def test_before_serialize_hook_exists(self) -> None:
        """BEFORE_SERIALIZE 应存在于 HookPoint 枚举中。"""
        assert HookPoint.BEFORE_SERIALIZE.value == "before_serialize"

    async def test_before_serialize_transform_triggered(self) -> None:
        """before_serialize Transform 应在 LLM step 中被调用。"""
        runtime = AgentRuntime(system_prompt="助手")
        called: list[str] = []

        @runtime.on(HookPoint.BEFORE_SERIALIZE, primitive=PrimitiveType.TRANSFORM)
        async def on_serialize(data, ctx):
            called.append("before_serialize")
            return data

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        runtime.set_llm_executor(mock_llm)
        runtime._context_payload.mark_dirty()
        await runtime.run("test")
        assert "before_serialize" in called


class TestOnStreamChunk:
    """测试 ON_STREAM_CHUNK 钩子点。"""

    async def test_emit_stream_chunk_with_transform(self) -> None:
        """emit_stream_chunk 同时触发 Transform 和 Observer。"""
        runtime = AgentRuntime(system_prompt="助手")
        transformed_chunks: list[str] = []

        @runtime.on(HookPoint.ON_STREAM_CHUNK, primitive=PrimitiveType.TRANSFORM)
        async def upper_chunk(data, ctx):
            transformed_chunks.append(data)
            return data.upper()

        observed: list[str] = []

        @runtime.on(HookPoint.ON_STREAM_CHUNK)
        async def observe_chunk(event, ctx):
            observed.append(event.get("chunk", ""))

        await runtime.emit_stream_chunk("hello")
        # Transform 看到原始数据
        assert transformed_chunks == ["hello"]
        # Observer 看到转换后的数据
        assert observed == ["HELLO"]

    async def test_emit_stream_chunk_triggers_observers(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        chunks: list[str] = []

        @runtime.on(HookPoint.ON_STREAM_CHUNK)
        async def on_chunk(event, ctx):
            chunks.append(event.get("chunk", ""))

        await runtime.emit_stream_chunk("hello")
        await runtime.emit_stream_chunk(" world")

        assert chunks == ["hello", " world"]


class TestStepRunner:
    """测试 StepRunner 组件。"""

    async def test_step_runner_llm_step(self) -> None:
        """StepRunner LLM 基本流程（通过 run_llm_only）。"""
        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "step response"}

        runner = StepRunner(
            hooks=hooks,
            llm_executor=mock_llm,
        )

        ctl = RuntimeController(runtime)
        ctx = ctl.build_context()
        result = await runner.run_llm_only(ctx, ctl)
        assert result is not None  # 正常执行，返回 LLMResponse
        assert result.content == "step response"

    async def test_step_runner_tool_step(self) -> None:
        """StepRunner.run_tool_step 基本流程。"""
        hooks = HookRegistry()
        messages: list = []
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_tool(ctx):
            return {"role": "tool", "content": "tool result"}

        runner = StepRunner(
            hooks=hooks,
            tool_executor=mock_tool,
        )

        ctl = RuntimeController(runtime)
        await runner.run_tool_step(
            {"name": "test_tool"},
            messages,
            ctl,
        )
        # 工具结果应追加到 messages
        assert any(m.get("content") == "tool result" for m in messages)

    async def test_step_runner_llm_blocked(self) -> None:
        """before_llm intercept block 时 StepRunner 阻断（通过 run_llm_only）。"""
        from src.runtime._types import BlockAction

        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")

        async def block_llm(data, ctx):
            return BlockAction(reason="no llm")

        hooks.register(
            HookPoint.BEFORE_LLM,
            block_llm,
            primitive=PrimitiveType.INTERCEPT,
        )

        runner = StepRunner(hooks=hooks, llm_executor=None)
        ctl = RuntimeController(runtime)
        ctx = ctl.build_context()
        result = await runner.run_llm_only(ctx, ctl)
        assert result is None  # 阻断时返回 None

    async def test_step_runner_llm_pause(self) -> None:
        """before_llm intercept pause 触发暂停（通过 run_llm_only）。"""
        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")

        async def pause_llm(data, ctx):
            return PauseAction(approval_id="need_approve")

        hooks.register(
            HookPoint.BEFORE_LLM,
            pause_llm,
            primitive=PrimitiveType.INTERCEPT,
        )

        runner = StepRunner(hooks=hooks)
        ctl = RuntimeController(runtime)
        ctx = ctl.build_context()
        result = await runner.run_llm_only(ctx, ctl)
        assert result is None
        assert runtime.status == "paused"

    async def test_step_runner_tool_pause(self) -> None:
        """before_tool intercept pause 触发暂停。"""
        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")

        async def pause_tool(data, ctx):
            return PauseAction(approval_id="tool_pause")

        hooks.register(
            HookPoint.BEFORE_TOOL,
            pause_tool,
            primitive=PrimitiveType.INTERCEPT,
        )

        runner = StepRunner(hooks=hooks)
        ctl = RuntimeController(runtime)
        await runner.run_tool_step({"name": "test"}, [], ctl)
        assert runtime.status == "paused"

    async def test_step_runner_tool_blocked(self) -> None:
        """before_tool intercept block 时 StepRunner 直接返回。"""
        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")

        async def block_tool(data, ctx):
            return BlockAction(reason="no tool")

        hooks.register(
            HookPoint.BEFORE_TOOL,
            block_tool,
            primitive=PrimitiveType.INTERCEPT,
        )

        runner = StepRunner(hooks=hooks, tool_executor=None)
        ctl = RuntimeController(runtime)
        # 不应报错
        await runner.run_tool_step({"name": "test"}, [], ctl)

    async def test_step_runner_no_executors(self) -> None:
        """StepRunner 无 executor 时不报错（通过 run_llm_only）。"""
        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")

        runner = StepRunner(hooks=hooks)
        ctl = RuntimeController(runtime)
        ctx = ctl.build_context()

        result = await runner.run_llm_only(ctx, ctl)
        assert result is None

        await runner.run_tool_step(None, [], ctl)
