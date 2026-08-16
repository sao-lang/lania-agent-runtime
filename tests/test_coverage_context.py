"""
Context 层覆盖率补测。

覆盖 TokenManager 预算耗尽分支、BudgetController 动态配额、ContextManager
关闭管线/回退载荷/原始消息提取、Selector 去重键计算，以及包惰性导出。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.context import ContextConfig, ContextManager, Selector
from src.context._budget import BudgetController, TokenManager
from src.context._models import SelectionDecision
from src.memory._types import RecallResult
from src.runtime.context._context import RuntimeContext
from src.runtime.context._payload import ContextPayload


def make_payload() -> ContextPayload:
    """构造带各类字段的 ContextPayload。"""
    return ContextPayload(
        system_prompt="sys",
        memories=["m1", "m2"],
        rag_documents=["doc"],
        injected_context=["ctx1"],
        history=[{"role": "user", "content": "old"}],
        tool_results=["r1", "r2"],
    )


class TestTokenManagerCoverage:
    """TokenManager 未覆盖分支。"""

    def test_apply_budget_all_consumed(self) -> None:
        tm = TokenManager()
        payload = make_payload()
        huge_messages = [{"role": "user", "content": "x" * 5000}] * 5
        result = tm.apply_budget(payload, huge_messages, max_tokens=1024)
        assert result.memories == []
        assert result.rag_documents == []
        assert result.injected_context == []
        assert result.tool_results == []
        assert result.history == []

    def test_trim_field_under_budget(self) -> None:
        tm = TokenManager()
        payload = make_payload()
        result = tm._trim_field(payload, "memories", 10_000)
        assert result.memories == ["m1", "m2"]

    def test_trim_field_pops_from_end(self) -> None:
        tm = TokenManager()
        payload = make_payload()
        result = tm._trim_field(payload, "memories", 1)
        assert result.memories != ["m1", "m2"]
        assert payload._dirty is True


class TestBudgetControllerCoverage:
    """BudgetController 未覆盖分支。"""

    async def test_apply_sets_hints(self) -> None:
        controller = BudgetController()
        payload = make_payload()
        config = ContextConfig(max_context_tokens=10_000)
        result = await controller.apply(payload, [{"role": "user", "content": "hi"}], config)
        assert result.max_tokens == 10_000
        assert result.reserve_for_response >= 512
        assert result.preserve_last_n_history >= config.min_preserve_turns

    async def test_apply_raises_small_reserve(self) -> None:
        controller = BudgetController()
        payload = make_payload()
        config = ContextConfig(max_context_tokens=1_000, reserve_for_response=1)
        result = await controller.apply(payload, [], config)
        assert result.reserve_for_response == 512


class TestContextManagerCoverage:
    """ContextManager 未覆盖分支。"""

    async def test_disabled_uses_fallback(self) -> None:
        memory = AsyncMock()
        manager = ContextManager(memory, config=ContextConfig(enabled=False))
        ctx = RuntimeContext(
            messages=(
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            )
        )
        messages = await manager.assemble(ctx)
        assert messages[0]["content"] == "sys"
        assert {"role": "user", "content": "hi"} in messages

    async def test_fallback_empty_messages(self) -> None:
        manager = ContextManager(AsyncMock(), config=ContextConfig(enabled=False))
        payload = manager._build_fallback_payload(RuntimeContext())
        assert isinstance(payload, ContextPayload)
        assert payload.system_prompt == ""

    async def test_fallback_without_system(self) -> None:
        manager = ContextManager(AsyncMock(), config=ContextConfig(enabled=False))
        payload = manager._build_fallback_payload(
            RuntimeContext(messages=({"role": "user", "content": "hi"},))
        )
        assert payload.system_prompt == ""
        assert payload.history == [{"role": "user", "content": "hi"}]

    async def test_get_raw_messages_beyond_index(self) -> None:
        manager = ContextManager(AsyncMock())
        decision = SelectionDecision(keep_from_index=99)
        raw = manager._get_raw_messages(
            RuntimeContext(messages=({"role": "user", "content": "hi"},)),
            decision,
        )
        assert raw == []

    async def test_assemble_pipeline_with_memory(self) -> None:
        memory = AsyncMock()
        memory.recall_raw = AsyncMock(
            return_value=RecallResult(
                episodic_memories=[],
                entity_profile={},
                concepts=[],
                tone_instruction="",
            )
        )
        manager = ContextManager(memory)
        ctx = RuntimeContext(
            messages=(
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "你好"},
            ),
            session_id="s1",
            services={"user_id": "u1"},
        )
        messages = await manager.assemble(ctx)
        assert messages[0]["content"] == "sys"
        assert any(m.get("content") == "你好" for m in messages)
        memory.recall_raw.assert_awaited_once()


class TestSelectorCoverage:
    """Selector 未覆盖分支。"""

    async def test_dedup_keys_turn_indices(self) -> None:
        selector = Selector()
        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
                {"role": "user", "content": "c"},
            )
        )
        keep = {"from_index": 2}
        dedup = selector._find_dedup_keys(ctx, keep, ContextConfig())
        assert dedup["memory_ids"] == set()
        assert dedup["turn_indices"] == {1}

    async def test_select_with_tool_context(self) -> None:
        selector = Selector()
        ctx = RuntimeContext(
            messages=(
                {"role": "user", "content": "a"},
                {
                    "role": "assistant",
                    "content": "b",
                    "tool_calls": [{"id": "c1"}],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "r"},
            )
        )
        decision = await selector.select(ctx, ContextConfig(preserve_turns=1))
        assert decision.preserve_message_count == 1
        assert decision.keep_from_index == 0


class TestPackageLazyExports:
    """context 包惰性导出。"""

    def test_lazy_imports(self) -> None:
        from src.context import BudgetController, Compressor, TokenManager

        assert ContextManager is not None
        assert Selector is not None
        assert Compressor is not None
        assert BudgetController is not None
        assert TokenManager is not None

    def test_unknown_attribute_raises(self) -> None:
        import src.context as context_pkg

        with pytest.raises(AttributeError):
            context_pkg.NonExistent  # noqa: B018

    def test_context_hooks_lazy_import(self) -> None:
        from src.context.context_hooks import ContextAssemblerHook

        assert ContextAssemblerHook is not None
        with pytest.raises(AttributeError):
            import src.context.context_hooks as hooks_pkg

            hooks_pkg.NonExistent  # noqa: B018
