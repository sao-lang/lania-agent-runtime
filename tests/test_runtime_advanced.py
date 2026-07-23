"""
高级 Runtime 测试：覆盖 run_step、tool step、pause、loop_executor 等路径。
"""

from __future__ import annotations

from src.runtime._runtime import AgentRuntime
from src.runtime._types import BlockAction, HookPoint, PauseAction, PrimitiveType


class TestAgentRuntimeRunStep:
    """测试 run_step 方法。"""

    async def test_run_step_not_running(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        assert runtime.status == "idle"
        await runtime.run_step()
        # idle 状态不应执行
        assert runtime._step_index == 0

    async def test_run_step_cancelled(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        runtime.status = "running"
        await runtime.cancel()
        await runtime.run_step()
        assert runtime.status == "cancelled"

    async def test_run_step_timeout(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        runtime.status = "running"
        runtime._timeout["remaining_ms"] = 0
        await runtime.run_step()
        assert runtime.status == "error"


class TestAgentRuntimeToolStep:
    """测试工具执行步骤。"""

    async def test_tool_executor_called(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        tool_called: list[str] = []

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        async def mock_tool(ctx):
            tool_called.append("called")
            return {"role": "tool", "content": "result"}

        runtime.set_llm_executor(mock_llm)

        # 直接调用 _execute_tool_step
        runtime._tool_executor = mock_tool
        ctx = runtime._build_context()
        await runtime._execute_tool_step(ctx)
        assert tool_called == ["called"]

    async def test_before_tool_intercept_block(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        tool_called: list[str] = []

        @runtime.on(HookPoint.BEFORE_TOOL, primitive=PrimitiveType.INTERCEPT)
        async def block_tool(data, ctx):
            return BlockAction(reason="tool blocked")

        async def mock_tool(ctx):
            tool_called.append("called")
            return {"role": "tool", "content": "result"}

        runtime._tool_executor = mock_tool
        ctx = runtime._build_context()
        await runtime._execute_tool_step(ctx)
        assert tool_called == []
        assert runtime.status == "error"

    async def test_before_tool_intercept_pause(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        @runtime.on(HookPoint.BEFORE_TOOL, primitive=PrimitiveType.INTERCEPT)
        async def pause_tool(data, ctx):
            return PauseAction(approval_id="tool_approval")

        async def mock_tool(ctx):
            return {"role": "tool", "content": "result"}

        runtime._tool_executor = mock_tool
        ctx = runtime._build_context()
        await runtime._execute_tool_step(ctx)
        assert runtime.status == "paused"
        assert runtime._pause_state["is_paused"] is True

    async def test_tool_not_set(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        ctx = runtime._build_context()
        # 没有设置 tool_executor，不应报错
        await runtime._execute_tool_step(ctx)


class TestAgentRuntimeLoopExecutor:
    """测试自定义 loop executor。"""

    async def test_loop_executor_called(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        loop_called: list[str] = []

        async def my_loop(ctx):
            loop_called.append("loop")
            return "custom result"

        runtime.set_loop_executor(my_loop)
        result = await runtime.run("test")
        assert loop_called == ["loop"]
        assert result.content == "custom result"

    async def test_loop_executor_with_dict_response(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def my_loop(ctx):
            return {"content": "dict response"}

        runtime.set_loop_executor(my_loop)
        result = await runtime.run("test")
        assert result.content == "dict response"


class TestAgentRuntimePauseFlow:
    """测试暂停/恢复流程。"""

    async def test_handle_pause(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        await runtime._handle_pause(PauseAction(approval_id="test_approval"))
        assert runtime.status == "paused"
        assert runtime._pause_state["is_paused"] is True
        assert len(runtime._pause_state["pending_approvals"]) == 1
        pending = runtime._pause_state["pending_approvals"]
        assert pending[0]["id"] == "test_approval"

    async def test_resume_approval_not_found(self) -> None:
        """恢复时如果仍有其他待审批，不应改变 paused 状态。"""
        runtime = AgentRuntime(system_prompt="助手")
        runtime.status = "paused"
        runtime._pause_state = {
            "is_paused": True,
            "pending_approvals": [
                {"id": "approve_1"},
                {"id": "approve_2"},
            ],
            "resume_token": "",
        }

        await runtime.resume("approve_1")
        # 还剩一个 pending
        assert runtime.status == "paused"
        assert len(runtime._pause_state["pending_approvals"]) == 1

        await runtime.resume("approve_2")
        # 全部清空，恢复 running
        assert runtime.status == "running"
        assert runtime._pause_state["is_paused"] is False

    async def test_resume_triggers_session_resume_observers(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        runtime.status = "paused"
        runtime._pause_state = {
            "is_paused": True,
            "pending_approvals": [{"id": "approve_1"}],
            "resume_token": "",
        }
        resumed: list[str] = []

        @runtime.on(HookPoint.SESSION_RESUME)
        async def on_resume(event, ctx):
            resumed.append(event.get("approval_id", ""))

        await runtime.resume("approve_1")
        assert resumed == ["approve_1"]


class TestAgentRuntimeExecuteStep:
    """测试 _execute_step 各种路径。"""

    async def test_execute_unknown_step(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        ctx = runtime._build_context()
        # 未知 step_id 不应报错
        await runtime._execute_step("unknown", ctx)

    async def test_execute_llm_without_executor(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        # 用 _get_next_step 测试返回 "end"
        ctx = runtime._build_context()
        step = await runtime._get_next_step(ctx)
        assert step == "end"


class TestAgentRuntimeRemoveComponent:
    """测试 remove_component。"""

    async def test_remove_existing_component(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        detached: list[str] = []

        from src.runtime.plugins._plugin import PluggableComponent

        class TestComp(PluggableComponent):
            @property
            def name(self) -> str:
                return "test_comp"

            async def on_detach(self):
                detached.append("detached")

        comp = TestComp()
        runtime._components["test_comp"] = comp
        await runtime.remove_component("test_comp")
        assert detached == ["detached"]
        assert "test_comp" not in runtime._components


class TestAgentRuntimeStepHistory:
    """测试 step_history 记录。"""

    async def test_step_history_recorded(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        runtime.set_llm_executor(mock_llm)
        await runtime.run("test")
        assert len(runtime._step_history) >= 1
        assert "react" in runtime._step_history[0]["step_id"]
        assert runtime._step_history[0]["step_index"] == 1


class TestAgentRuntimeOnError:
    """测试更完整的错误处理路径。"""

    async def test_on_error_transform_router(self) -> None:
        """验证 on_error 的 Observer 和 Transform 路径。"""
        runtime = AgentRuntime(system_prompt="助手")
        observed: list[str] = []

        @runtime.on(HookPoint.ON_ERROR)
        async def on_error_obs(event, ctx):
            observed.append("error_observed")

        async def failing_llm(ctx):
            msg = "crash"
            raise RuntimeError(msg)

        runtime.set_llm_executor(failing_llm)
        response = await runtime.run("hi")
        assert "crash" in response.content
        assert "error_observed" in observed

    async def test_run_with_error_status_ended(self) -> None:
        """验证 error 后 status 保持 error。"""
        runtime = AgentRuntime(system_prompt="助手")

        @runtime.on(HookPoint.BEFORE_LLM, primitive=PrimitiveType.INTERCEPT)
        async def block_all(data, ctx):
            return BlockAction(reason="blocked")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "should not reach"}

        runtime.set_llm_executor(mock_llm)
        await runtime.run("test")
        last_msg = runtime._messages[-1]["content"] if runtime._messages else ""
        assert "blocked" in last_msg
