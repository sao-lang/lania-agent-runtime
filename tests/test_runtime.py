"""
测试 AgentRuntime：核心执行、Hook 注册、组件管理。
"""

from __future__ import annotations

from src.runtime._runtime import AgentRuntime
from src.runtime._types import (
    AllowAction,
    BlockAction,
    HookPoint,
    PrimitiveType,
    RunResult,
    SessionSnapshot,
    StreamEvent,
)
from src.runtime.plugins._plugin import PluggableComponent, Plugin


class TestAgentRuntimeInit:
    """测试 AgentRuntime 初始化。"""

    async def test_default_initialization(self) -> None:
        runtime = AgentRuntime(system_prompt="你是一个助手")
        assert runtime.session_id != ""
        assert runtime.agent_id != ""
        assert runtime.status == "idle"

    async def test_custom_agent_id(self) -> None:
        runtime = AgentRuntime(system_prompt="助手", agent_id="my_agent")
        assert runtime.agent_id == "my_agent"

    async def test_empty_system_prompt(self) -> None:
        runtime = AgentRuntime(system_prompt="")
        assert runtime.status == "idle"


class TestAgentRuntimeRegister:
    """测试 AgentRuntime 的注册方法。"""

    async def test_observe(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def handler(event, ctx):
            pass

        handler_id = runtime.observe(HookPoint.AFTER_LLM, handler, name="test_obs")
        assert handler_id is not None
        assert "test_obs" in handler_id

        handlers = runtime._hooks.list(HookPoint.AFTER_LLM)
        # AFTER_LLM 有默认预算 Transform + 刚注册的 Observer
        transforms = [h for h in handlers if h.primitive == PrimitiveType.TRANSFORM]
        observers = [h for h in handlers if h.primitive == PrimitiveType.OBSERVER]
        assert len(transforms) == 1
        assert transforms[0].name == "_default_budget"
        assert len(observers) == 1
        assert observers[0].name == "test_obs"

    async def test_transform(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def handler(data, ctx):
            return data

        handler_id = runtime.transform(HookPoint.BEFORE_LLM, handler, name="test_tf")
        assert handler_id is not None

        handlers = runtime._hooks.list(HookPoint.BEFORE_LLM)
        # 2 个 Transform：_tools_schema_refresh + test_tf
        assert len(handlers) == 2
        assert handlers[0].primitive == PrimitiveType.TRANSFORM
        assert handlers[1].primitive == PrimitiveType.TRANSFORM
        names = {h.name for h in handlers}
        assert "test_tf" in names
        assert "_tools_schema_refresh" in names

    async def test_intercept(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def handler(data, ctx):
            return AllowAction()

        handler_id = runtime.intercept(HookPoint.BEFORE_TOOL, handler, name="test_ic")
        assert handler_id is not None

        handlers = runtime._hooks.list(HookPoint.BEFORE_TOOL)
        assert len(handlers) == 1
        assert handlers[0].primitive == PrimitiveType.INTERCEPT

    async def test_register_generic(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def handler(event, ctx):
            pass

        handler_id = runtime.register(HookPoint.ON_ERROR, handler, primitive=PrimitiveType.OBSERVER)
        assert handler_id is not None


class TestAgentRuntimeDecorator:
    """测试 @runtime.on 装饰器。"""

    async def test_on_decorator(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        @runtime.on(HookPoint.AFTER_LLM)
        async def my_observer(event, ctx):
            pass

        handlers = runtime._hooks.list(HookPoint.AFTER_LLM)
        # AFTER_LLM 有默认预算 Transform + 刚注册的 Observer
        assert len(handlers) == 2
        observers = [h for h in handlers if h.primitive == PrimitiveType.OBSERVER]
        assert len(observers) == 1
        assert observers[0].primitive == PrimitiveType.OBSERVER

    async def test_on_decorator_with_transform(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        @runtime.on(HookPoint.BEFORE_LLM, primitive=PrimitiveType.TRANSFORM)
        async def my_transform(data, ctx):
            return data

        handlers = runtime._hooks.list(HookPoint.BEFORE_LLM)
        # 2 个 Transform：_tools_schema_refresh + my_transform
        assert len(handlers) == 2
        assert all(h.primitive == PrimitiveType.TRANSFORM for h in handlers)


class TestAgentRuntimeEngine:
    """测试 AgentRuntime 引擎替换方法。"""

    async def test_set_router(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def my_router(ctx):
            return "llm"

        runtime.set_router(my_router)
        assert runtime._router is my_router

    async def test_set_llm_executor(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def my_llm(ctx):
            return {"role": "assistant", "content": "hello"}

        runtime.set_llm_executor(my_llm)
        assert runtime._llm_executor is my_llm

    async def test_set_tool_executor(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def my_tool(ctx):
            return {"role": "tool", "content": "result"}

        runtime.set_tool_executor(my_tool)
        assert runtime._tool_executor is my_tool

    async def test_set_loop_executor(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def my_loop(ctx):
            return "done"

        runtime.set_loop_executor(my_loop)
        assert runtime._loop_executor is my_loop


class TestAgentRuntimeUse:
    """测试 runtime.use() 组件管理。"""

    async def test_use_pluggable_component(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        attached: list[str] = []

        class TestComponent(PluggableComponent):
            @property
            def name(self) -> str:
                return "test_component"

            async def on_attach(self, rt):
                attached.append("attached")

            async def on_detach(self):
                attached.append("detached")

        comp = TestComponent()
        name = await runtime.use(comp)
        assert name == "test_component"
        assert attached == ["attached"]

        # 卸载
        await runtime.remove_component("test_component")
        assert attached == ["attached", "detached"]

    async def test_use_plugin(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        registered: list[str] = []

        class TestPlugin(Plugin):
            @property
            def name(self) -> str:
                return "test_plugin"

            def _declare_hooks(self):
                return [
                    (HookPoint.AFTER_LLM, PrimitiveType.OBSERVER, self._log),
                ]

            async def _log(self, event, ctx):
                registered.append("logged")

        plugin = TestPlugin()
        await runtime.use(plugin)

        hooks = runtime._hooks.list(HookPoint.AFTER_LLM)
        # AFTER_LLM 有默认预算 Transform + Plugin 注册的 Observer
        transforms = [h for h in hooks if h.primitive == PrimitiveType.TRANSFORM]
        observers = [h for h in hooks if h.primitive == PrimitiveType.OBSERVER]
        assert len(transforms) >= 1
        assert len(observers) == 1

    async def test_remove_component_nonexistent(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        await runtime.remove_component("nonexistent")
        # 不应抛出异常


class TestAgentRuntimeRun:
    """测试 AgentRuntime.run() 执行流程。"""

    async def test_run_with_llm_executor(self) -> None:
        runtime = AgentRuntime(system_prompt="你是一个助手")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "你好，有什么可以帮助你的？"}

        runtime.set_llm_executor(mock_llm)

        response = await runtime.run("你好")
        assert response.content == "你好，有什么可以帮助你的？"
        assert runtime.status == "ended"

    async def test_run_observers_triggered(self) -> None:
        """验证 session_start / session_end 的 Observer 被触发。"""
        runtime = AgentRuntime(system_prompt="助手")
        events: list[str] = []

        @runtime.on(HookPoint.SESSION_START)
        async def on_start(event, ctx):
            events.append("start")

        @runtime.on(HookPoint.SESSION_END)
        async def on_end(event, ctx):
            events.append("end")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        runtime.set_llm_executor(mock_llm)
        await runtime.run("test")

        assert "start" in events
        assert "end" in events

    async def test_before_llm_transform(self) -> None:
        """验证 before_llm Transformer 被执行。"""
        runtime = AgentRuntime(system_prompt="助手")
        transformed: list[str] = []

        @runtime.on(HookPoint.BEFORE_LLM, primitive=PrimitiveType.TRANSFORM)
        async def my_transform(data, ctx):
            transformed.append("transformed")
            return data

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        runtime.set_llm_executor(mock_llm)
        await runtime.run("test")
        # Transformer 在每次 step loop 的 before_llm 阶段都会被调用
        assert len(transformed) >= 1
        assert all(t == "transformed" for t in transformed)

    async def test_before_llm_intercept_block(self) -> None:
        """验证 before_llm Interceptor block 会终止执行。"""
        runtime = AgentRuntime(system_prompt="助手")

        @runtime.on(HookPoint.BEFORE_LLM, primitive=PrimitiveType.INTERCEPT)
        async def block_all(data, ctx):
            return BlockAction(reason="blocked")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "should not reach"}

        runtime.set_llm_executor(mock_llm)
        response = await runtime.run("test")
        assert "blocked" in response.content  # on_error 返回错误消息
        assert runtime.status == "error"

    async def test_after_llm_observers(self) -> None:
        """验证 after_llm Observer 被触发。"""
        runtime = AgentRuntime(system_prompt="助手")
        observed: list[str] = []

        @runtime.on(HookPoint.AFTER_LLM)
        async def log_response(event, ctx):
            observed.append("observed")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        runtime.set_llm_executor(mock_llm)
        await runtime.run("test")
        # Observer 在每次 LLM step 后都会被触发
        assert len(observed) >= 1
        assert all(t == "observed" for t in observed)

    async def test_after_llm_intercept_modified(self) -> None:
        """验证 after_llm Interceptor 的 modified 替换 assistant 消息。"""
        runtime = AgentRuntime(system_prompt="助手")

        @runtime.on(HookPoint.AFTER_LLM, primitive=PrimitiveType.INTERCEPT)
        async def modify_response(data, ctx):
            return AllowAction(modified="modified content")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "original"}

        runtime.set_llm_executor(mock_llm)
        response = await runtime.run("test")
        assert "modified content" in response.content


class TestAgentRuntimeCancel:
    """测试取消功能。"""

    async def test_cancel(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        await runtime.cancel()
        assert runtime.status == "cancelled"
        assert runtime._cancelled is True


class TestAgentRuntimeResume:
    """测试暂停/恢复功能。"""

    async def test_resume_not_paused(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        await runtime.resume("some_id")
        assert runtime.status == "idle"

    async def test_resume_clears_pending(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        runtime.status = "paused"
        runtime._pause_state = {
            "is_paused": True,
            "pending_approvals": [{"id": "approve_1"}],
            "resume_token": "",
        }

        await runtime.resume("approve_1")
        assert runtime.status == "running"
        assert runtime._pause_state["is_paused"] is False
        assert runtime._pause_state["pending_approvals"] == []


class TestAgentRuntimeBuildContext:
    """测试 _build_context 方法。"""

    async def test_build_context(self) -> None:
        runtime = AgentRuntime(
            system_prompt="助手",
            agent_id="test_agent",
        )
        runtime.session_id = "test_session"
        runtime._step_index = 5

        ctx = runtime._build_context()
        assert ctx.session_id == "test_session"
        assert ctx.agent_id == "test_agent"
        assert ctx.step_index == 5
        assert ctx.services == {"_runtime": runtime}

        # 验证回调函数可用
        ctx.set_plan({"steps": ["llm"]})
        assert runtime._plan == {"steps": ["llm"]}

        ctx.deduct_budget(100)
        assert runtime._budget.token_used == 100

    async def test_build_context_with_services(self) -> None:
        runtime = AgentRuntime(
            system_prompt="助手",
            services={"memory": object()},
        )
        ctx = runtime._build_context()
        assert "memory" in ctx.services


class TestAgentRuntimeError:
    """测试错误处理路径。"""

    async def test_on_error_observers(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")
        errors: list[str] = []

        @runtime.on(HookPoint.ON_ERROR)
        async def handle_error(event, ctx):
            errors.append(event.get("error", ""))

        async def failing_llm(ctx):
            msg = "LLM 调用失败"
            raise RuntimeError(msg)

        runtime.set_llm_executor(failing_llm)
        response = await runtime.run("test")
        assert "LLM 调用失败" in response.content
        assert len(errors) > 0
        assert "LLM 调用失败" in errors[0]

    async def test_error_state_updated(self) -> None:
        runtime = AgentRuntime(system_prompt="助手")

        async def failing_llm(ctx):
            raise ValueError("test error")

        runtime.set_llm_executor(failing_llm)
        await runtime.run("test")
        assert runtime._error_state["consecutive_errors"] >= 1
        assert runtime._error_state["last_error"] is not None


class TestAgentRuntimeExternalAPI:
    """测试 AgentRuntime 外部 API（RunResult, run_stream, destroy 等）。"""

    async def test_run_returns_run_result(self) -> None:
        """run() 返回 RunResult 实例。"""
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "你好"}

        runtime.set_llm_executor(mock_llm)
        result = await runtime.run("你好")

        assert isinstance(result, RunResult)
        assert result.content == "你好"
        assert result.session_id == runtime.session_id
        assert result.messages is not None
        assert result.token_used >= 0

    async def test_run_result_on_error(self) -> None:
        """run() 出错时返回包含错误信息的 RunResult。"""
        runtime = AgentRuntime(system_prompt="助手")

        async def failing_llm(ctx):
            raise RuntimeError("出错了")

        runtime.set_llm_executor(failing_llm)
        result = await runtime.run("test")

        assert isinstance(result, RunResult)
        assert "出错了" in result.content
        assert result.status == "error"

    async def test_destroy(self) -> None:
        """destroy() 清空状态并触发 session_end。"""
        runtime = AgentRuntime(system_prompt="助手")
        ended: list[str] = []

        @runtime.on(HookPoint.SESSION_END)
        async def on_end(event, ctx):
            ended.append(event.get("status", ""))

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        runtime.set_llm_executor(mock_llm)
        await runtime.run("hi")
        await runtime.destroy()

        assert runtime.status == "ended"
        assert len(runtime._messages) == 0
        assert len(ended) >= 1
        assert "destroyed" in ended

    async def test_get_session_state(self) -> None:
        """get_session_state() 返回正确的快照。"""
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        runtime.set_llm_executor(mock_llm)
        await runtime.run("hi")

        snapshot = runtime.get_session_state()
        assert isinstance(snapshot, SessionSnapshot)
        assert snapshot.session_id == runtime.session_id
        assert snapshot.message_count >= 2  # user + assistant
        assert snapshot.step_count >= 1

    async def test_run_stream_yields_events(self) -> None:
        """run_stream() 产出 StreamEvent 序列。"""
        runtime = AgentRuntime(system_prompt="助手")

        async def mock_llm(ctx):
            return {"role": "assistant", "content": "你好"}

        runtime.set_llm_executor(mock_llm)

        events: list[StreamEvent] = []
        async for event in runtime.run_stream("你好"):
            events.append(event)

        assert len(events) >= 1
        assert events[-1].type == "done"
        assert events[-1].metadata is not None
        assert "result" in events[-1].metadata

    async def test_run_stream_error(self) -> None:
        """run_stream() 出错时产出 error + done 事件。"""
        runtime = AgentRuntime(system_prompt="助手")

        async def failing_llm(ctx):
            raise RuntimeError("stream error")

        runtime.set_llm_executor(failing_llm)

        events: list[StreamEvent] = []
        async for event in runtime.run_stream("test"):
            events.append(event)

        types = [e.type for e in events]
        assert "error" in types
        assert "done" in types
        assert events[-1].type == "done"
