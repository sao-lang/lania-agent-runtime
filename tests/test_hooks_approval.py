"""
Hook 模块测试——审批、批评、Replan。

覆盖：
  - ApprovalPolicy 各实现
  - HumanApprovalInterceptor
  - SelfCritiqueHook / DualModelCritiqueHook
  - ReplanHook
"""

from __future__ import annotations

import pytest

from src.runtime.hooks._approval_hook import (
    BudgetThresholdPolicy,
    CompoundPolicy,
    HumanApprovalInterceptor,
    RegexContentPolicy,
    ToolNamePolicy,
)


# ============ ApprovalPolicy 测试 ============


class MockContext:
    """模拟 RuntimeContext。"""

    def __init__(self, token_used: int = 0, step_count: int = 0) -> None:
        self.budget = MockBudget(token_used, step_count)


class MockBudget:
    def __init__(self, token_used: int = 0, step_count: int = 0) -> None:
        self.token_used = token_used
        self.step_count = step_count


class TestToolNamePolicy:
    async def test_matches_tool_name(self) -> None:
        policy = ToolNamePolicy(["deploy", "delete_db"])
        ctx = MockContext()
        need, reason = await policy.needs_approval(ctx, "deploy", {})
        assert need is True
        assert "deploy" in reason

    async def test_not_matches(self) -> None:
        policy = ToolNamePolicy(["deploy"])
        ctx = MockContext()
        need, _ = await policy.needs_approval(ctx, "get_weather", {})
        assert need is False

    async def test_empty_list(self) -> None:
        policy = ToolNamePolicy([])
        ctx = MockContext()
        need, _ = await policy.needs_approval(ctx, "anything", {})
        assert need is False


class TestBudgetThresholdPolicy:
    async def test_token_threshold(self) -> None:
        policy = BudgetThresholdPolicy(token_threshold=100)
        ctx = MockContext(token_used=150)
        need, reason = await policy.needs_approval(ctx, "tool", {})
        assert need is True
        assert "Token" in reason

    async def test_step_threshold(self) -> None:
        policy = BudgetThresholdPolicy(step_threshold=5)
        ctx = MockContext(step_count=10)
        need, reason = await policy.needs_approval(ctx, "tool", {})
        assert need is True
        assert "Step" in reason

    async def test_under_threshold(self) -> None:
        policy = BudgetThresholdPolicy(token_threshold=1000, step_threshold=10)
        ctx = MockContext(token_used=50, step_count=3)
        need, _ = await policy.needs_approval(ctx, "tool", {})
        assert need is False

    async def test_zero_threshold_disabled(self) -> None:
        policy = BudgetThresholdPolicy()
        ctx = MockContext(token_used=99999, step_count=99999)
        need, _ = await policy.needs_approval(ctx, "tool", {})
        assert need is False


class TestRegexContentPolicy:
    async def test_matches_pattern(self) -> None:
        policy = RegexContentPolicy([r"password", r"secret"])
        ctx = MockContext()
        need, reason = await policy.needs_approval(
            ctx, "write_file", {"content": "my_password=123"}
        )
        assert need is True
        assert "password" in reason

    async def test_no_match(self) -> None:
        policy = RegexContentPolicy([r"secret"])
        ctx = MockContext()
        need, _ = await policy.needs_approval(ctx, "write_file", {"content": "public_info"})
        assert need is False


class TestCompoundPolicy:
    async def test_any_strategy_one_match(self) -> None:
        policy = CompoundPolicy([
            ToolNamePolicy(["deploy"]),
            BudgetThresholdPolicy(token_threshold=1000),
        ], strategy="any")
        ctx = MockContext(token_used=50)
        need, _ = await policy.needs_approval(ctx, "deploy", {})
        assert need is True

    async def test_any_strategy_no_match(self) -> None:
        policy = CompoundPolicy([
            ToolNamePolicy(["deploy"]),
            BudgetThresholdPolicy(token_threshold=1000),
        ], strategy="any")
        ctx = MockContext(token_used=50)
        need, _ = await policy.needs_approval(ctx, "get_weather", {})
        assert need is False

    async def test_all_strategy_all_match(self) -> None:
        policy = CompoundPolicy([
            ToolNamePolicy(["deploy"]),
            BudgetThresholdPolicy(token_threshold=50),
        ], strategy="all")
        ctx = MockContext(token_used=100)
        need, _ = await policy.needs_approval(ctx, "deploy", {})
        assert need is True

    async def test_all_strategy_partial_match(self) -> None:
        policy = CompoundPolicy([
            ToolNamePolicy(["deploy"]),
            BudgetThresholdPolicy(token_threshold=1000),
        ], strategy="all")
        ctx = MockContext(token_used=50)
        need, _ = await policy.needs_approval(ctx, "deploy", {})
        assert need is False

    async def test_invalid_strategy(self) -> None:
        with pytest.raises(ValueError, match="strategy 必须是"):
            CompoundPolicy([], strategy="invalid")


