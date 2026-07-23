"""
测试 _types 模块：枚举、Protocol、数据类。
"""

from __future__ import annotations

from src.runtime._types import (
    AllowAction,
    BlockAction,
    BudgetSnapshot,
    HandlerInfo,
    HookPoint,
    Interceptor,
    Observer,
    PauseAction,
    PrimitiveType,
    Transformer,
)


class TestPrimitiveType:
    """测试 PrimitiveType 枚举。"""

    def test_values(self) -> None:
        assert PrimitiveType.OBSERVER.value == "observer"
        assert PrimitiveType.TRANSFORM.value == "transform"
        assert PrimitiveType.INTERCEPT.value == "intercept"
        assert PrimitiveType.ROUTER.value == "router"
        assert PrimitiveType.EXECUTE.value == "execute"

    def test_members_count(self) -> None:
        assert len(PrimitiveType) == 5


class TestHookPoint:
    """测试 HookPoint 枚举。"""

    def test_values(self) -> None:
        assert HookPoint.SESSION_START.value == "session_start"
        assert HookPoint.SESSION_END.value == "session_end"
        assert HookPoint.SESSION_RESUME.value == "session_resume"
        assert HookPoint.BEFORE_STEP.value == "before_step"
        assert HookPoint.AFTER_STEP.value == "after_step"
        assert HookPoint.BEFORE_LLM.value == "before_llm"
        assert HookPoint.AFTER_LLM.value == "after_llm"
        assert HookPoint.BEFORE_TOOL.value == "before_tool"
        assert HookPoint.AFTER_TOOL.value == "after_tool"
        assert HookPoint.ON_ERROR.value == "on_error"
        assert HookPoint.ON_STREAM_CHUNK.value == "on_stream_chunk"

    def test_members_count(self) -> None:
        assert len(HookPoint) == 12


class TestInterceptActions:
    """测试 Intercept 结果类型。"""

    def test_allow_action_default(self) -> None:
        action = AllowAction()
        assert action.modified is None

    def test_allow_action_with_modified(self) -> None:
        action = AllowAction(modified={"key": "value"})
        assert action.modified == {"key": "value"}

    def test_block_action_default(self) -> None:
        action = BlockAction()
        assert action.reason == ""

    def test_block_action_with_reason(self) -> None:
        action = BlockAction(reason="blocked by guardrail")
        assert action.reason == "blocked by guardrail"

    def test_pause_action_default(self) -> None:
        action = PauseAction()
        assert action.approval_id == ""
        assert action.context == {}

    def test_pause_action_with_values(self) -> None:
        action = PauseAction(approval_id="abc", context={"tool": "transfer"})
        assert action.approval_id == "abc"
        assert action.context == {"tool": "transfer"}


class TestBudgetSnapshot:
    """测试 BudgetSnapshot。"""

    def test_default_values(self) -> None:
        budget = BudgetSnapshot()
        assert budget.token_used == 0
        assert budget.token_limit == 0
        assert budget.step_count == 0
        assert budget.step_limit == 0
        assert budget.cost_in_cents == 0

    def test_custom_values(self) -> None:
        budget = BudgetSnapshot(
            token_used=100,
            token_limit=1000,
            step_count=5,
            step_limit=50,
            cost_in_cents=10,
        )
        assert budget.token_used == 100
        assert budget.token_limit == 1000
        assert budget.step_count == 5
        assert budget.step_limit == 50
        assert budget.cost_in_cents == 10


class TestHandlerInfo:
    """测试 HandlerInfo。"""

    def test_default_values(self) -> None:
        async def dummy_handler(event, ctx): ...

        info = HandlerInfo(
            handler_id="test_id",
            point=HookPoint.BEFORE_LLM,
            primitive=PrimitiveType.OBSERVER,
            handler=dummy_handler,
        )
        assert info.handler_id == "test_id"
        assert info.point == HookPoint.BEFORE_LLM
        assert info.primitive == PrimitiveType.OBSERVER
        assert info.handler is dummy_handler
        assert info.priority == 0
        assert info.name == ""

    def test_custom_values(self) -> None:
        async def dummy_handler(event, ctx): ...

        info = HandlerInfo(
            handler_id="test_id",
            point=HookPoint.AFTER_TOOL,
            primitive=PrimitiveType.INTERCEPT,
            handler=dummy_handler,
            priority=10,
            name="my_handler",
        )
        assert info.priority == 10
        assert info.name == "my_handler"


class TestProtocols:
    """测试原语 Protocol 的可调用性。"""

    async def test_observer_protocol(self) -> None:
        async def my_observer(event, ctx):
            pass

        observer: Observer = my_observer
        await observer({"type": "test"}, None)

    async def test_transformer_protocol(self) -> None:
        async def my_transformer(data, ctx):
            return data.upper()

        transformer: Transformer[str] = my_transformer
        result = await transformer("hello", None)
        assert result == "HELLO"

    async def test_interceptor_protocol(self) -> None:
        async def my_interceptor(data, ctx):
            return AllowAction()

        interceptor: Interceptor = my_interceptor
        result = await interceptor("data", None)
        assert isinstance(result, AllowAction)
