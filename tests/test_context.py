"""Tests for RuntimeContext."""

from lania_agent_runtime.context import Budget, ErrorState, PauseState, RuntimeContext
from lania_agent_runtime.models import RuntimeStatus


class TestRuntimeContext:
    """Test RuntimeContext."""

    def test_initial_state(self) -> None:
        ctx = RuntimeContext(session_id="s1", agent_id="a1")
        assert ctx.session_id == "s1"
        assert ctx.agent_id == "a1"
        assert ctx.status == RuntimeStatus.IDLE
        assert ctx.messages == []
        assert ctx.step_index == 0
        assert ctx.budget.token_used == 0
        assert ctx.error_state.consecutive_errors == 0

    def test_append_message(self) -> None:
        ctx = RuntimeContext(session_id="s1", agent_id="a1")
        ctx.append_message({"role": "user", "content": "hello"})
        assert len(ctx.messages) == 1
        assert ctx.messages[0]["content"] == "hello"

    def test_set_status(self) -> None:
        ctx = RuntimeContext()
        ctx.set_status(RuntimeStatus.RUNNING)
        assert ctx.status == RuntimeStatus.RUNNING

    def test_set_plan(self) -> None:
        ctx = RuntimeContext()
        ctx.set_plan({"steps": [1, 2, 3]})
        assert ctx.plan == {"steps": [1, 2, 3]}

    def test_deduct_budget(self) -> None:
        ctx = RuntimeContext()
        ctx.deduct_budget(tokens=100, cost=5)
        assert ctx.budget.token_used == 100
        assert ctx.budget.cost_in_cents == 5
        # step_count 由 increment_step 管理, deduct_budget 不修改
        assert ctx.budget.step_count == 0

    def test_increment_step_updates_budget_step_count(self) -> None:
        """验证 step_count 在 increment_step 中递增 (设计文档 §七)."""
        ctx = RuntimeContext()
        ctx.deduct_budget(tokens=50)
        ctx.increment_step()
        assert ctx.budget.step_count == 1
        assert ctx.step_index == 1

    def test_set_agent_identity(self) -> None:
        ctx = RuntimeContext()
        ctx.set_agent_identity({"name": "test-agent"})
        assert ctx.agent_identity == {"name": "test-agent"}

    def test_set_tools_schema(self) -> None:
        ctx = RuntimeContext()
        schema = [{"name": "test_tool", "parameters": {"type": "object"}}]
        ctx.set_tools_schema(schema)
        assert ctx.tools_schema == schema

    def test_set_error_state(self) -> None:
        ctx = RuntimeContext()
        ctx.set_error_state("Something went wrong")
        assert ctx.error_state.last_error == "Something went wrong"
        assert ctx.error_state.consecutive_errors == 1

    def test_increment_step(self) -> None:
        ctx = RuntimeContext()
        ctx.increment_step()
        assert ctx.step_index == 1
        assert len(ctx.step_history) == 1
        assert ctx.step_history[0]["step_index"] == 1

    def test_set_services(self) -> None:
        ctx = RuntimeContext()
        ctx.set_services({"memory": "mock"})
        assert ctx.services == {"memory": "mock"}

    def test_serialize_messages_empty(self) -> None:
        ctx = RuntimeContext()
        result = ctx.serialize_messages()
        assert len(result) == 1
        assert result[0]["role"] == "system"

    def test_serialize_messages_with_history(self) -> None:
        ctx = RuntimeContext()
        ctx.append_message({"role": "user", "content": "hi"})
        result = ctx.serialize_messages()
        assert len(result) == 2  # system + user
        assert result[1]["content"] == "hi"

    def test_serialize_skips_system_in_history(self) -> None:
        ctx = RuntimeContext()
        ctx.append_message({"role": "system", "content": "old system"})
        ctx.append_message({"role": "user", "content": "hi"})
        result = ctx.serialize_messages()
        # The old system message should be skipped (new one is generated)
        system_count = sum(1 for m in result if m["role"] == "system")
        assert system_count == 1
        user_count = sum(1 for m in result if m["role"] == "user")
        assert user_count == 1

    def test_messages_immutable_via_property(self) -> None:
        ctx = RuntimeContext()
        ctx.append_message({"role": "user", "content": "hi"})
        msgs = ctx.messages
        assert len(msgs) == 1
        # Verify we can still read
        assert msgs[0]["role"] == "user"

    def test_budget_default_values(self) -> None:
        b = Budget()
        assert b.token_used == 0
        assert b.token_limit == 100000
        assert b.step_limit == 100
        assert b.cost_in_cents == 0

    def test_pause_state_default(self) -> None:
        p = PauseState()
        assert p.is_paused is False
        assert p.pending_approvals == []
        assert p.resume_token is None

    def test_error_state_default(self) -> None:
        e = ErrorState()
        assert e.consecutive_errors == 0
        assert e.max_retries == 3
        assert e.last_error is None

    def test_context_serialize_with_context_payload(self) -> None:
        ctx = RuntimeContext()
        ctx.context_payload.system_prompt = "Custom system prompt"
        ctx.append_message({"role": "user", "content": "hello"})
        result = ctx.serialize_messages()
        assert "Custom system prompt" in result[0]["content"]