class TestHumanApprovalInterceptor:
    """HumanApprovalInterceptor 测试。"""

    async def test_no_approval_needed(self) -> None:
        policy = ToolNamePolicy(["deploy"])
        interceptor = HumanApprovalInterceptor(policy)
        ctx = MockContext()
        result = await interceptor({"tool_name": "get_weather", "arguments": {}}, ctx)
        from src.runtime._types import AllowAction
        assert isinstance(result, AllowAction)

    async def test_approval_needed_blocking(self) -> None:
        policy = ToolNamePolicy(["deploy"])
        interceptor = HumanApprovalInterceptor(policy, mode="sync_blocking")
        ctx = MockContext()
        result = await interceptor({"tool_name": "deploy", "arguments": {}}, ctx)
        from src.runtime._types import PauseAction
        assert isinstance(result, PauseAction)
        assert result.context["tool_name"] == "deploy"

    async def test_notify_only(self) -> None:
        policy = ToolNamePolicy(["deploy"])
        interceptor = HumanApprovalInterceptor(policy, mode="notify_only")
        ctx = MockContext()
        result = await interceptor({"tool_name": "deploy", "arguments": {}}, ctx)
        from src.runtime._types import AllowAction
        assert isinstance(result, AllowAction)

    async def test_mark_approved(self) -> None:
        policy = ToolNamePolicy(["deploy"])
        interceptor = HumanApprovalInterceptor(policy)
        interceptor.mark_approved("approval_1")
        ctx = MockContext()
        result = await interceptor(
            {"tool_name": "deploy", "arguments": {}, "approval_id": "approval_1"}, ctx
        )
        from src.runtime._types import AllowAction
        assert isinstance(result, AllowAction)


class TestSelfCritiqueHook:
    """SelfCritiqueHook 测试。"""

    async def test_basic_call(self) -> None:
        from src.runtime.hooks._critique_hook import SelfCritiqueHook
        hook = SelfCritiqueHook()
        ctx = type("MockCtx", (), {"services": {}, "step_index": 1})()
        await hook({"response": "test"}, ctx)
        assert "_critique_results" in ctx.services
        assert len(ctx.services["_critique_results"]) == 1

    async def test_no_response(self) -> None:
        from src.runtime.hooks._critique_hook import SelfCritiqueHook
        hook = SelfCritiqueHook()
        ctx = type("MockCtx", (), {"services": {}, "step_index": 1})()
        await hook({}, ctx)
        assert "_critique_results" not in ctx.services


class TestDualModelCritiqueHook:
    """DualModelCritiqueHook 测试。"""

    async def test_basic_call(self) -> None:
        from src.runtime.hooks._critique_hook import DualModelCritiqueHook

        async def mock_critic(ctx):
            return "ACCEPT"

        hook = DualModelCritiqueHook(critic_executor=mock_critic)
        ctx = type("MockCtx", (), {"services": {}, "step_index": 1})()
        await hook({"response": "test"}, ctx)
        assert "_critique_results" in ctx.services

    async def test_no_response(self) -> None:
        from src.runtime.hooks._critique_hook import DualModelCritiqueHook

        hook = DualModelCritiqueHook(critic_executor=lambda ctx: "ACCEPT")
        ctx = type("MockCtx", (), {"services": {}, "step_index": 1})()
        await hook({}, ctx)
        assert "_critique_results" not in ctx.services

    async def test_default_rounds(self) -> None:
        from src.runtime.hooks._critique_hook import DualModelCritiqueHook

        hook = DualModelCritiqueHook(critic_executor=None)
        assert hook._max_rounds == 2


class TestReplanHook:
    """ReplanHook 测试。"""

    async def test_basic_transform(self) -> None:
        from src.runtime.hooks._replan_hook import ReplanHook

        replan_called = False

        def should_replan(ctx):
            return True

        async def replanner_fn(ctx):
            nonlocal replan_called
            replan_called = True
            return {"steps": [{"id": "new", "description": "new step"}]}

        hook = ReplanHook(should_replan=should_replan, replanner_fn=replanner_fn)
        mock_runtime = type("MockRt", (), {"_plan": None})()
        ctx = type("MockCtx", (), {"services": {"_runtime": mock_runtime}})()
        result = await hook({}, ctx)
        assert result == {}
        assert replan_called is True

    async def test_max_replans_limit(self) -> None:
        from src.runtime.hooks._replan_hook import ReplanHook

        call_count = 0

        def should_replan(ctx):
            return True

        async def replanner_fn(ctx):
            nonlocal call_count
            call_count += 1
            return {"steps": []}

        mock_runtime = type("MockRt", (), {"_plan": None})()

        def make_ctx():
            return type("MockCtx", (), {"services": {"_runtime": mock_runtime}})()

        hook = ReplanHook(
            should_replan=should_replan,
            replanner_fn=replanner_fn,
            max_replans=2,
        )
        # 第 1 次
        result = await hook({}, make_ctx())
        assert result == {}
        # 第 2 次
        result = await hook({}, make_ctx())
        assert result == {}
        # 第 3 次——超过 max_replans，不触发
        hook._replan_count = 2
        result = await hook({}, make_ctx())
        assert result == {}
        assert call_count == 2

    async def test_no_runtime(self) -> None:
        from src.runtime.hooks._replan_hook import ReplanHook

        hook = ReplanHook(should_replan=lambda ctx: True, replanner_fn=lambda ctx: {})
        ctx = type("MockCtx", (), {"services": {}})()
        result = await hook({}, ctx)
        assert result == {}
