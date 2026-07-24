"""
StepRunner 分支覆盖——覆盖剩余未覆盖路径。
"""

from __future__ import annotations

from src.runtime._control import RuntimeController
from src.runtime._runtime import AgentRuntime
from src.runtime._steps._step_runner import StepRunner
from src.runtime._types import (
    AllowAction,
    BlockAction,
    HookPoint,
    PrimitiveType,
)
from src.runtime.hooks._registry import HookRegistry


class TestStepRunnerBranches:
    """StepRunner 分支覆盖。"""

    async def test_llm_response_dict_path(self) -> None:
        """LLM 返回 dict 的路径（通过 run_llm_only）。"""
        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "dict response"}

        runner = StepRunner(hooks=hooks, llm_executor=mock_llm)
        ctl = RuntimeController(runtime)
        ctx = ctl.build_context()
        await runner.run_llm_only(ctx, ctl)
        assert any(m.get("content") == "dict response" for m in ctl.messages)

    async def test_llm_response_str_path(self) -> None:
        """LLM 返回字符串的路径（通过 run_llm_only）。"""
        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_llm(ctx):
            return "string response"

        runner = StepRunner(hooks=hooks, llm_executor=mock_llm)
        ctl = RuntimeController(runtime)
        ctx = ctl.build_context()
        await runner.run_llm_only(ctx, ctl)
        assert any(m.get("content") == "string response" for m in ctl.messages)

    async def test_after_llm_block_action(self) -> None:
        """after_llm BlockAction 路径（通过 run_llm_only）。"""
        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")

        async def block_after(data, ctx):
            return BlockAction(reason="bad output")

        hooks.register(
            HookPoint.AFTER_LLM,
            block_after,
            primitive=PrimitiveType.INTERCEPT,
        )

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "bad content"}

        runner = StepRunner(hooks=hooks, llm_executor=mock_llm)
        ctl = RuntimeController(runtime)
        ctx = ctl.build_context()
        result = await runner.run_llm_only(ctx, ctl)
        assert result is None  # run_llm_only 被阻断时返回 None
        assert runtime.status == "error"

    async def test_after_llm_allow_modified_dict(self) -> None:
        """after_llm AllowAction modified dict 路径（通过 run_step）。"""
        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")

        async def modify_after(data, ctx):
            return AllowAction(modified={"role": "assistant", "content": "fixed"})

        hooks.register(
            HookPoint.AFTER_LLM,
            modify_after,
            primitive=PrimitiveType.INTERCEPT,
        )

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "original"}

        runner = StepRunner(hooks=hooks, llm_executor=mock_llm)
        ctl = RuntimeController(runtime)
        ctx = ctl.build_context()
        await runner.run_step(ctx, ctl)
        # 验证消息被修改
        assert any(m.get("content") == "fixed" for m in ctl.messages)

    async def test_before_serialize_transform(self) -> None:
        """StepRunner 中 before_serialize Transform（通过 run_llm_only）。"""
        hooks = HookRegistry()
        runtime = AgentRuntime(system_prompt="助手")
        runtime._context_payload.mark_dirty()

        serialized: list[str] = []

        async def on_serialize(data, ctx):
            serialized.append("before_serialize")
            return data

        hooks.register(
            HookPoint.BEFORE_SERIALIZE,
            on_serialize,
            primitive=PrimitiveType.TRANSFORM,
        )

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        runner = StepRunner(hooks=hooks, llm_executor=mock_llm)
        ctl = RuntimeController(runtime)
        ctx = ctl.build_context()
        await runner.run_llm_only(ctx, ctl)
        assert "before_serialize" in serialized
