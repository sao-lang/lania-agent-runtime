"""
测试 HookRegistry：注册、移除、替换、执行管线。
"""

from __future__ import annotations

from src.runtime._types import (
    AllowAction,
    BlockAction,
    HookPoint,
    PauseAction,
    PrimitiveType,
)
from src.runtime.hooks._registry import HookRegistry


class TestHookRegistry:
    """测试 HookRegistry 核心功能。"""

    async def test_register_and_list(self) -> None:
        registry = HookRegistry()

        async def handler(event, ctx):
            pass

        handler_id = registry.register(
            HookPoint.BEFORE_LLM, handler, primitive=PrimitiveType.OBSERVER, name="test"
        )
        assert handler_id is not None
        assert handler_id.startswith("before_llm.test")

        handlers = registry.list()
        assert len(handlers) == 1
        assert handlers[0].handler_id == handler_id

        point_handlers = registry.list(HookPoint.BEFORE_LLM)
        assert len(point_handlers) == 1

        empty_handlers = registry.list(HookPoint.AFTER_LLM)
        assert len(empty_handlers) == 0

    async def test_remove(self) -> None:
        registry = HookRegistry()

        async def handler(event, ctx):
            pass

        handler_id = registry.register(
            HookPoint.BEFORE_LLM, handler, primitive=PrimitiveType.OBSERVER
        )
        assert len(registry.list()) == 1

        registry.remove(handler_id)
        assert len(registry.list()) == 0

    async def test_remove_nonexistent(self) -> None:
        registry = HookRegistry()
        try:
            registry.remove("nonexistent")
            assert False, "应该抛出 KeyError"
        except KeyError:
            pass

    async def test_replace(self) -> None:
        registry = HookRegistry()

        async def old_handler(event, ctx):
            return "old"

        async def new_handler(event, ctx):
            return "new"

        handler_id = registry.register(
            HookPoint.BEFORE_LLM, old_handler, primitive=PrimitiveType.OBSERVER
        )

        registry.replace(handler_id, new_handler)

        info = registry.list()[0]
        assert info.handler is new_handler

    async def test_replace_nonexistent(self) -> None:
        registry = HookRegistry()
        try:

            async def handler(event, ctx):
                pass

            registry.replace("nonexistent", handler)
            assert False, "应该抛出 KeyError"
        except KeyError:
            pass

    async def test_run_transformers(self) -> None:
        registry = HookRegistry()

        async def upper_transformer(data, ctx):
            return data.upper()

        async def exclaim_transformer(data, ctx):
            return data + "!"

        registry.register(
            HookPoint.BEFORE_LLM,
            upper_transformer,
            primitive=PrimitiveType.TRANSFORM,
            priority=1,
        )
        registry.register(
            HookPoint.BEFORE_LLM,
            exclaim_transformer,
            primitive=PrimitiveType.TRANSFORM,
            priority=2,
        )

        result = await registry.run_transformers(HookPoint.BEFORE_LLM, "hello", None)
        assert result == "HELLO!"

    async def test_run_transformers_empty(self) -> None:
        registry = HookRegistry()
        result = await registry.run_transformers(HookPoint.BEFORE_LLM, "hello", None)
        assert result == "hello"

    async def test_run_interceptors_allow(self) -> None:
        registry = HookRegistry()

        async def always_allow(data, ctx):
            return AllowAction()

        registry.register(
            HookPoint.BEFORE_LLM,
            always_allow,
            primitive=PrimitiveType.INTERCEPT,
        )

        result = await registry.run_interceptors(HookPoint.BEFORE_LLM, "data", None)
        assert isinstance(result, AllowAction)
        # 即使没有修改，也会返回原始 data
        assert result.modified == "data"

    async def test_run_interceptors_block(self) -> None:
        registry = HookRegistry()

        async def always_block(data, ctx):
            return BlockAction(reason="blocked")

        registry.register(
            HookPoint.BEFORE_LLM,
            always_block,
            primitive=PrimitiveType.INTERCEPT,
        )

        result = await registry.run_interceptors(HookPoint.BEFORE_LLM, "data", None)
        assert isinstance(result, BlockAction)
        assert result.reason == "blocked"

    async def test_run_interceptors_pause(self) -> None:
        registry = HookRegistry()

        async def always_pause(data, ctx):
            return PauseAction(approval_id="need_approval")

        registry.register(
            HookPoint.BEFORE_LLM,
            always_pause,
            primitive=PrimitiveType.INTERCEPT,
        )

        result = await registry.run_interceptors(HookPoint.BEFORE_LLM, "data", None)
        assert isinstance(result, PauseAction)
        assert result.approval_id == "need_approval"

    async def test_run_interceptors_short_circuit(self) -> None:
        """第一个 block/pause 应短路后续 interceptor。"""
        registry = HookRegistry()
        calls: list[str] = []

        async def first_block(data, ctx):
            calls.append("first")
            return BlockAction(reason="first blocked")

        async def second_never_called(data, ctx):
            calls.append("second")
            return AllowAction()

        registry.register(
            HookPoint.BEFORE_LLM,
            first_block,
            primitive=PrimitiveType.INTERCEPT,
            priority=1,
        )
        registry.register(
            HookPoint.BEFORE_LLM,
            second_never_called,
            primitive=PrimitiveType.INTERCEPT,
            priority=2,
        )

        result = await registry.run_interceptors(HookPoint.BEFORE_LLM, "data", None)
        assert isinstance(result, BlockAction)
        assert calls == ["first"]

    async def test_run_interceptors_with_modified(self) -> None:
        """Interceptor 可通过 AllowAction.modified 修改数据传递给下一个。"""
        registry = HookRegistry()
        received_data: list = []

        async def modify_and_allow(data, ctx):
            return AllowAction(modified=data + " modified")

        async def check_data(data, ctx):
            received_data.append(data)
            return AllowAction()

        registry.register(
            HookPoint.BEFORE_LLM,
            modify_and_allow,
            primitive=PrimitiveType.INTERCEPT,
            priority=1,
        )
        registry.register(
            HookPoint.BEFORE_LLM,
            check_data,
            primitive=PrimitiveType.INTERCEPT,
            priority=2,
        )

        result = await registry.run_interceptors(HookPoint.BEFORE_LLM, "original", None)
        assert isinstance(result, AllowAction)
        assert received_data == ["original modified"]

    async def test_run_observers(self) -> None:
        registry = HookRegistry()
        observed: list[str] = []

        async def observer1(event, ctx):
            observed.append("obs1")

        async def observer2(event, ctx):
            observed.append("obs2")

        registry.register(
            HookPoint.AFTER_LLM, observer1, primitive=PrimitiveType.OBSERVER, priority=1
        )
        registry.register(
            HookPoint.AFTER_LLM, observer2, primitive=PrimitiveType.OBSERVER, priority=2
        )

        await registry.run_observers(HookPoint.AFTER_LLM, {"type": "test"}, None)
        assert len(observed) == 2
        assert "obs1" in observed
        assert "obs2" in observed

    async def test_run_observers_empty(self) -> None:
        registry = HookRegistry()
        await registry.run_observers(HookPoint.AFTER_LLM, {}, None)
        # 不应抛出异常

    async def test_priority_order(self) -> None:
        """priority 值越小越先执行。"""
        registry = HookRegistry()
        order: list[int] = []

        async def make_handler(priority: int):
            async def handler(data, ctx):
                order.append(priority)
                return data

            return handler

        registry.register(
            HookPoint.BEFORE_LLM,
            await make_handler(10),
            primitive=PrimitiveType.TRANSFORM,
            priority=10,
        )
        registry.register(
            HookPoint.BEFORE_LLM,
            await make_handler(1),
            primitive=PrimitiveType.TRANSFORM,
            priority=1,
        )
        registry.register(
            HookPoint.BEFORE_LLM,
            await make_handler(5),
            primitive=PrimitiveType.TRANSFORM,
            priority=5,
        )

        await registry.run_transformers(HookPoint.BEFORE_LLM, "data", None)
        assert order == [1, 5, 10]

    async def test_handler_id_format(self) -> None:
        registry = HookRegistry()

        async def handler(event, ctx):
            pass

        handler_id = registry.register(
            HookPoint.SESSION_START, handler, primitive=PrimitiveType.OBSERVER, name="custom_name"
        )
        assert "session_start" in handler_id
        assert "custom_name" in handler_id

    async def test_copy(self) -> None:
        """HookRegistry.copy() 应创建独立副本。"""
        registry = HookRegistry()

        async def handler(event, ctx):
            pass

        registry.register(
            HookPoint.BEFORE_LLM, handler, primitive=PrimitiveType.OBSERVER, name="obs1"
        )
        registry.register(
            HookPoint.AFTER_LLM, handler, primitive=PrimitiveType.TRANSFORM, name="tf1"
        )

        copy_registry = registry.copy()

        # 副本应有相同的 handlers
        assert len(copy_registry.list()) == 2
        assert len(copy_registry.list(HookPoint.BEFORE_LLM)) == 1
        assert len(copy_registry.list(HookPoint.AFTER_LLM)) == 1

        # 修改副本不应影响原 registry
        copy_registry.remove(copy_registry.list()[0].handler_id)
        assert len(copy_registry.list()) == 1
        assert len(registry.list()) == 2
