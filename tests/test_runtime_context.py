"""
测试 RuntimeContext：只读快照、受限写方法。
"""

from __future__ import annotations

import pytest

from src.runtime._types import BudgetSnapshot
from src.runtime.context._context import RuntimeContext
from src.runtime.context._payload import ContextPayload


class TestRuntimeContext:
    """测试 RuntimeContext 核心功能。"""

    def test_default_values(self) -> None:
        ctx = RuntimeContext()
        assert ctx.session_id == ""
        assert ctx.agent_id == ""
        assert ctx.step_index == 0
        assert ctx.messages == ()
        assert ctx.plan is None
        assert isinstance(ctx.budget, BudgetSnapshot)
        assert ctx.services == {}

    def test_custom_values(self) -> None:
        ctx = RuntimeContext(
            session_id="sess_abc",
            agent_id="agent_xyz",
            step_index=3,
            messages=({"role": "user", "content": "hi"},),
            plan={"steps": ["llm", "tool"]},
            budget=BudgetSnapshot(token_used=50, token_limit=1000),
            services={"memory": object()},
        )
        assert ctx.session_id == "sess_abc"
        assert ctx.agent_id == "agent_xyz"
        assert ctx.step_index == 3
        assert len(ctx.messages) == 1
        assert ctx.plan == {"steps": ["llm", "tool"]}
        assert ctx.budget.token_used == 50
        assert "memory" in ctx.services

    def test_frozen_dataclass(self) -> None:
        """RuntimeContext 应为 frozen（不可变）。"""
        ctx = RuntimeContext(session_id="sess_abc")
        with pytest.raises(AttributeError):
            ctx.session_id = "new_value"  # type: ignore[misc]

    def test_set_plan_without_callback(self) -> None:
        ctx = RuntimeContext()
        with pytest.raises(RuntimeError, match="set_plan 未在 Runtime 中初始化"):
            ctx.set_plan({"steps": ["llm"]})

    def test_deduct_budget_without_callback(self) -> None:
        ctx = RuntimeContext()
        err_msg = "deduct_budget 未在 Runtime 中初始化"
        with pytest.raises(RuntimeError, match=err_msg):
            ctx.deduct_budget(100)

    def test_update_context_payload_without_callback(self) -> None:
        ctx = RuntimeContext()
        err_msg = "update_context_payload 未在 Runtime 中初始化"
        with pytest.raises(RuntimeError, match=err_msg):
            ctx.update_context_payload(lambda p: p)

    def test_set_plan_with_callback(self) -> None:
        results: list[dict] = []

        def callback(plan: dict) -> None:
            results.append(plan)

        ctx = RuntimeContext(_set_plan_callback=callback)
        ctx.set_plan({"steps": ["llm"]})
        assert len(results) == 1
        assert results[0] == {"steps": ["llm"]}

    def test_deduct_budget_with_callback(self) -> None:
        deducted: list[int] = []

        def callback(tokens: int) -> None:
            deducted.append(tokens)

        ctx = RuntimeContext(_deduct_budget_callback=callback)
        ctx.deduct_budget(50)
        assert deducted == [50]

    def test_update_context_payload_with_callback(self) -> None:
        updated: list[ContextPayload] = []

        def callback(updater):
            payload = ContextPayload(system_prompt="original")
            result = updater(payload)
            updated.append(result)

        ctx = RuntimeContext(_update_context_payload_callback=callback)
        ctx.update_context_payload(
            lambda p: ContextPayload(system_prompt=p.system_prompt + " + extra")
        )
        assert len(updated) == 1
        assert updated[0].system_prompt == "original + extra"
