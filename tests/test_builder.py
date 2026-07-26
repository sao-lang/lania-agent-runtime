"""
测试 RuntimeBuilder、AgentRuntime.builder()、from_config()。
"""

from __future__ import annotations

import os
import tempfile

import pytest

from src.runtime._builder import RuntimeBuilder
from src.runtime._runtime import AgentRuntime
from src.runtime._types import HookPoint, PrimitiveType
from src.runtime.config._runtime_config import RuntimeConfig
from src.runtime.plugins._plugin import Plugin


class TestRuntimeBuilder:
    """测试 RuntimeBuilder 链式 API。"""

    async def test_basic_build(self) -> None:
        runtime = RuntimeBuilder().system_prompt("你是助手").build()
        assert runtime is not None
        assert isinstance(runtime, AgentRuntime)

    async def test_build_with_llm_executor(self) -> None:
        async def my_llm(ctx):
            return {"role": "assistant", "content": "ok"}

        runtime = RuntimeBuilder().system_prompt("助手").llm(executor=my_llm).build()
        assert runtime._llm_executor is my_llm

    async def test_build_with_tool(self) -> None:
        async def my_tool(ctx):
            return {"role": "tool", "content": "done"}

        runtime = RuntimeBuilder().system_prompt("助手").tool(my_tool).build()
        # 传入的自定义 tool_executor 保持不变
        assert runtime._tool_executor is my_tool

    async def test_build_with_agent_id(self) -> None:
        runtime = RuntimeBuilder().system_prompt("助手").agent_id("my_bot").build()
        assert runtime.agent_id == "my_bot"

    async def test_build_with_plugin(self) -> None:
        class TestPlugin(Plugin):
            @property
            def name(self) -> str:
                return "test_plugin"

            def _declare_hooks(self):
                return [
                    (HookPoint.AFTER_LLM, PrimitiveType.OBSERVER, self._log),
                ]

            async def _log(self, event, ctx):
                pass

        plugin = TestPlugin()
        runtime = RuntimeBuilder().system_prompt("助手").plugin(plugin).build()
        # 插件需要异步注册
        await runtime.use(plugin)
        handlers = runtime._hooks.list(HookPoint.AFTER_LLM)
        assert len(handlers) >= 1

    async def test_from_config_full(self) -> None:
        """from_config 完整路径（含 memory/services）。"""
        config = RuntimeConfig(
            system_prompt="助手",
            llm={"model": "gpt-4o"},
            loop={"strategy": "react"},
            memory={"backend": "sqlite", "path": "./mem.db"},
            services={"weather_key": "abc"},
        )
        runtime = RuntimeBuilder().from_config(config).build()
        assert runtime is not None
        assert runtime._services.get("weather_key") == "abc"
        assert runtime._services.get("memory_config", {}).get("backend") == "sqlite"

    async def test_from_yaml(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("system_prompt: 你是助手\n")
            yaml_path = f.name

        try:
            runtime = AgentRuntime.from_config(yaml_path)
            assert isinstance(runtime, AgentRuntime)
        finally:
            os.unlink(yaml_path)

    async def test_services_config(self) -> None:
        runtime = (
            RuntimeBuilder().system_prompt("助手").services({"weather_api_key": "test"}).build()
        )
        assert runtime._services.get("weather_api_key") == "test"

    async def test_memory_service(self) -> None:
        from src.memory._backends._sqlite import SQLitePersistence
        from src.memory._service import MemoryService

        persistence = SQLitePersistence(":memory:")
        memory = MemoryService(persistence=persistence)
        runtime = RuntimeBuilder().system_prompt("助手").memory(memory).build()
        # 验证 Builder 创建了 ContextManager 并注册了 hook
        assert "context_manager" in runtime._services
        handlers = runtime._hooks.list()
        names = [h.name for h in handlers]
        assert "_context_assembler" in names
        assert "_memory_commit" in names

    async def test_context_with_memory(self) -> None:
        """.context() 配合 .memory() 时，ContextConfig 传递给 ContextManager。"""
        from src.context import ContextConfig
        from src.memory._backends._sqlite import SQLitePersistence
        from src.memory._service import MemoryService

        mem = MemoryService(persistence=SQLitePersistence(":memory:"))
        runtime = (
            RuntimeBuilder()
            .system_prompt("助手")
            .memory(mem)
            .context(config=ContextConfig(compression_level=4, preserve_turns=5))
            .build()
        )
        cfg = runtime._services["context_manager"]._config
        assert cfg.compression_level == 4
        assert cfg.preserve_turns == 5
        await mem.close()

    async def test_context_without_memory_silent(self) -> None:
        """.context() 单独使用时不崩溃，配置被静默忽略（带 warning）。"""
        from src.context import ContextConfig

        runtime = (
            RuntimeBuilder()
            .system_prompt("助手")
            .context(config=ContextConfig(compression_level=4))
            .build()
        )
        # 没有 memory，就没有 context_manager
        assert "context_manager" not in runtime._services

    async def test_loop_config_by_name(self) -> None:
        """通过名称字符串配置 loop 策略。"""
        runtime = (
            RuntimeBuilder().system_prompt("助手").loop("plan_and_execute").build()
        )
        from src.runtime.loops._plan_execute import PlanExecuteLoop
        assert isinstance(runtime._loop, PlanExecuteLoop)

    async def test_loop_config_with_instance(self) -> None:
        """直接注入 LoopStrategy 实例。"""
        from unittest.mock import MagicMock
        from src.runtime.loops import ReActLoop

        hooks = MagicMock()
        step_runner = MagicMock()
        controller = MagicMock()
        my_loop = ReActLoop(
            hooks=hooks, step_runner=step_runner, controller=controller, max_iterations=20,
        )

        runtime = (
            RuntimeBuilder().system_prompt("助手").loop(my_loop).build()
        )
        assert runtime._loop is my_loop
        assert runtime._loop._max_iterations == 20

    async def test_loop_default(self) -> None:
        """不传 loop 参数时默认使用 ReActLoop。"""
        runtime = RuntimeBuilder().system_prompt("助手").build()
        from src.runtime.loops._react import ReActLoop
        assert isinstance(runtime._loop, ReActLoop)

    async def test_hooks_registry(self) -> None:
        from src.runtime.hooks._registry import HookRegistry

        registry = HookRegistry()
        runtime = RuntimeBuilder().system_prompt("助手").hooks(registry).build()
        assert runtime._hooks is registry

    async def test_llm_with_config(self) -> None:
        runtime = (
            RuntimeBuilder()
            .system_prompt("助手")
            .llm(model="gpt-4o", api_key="sk-test", max_tokens=4096)
            .build()
        )
        config = runtime._services.get("llm_config", {})
        assert config.get("model") == "gpt-4o"
        assert config.get("api_key") == "sk-test"
        assert config.get("max_tokens") == 4096


class TestAgentRuntimeFactory:
    """测试 AgentRuntime 工厂方法。"""

    async def test_builder_classmethod(self) -> None:
        builder = AgentRuntime.builder()
        assert isinstance(builder, RuntimeBuilder)

    async def test_from_config_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            AgentRuntime.from_config("nonexistent.yaml")
