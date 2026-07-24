"""
测试 tools 包：ToolSpec、ToolRegistry、ToolDispatcher 和 Runtime 集成。
"""

from __future__ import annotations

import pytest

from src.runtime._builder import RuntimeBuilder
from src.runtime._runtime import AgentRuntime
from src.runtime._types import HookPoint
from src.tools import ToolDispatcher, ToolRegistry
from src.tools._spec import ToolSpec

# ============ 辅助函数 ============


async def _calc_handler(a: int, b: int, operation: str = "add") -> int:
    """测试用工具 handler：简单计算器。"""
    if operation == "add":
        return a + b
    if operation == "multiply":
        return a * b
    msg = f"未知操作: {operation}"
    raise ValueError(msg)


async def _greet_handler(user_name: str, greeting: str = "Hello") -> str:
    """测试用工具 handler：问候。"""
    return f"{greeting}, {user_name}!"


def _make_calc_spec() -> ToolSpec:
    """创建计算器 ToolSpec。"""
    return ToolSpec(
        name="calculator",
        description="简单计算器，支持加法和乘法",
        parameters={
            "a": {"type": "integer", "description": "第一个数字"},
            "b": {"type": "integer", "description": "第二个数字"},
            "operation": {
                "type": "string",
                "description": "操作类型",
                "enum": ["add", "multiply"],
            },
        },
        handler=_calc_handler,
        required=["a", "b"],
    )


def _make_greet_spec() -> ToolSpec:
    """创建问候 ToolSpec。"""
    return ToolSpec(
        name="greet",
        description="问候用户",
        parameters={
            "user_name": {"type": "string", "description": "用户名称"},
            "greeting": {"type": "string", "description": "问候语"},
        },
        handler=_greet_handler,
        required=["user_name"],
    )


# ============ Test ToolSpec ============


class TestToolSpec:
    """测试 ToolSpec 数据类。"""

    def test_create(self) -> None:
        spec = _make_calc_spec()
        assert spec.name == "calculator"
        assert "简单计算器" in spec.description
        assert "a" in spec.parameters
        assert spec.required == ["a", "b"]
        assert spec.timeout == 30.0

    def test_default_timeout(self) -> None:
        spec = _make_greet_spec()
        assert spec.timeout == 30.0

    def test_custom_timeout(self) -> None:
        spec = _make_calc_spec()
        spec.timeout = 60.0
        assert spec.timeout == 60.0

    def test_to_openai_schema(self) -> None:
        spec = _make_calc_spec()
        schema = spec.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "calculator"
        assert schema["function"]["parameters"]["type"] == "object"
        assert "a" in schema["function"]["parameters"]["properties"]
        assert schema["function"]["parameters"]["required"] == ["a", "b"]


