"""
测试 PluggableComponent 和 Plugin。
"""

from __future__ import annotations

from src.runtime._types import HookPoint, PrimitiveType
from src.runtime.plugins._plugin import PluggableComponent, Plugin


class TestPluggableComponent:
    """测试 PluggableComponent 基本协议。"""

    async def test_name_property(self) -> None:
        class MyComponent(PluggableComponent):
            @property
            def name(self) -> str:
                return "my_component"

        comp = MyComponent()
        assert comp.name == "my_component"

    async def test_on_attach_default(self) -> None:
        class MyComponent(PluggableComponent):
            @property
            def name(self) -> str:
                return "test"

        comp = MyComponent()
        # 默认 on_attach 不应抛出异常
        await comp.on_attach(None)  # type: ignore[arg-type]

    async def test_on_detach_default(self) -> None:
        class MyComponent(PluggableComponent):
            @property
            def name(self) -> str:
                return "test"

        comp = MyComponent()
        # 默认 on_detach 不应抛出异常
        await comp.on_detach()


class TestPlugin:
    """测试 Plugin 基类。"""

    async def test_declare_hooks_default(self) -> None:
        class EmptyPlugin(Plugin):
            @property
            def name(self) -> str:
                return "empty"

        plugin = EmptyPlugin()
        hooks = plugin._declare_hooks()
        assert hooks == []

    async def test_declare_hooks_custom(self) -> None:
        class AuditPlugin(Plugin):
            @property
            def name(self) -> str:
                return "audit"

            def _declare_hooks(self):
                return [
                    (
                        HookPoint.AFTER_LLM,
                        PrimitiveType.OBSERVER,
                        self._on_llm,
                    ),
                    (
                        HookPoint.AFTER_TOOL,
                        PrimitiveType.OBSERVER,
                        self._on_tool,
                    ),
                ]

            async def _on_llm(self, event, ctx):
                pass

            async def _on_tool(self, event, ctx):
                pass

        plugin = AuditPlugin()
        hooks = plugin._declare_hooks()
        assert len(hooks) == 2
        assert hooks[0][0] == HookPoint.AFTER_LLM
        assert hooks[0][1] == PrimitiveType.OBSERVER
        assert hooks[1][0] == HookPoint.AFTER_TOOL

    async def test_on_attach_registers_hooks(self) -> None:
        """验证 on_attach 会将 _declare_hooks 中的 hooks 注册到 runtime。"""
        registered: list[tuple] = []

        class MockRuntime:
            def register(self, point, handler, *, primitive, name):
                registered.append((point, primitive, name))
                return "handler_id"

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
        runtime = MockRuntime()
        await plugin.on_attach(runtime)  # type: ignore[arg-type]

        assert len(registered) == 1
        assert registered[0][0] == HookPoint.AFTER_LLM
        assert registered[0][1] == PrimitiveType.OBSERVER
        assert "test_plugin._log" in registered[0][2]