class TestToolRegistry:
    """测试 ToolRegistry 注册、描述、执行。"""

    def test_empty_registry(self) -> None:
        registry = ToolRegistry()
        assert len(registry) == 0
        assert registry.describe() == []

    def test_register_tool(self) -> None:
        registry = ToolRegistry()
        spec = _make_calc_spec()
        registry.register(spec)
        assert len(registry) == 1
        assert "calculator" in registry

    def test_register_non_toolspec_raises(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(TypeError, match="期望 ToolSpec"):
            registry.register("not_a_tool")  # type: ignore[arg-type]

    def test_register_override(self) -> None:
        """同名工具后注册覆盖先注册。"""
        registry = ToolRegistry()
        spec1 = _make_calc_spec()
        spec2 = _make_calc_spec()
        spec2.description = "覆盖版计算器"
        registry.register(spec1)
        registry.register(spec2)
        assert len(registry) == 1
        assert registry.get("calculator").description == "覆盖版计算器"

    def test_describe(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        registry.register(_make_greet_spec())
        tools = registry.describe()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"calculator", "greet"}

    def test_list_specs_alias(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        specs = registry.list_specs()
        assert len(specs) == 1
        assert specs[0].name == "calculator"

    def test_get_existing(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        spec = registry.get("calculator")
        assert spec is not None
        assert spec.name == "calculator"

    def test_get_nonexistent(self) -> None:
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_unregister_existing(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        registry.unregister("calculator")
        assert len(registry) == 0

    def test_unregister_nonexistent_raises(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(KeyError, match="未注册"):
            registry.unregister("nonexistent")

    async def test_execute(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        result = await registry.execute("calculator", a=2, b=3)
        assert result == 5

    async def test_execute_with_kwargs(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        result = await registry.execute("calculator", a=3, b=4, operation="multiply")
        assert result == 12

    async def test_execute_nonexistent_raises(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(KeyError, match="未注册"):
            await registry.execute("nonexistent")

    async def test_execute_greet(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_greet_spec())
        result = await registry.execute("greet", user_name="World")
        assert result == "Hello, World!"

    def test_contains(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        assert "calculator" in registry
        assert "nonexistent" not in registry

    def test_len(self) -> None:
        registry = ToolRegistry()
        assert len(registry) == 0
        registry.register(_make_calc_spec())
        assert len(registry) == 1
        registry.register(_make_greet_spec())
        assert len(registry) == 2


class TestToolDispatcher:
    """测试 ToolDispatcher 统一调度。"""

    def test_all_tools_empty(self) -> None:
        registry = ToolRegistry()
        dispatcher = ToolDispatcher(tool_registry=registry)
        assert dispatcher.all_tools() == []

    def test_all_tools(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        registry.register(_make_greet_spec())
        dispatcher = ToolDispatcher(tool_registry=registry)
        tools = dispatcher.all_tools()
        assert len(tools) == 2

    def test_all_tools_returns_tool_specs(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        dispatcher = ToolDispatcher(tool_registry=registry)
        tools = dispatcher.all_tools()
        assert all(isinstance(t, ToolSpec) for t in tools)

    async def test_dispatch_tool(self) -> None:
        """真实 OpenAI tool_call 格式（function.name + function.arguments JSON）。"""
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        dispatcher = ToolDispatcher(tool_registry=registry)

        from src.runtime.context._context import RuntimeContext

        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "计算 2+3"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "calculator",
                                "arguments": '{"a": 2, "b": 3}',
                            },
                        }
                    ],
                },
            ),
        )
        result = await dispatcher.dispatch(ctx)
        assert result is not None
        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_1"
        assert result["content"] == "5"

    async def test_dispatch_tool_flat_format(self) -> None:
        """兼容直接格式（name/arguments 在顶层，非 OpenAI 标准）。"""
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        dispatcher = ToolDispatcher(tool_registry=registry)

        from src.runtime.context._context import RuntimeContext

        ctx = RuntimeContext(
            messages=(
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "call_2", "name": "calculator", "arguments": {"a": 10, "b": 20}},
                ]},
            ),
        )
        result = await dispatcher.dispatch(ctx)
        assert result is not None
        assert result["content"] == "30"

    async def test_dispatch_no_tool_call(self) -> None:
        registry = ToolRegistry()
        dispatcher = ToolDispatcher(tool_registry=registry)
        from src.runtime.context._context import RuntimeContext

        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "你好"},
            ),
        )
        result = await dispatcher.dispatch(ctx)
        assert result is None

    async def test_dispatch_mcp_not_found(self) -> None:
        """MCP 前缀路由：工具未连接时返回友好错误。"""
        registry = ToolRegistry()
        dispatcher = ToolDispatcher(tool_registry=registry)
        from src.runtime.context._context import RuntimeContext

        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "读文件"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_mcp",
                            "type": "function",
                            "function": {
                                "name": "mcp_fs_read_file",
                                "arguments": '{"path": "/tmp/test"}',
                            },
                        }
                    ],
                },
            ),
        )
        result = await dispatcher.dispatch(ctx)
        assert result is not None
        assert "未找到" in result["content"] or "错误" in result["content"]


class TestToolRuntimeIntegration:
    """测试 Tool 与 RuntimeBuilder/AgentRuntime 的集成。"""

    async def test_runtime_with_tools(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        registry.register(_make_greet_spec())

        runtime = (
            RuntimeBuilder()
            .system_prompt("你是一个助手")
            .tool_registry(registry)
            .build()
        )

        # 验证 tool_executor 已被 Builder 设置为 dispatcher.dispatch
        assert runtime._tool_executor is not None
        # 验证 before_llm Transform 已注册
        handlers = runtime._hooks.list(HookPoint.BEFORE_LLM)
        assert any(h.name == "_tools_schema_refresh" for h in handlers)

    async def test_runtime_with_tools_injects_schema(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())
        registry.register(_make_greet_spec())

        runtime = (
            RuntimeBuilder()
            .system_prompt("你是一个助手")
            .tool_registry(registry)
            .build()
        )

        # 执行 before_llm Transform 验证 tools_schema 注入
        from src.runtime._types import BudgetSnapshot
        from src.runtime.context._context import RuntimeContext
        from src.runtime.context._payload import ContextPayload

        ctx = RuntimeContext(
            session_id="test",
            messages=(),
            budget=BudgetSnapshot(),
            services=dict(runtime._services),
        )
        payload = ContextPayload(system_prompt="你是一个助手")

        # 手动触发 tools_schema_refresh Transform
        for h in runtime._hooks.list(HookPoint.BEFORE_LLM):
            if h.name == "_tools_schema_refresh":
                await h.handler(payload, ctx)

        # 验证 services 中有了 tools_schema
        schema = ctx.services.get("tools_schema")
        assert schema is not None
        assert len(schema) == 2
        assert schema[0]["type"] == "function"
        assert schema[0]["function"]["name"] in ("calculator", "greet")

    async def test_runtime_without_tools(self) -> None:
        """不传入 tools 时，没有 tools_schema Transform。"""
        runtime = AgentRuntime(system_prompt="你是一个助手")
        handlers = runtime._hooks.list(HookPoint.BEFORE_LLM)
        assert not any(h.name == "_tools_schema_refresh" for h in handlers)

    async def test_runtime_tool_executor_direct(self) -> None:
        """直接传入 tool_executor，不经过 Builder。"""
        async def fallback_executor(ctx):
            return {"role": "tool", "content": "fallback"}

        runtime = AgentRuntime(
            system_prompt="你是一个助手",
            tool_executor=fallback_executor,
        )

        assert runtime._tool_executor is fallback_executor

    async def test_builder_with_tool_executor_and_registry(self) -> None:
        """Builder 同时设置 tool_registry 和自定义 tool_executor 时，registry 优先。"""
        registry = ToolRegistry()
        registry.register(_make_calc_spec())

        async def fallback(ctx):
            return {"role": "tool", "content": "fallback"}

        runtime = (
            RuntimeBuilder()
            .system_prompt("你是一个助手")
            .tool(fallback)
            .tool_registry(registry)
            .build()
        )

        # tool_executor 已被 dispatcher.dispatch 覆盖（registry 优先）
        assert runtime._tool_executor is not fallback
        assert runtime._tool_executor is not None
        # 验证 before_llm Transform 已注入 tools_schema
        handlers = runtime._hooks.list(HookPoint.BEFORE_LLM)
        assert any(h.name == "_tools_schema_refresh" for h in handlers)


class TestToolRuntimeBuilderIntegration:
    """测试 RuntimeBuilder 的 tool_registry() 方法。"""

    async def test_builder_with_tool_registry(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_calc_spec())

        runtime = (
            RuntimeBuilder()
            .system_prompt("你是一个助手")
            .tool_registry(registry)
            .build()
        )

        # tool_executor 被设为 dispatcher.dispatch
        assert runtime._tool_executor is not None
        # 验证 before_llm Transform 已注册
        handlers = runtime._hooks.list(HookPoint.BEFORE_LLM)
        assert any(h.name == "_tools_schema_refresh" for h in handlers)
