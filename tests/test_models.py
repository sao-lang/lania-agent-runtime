"""Tests for data models."""

from lania_agent_runtime.models import (
    ContextPayload,
    LLMResponse,
    LLMUsage,
    PriorityHints,
    RunResult,
    RuntimeStatus,
    StreamEvent,
    ToolCall,
)


class TestModels:
    """Test core data models."""

    def test_llm_usage_total_tokens(self) -> None:
        u = LLMUsage(prompt_tokens=100, completion_tokens=50)
        assert u.total_tokens == 150

    def test_llm_usage_defaults(self) -> None:
        u = LLMUsage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0

    def test_tool_call_creation(self) -> None:
        tc = ToolCall(
            id="call_1",
            name="get_weather",
            arguments={"city": "Beijing"},
            raw_arguments='{"city": "Beijing"}',
        )
        assert tc.id == "call_1"
        assert tc.name == "get_weather"
        assert tc.arguments["city"] == "Beijing"

    def test_llm_response_defaults(self) -> None:
        r = LLMResponse()
        assert r.content == ""
        assert r.tool_calls == []
        assert r.finish_reason == "stop"
        assert r.model == ""

    def test_llm_response_with_data(self) -> None:
        tc = ToolCall(id="c1", name="test", arguments={}, raw_arguments="{}")
        r = LLMResponse(
            content="hello", tool_calls=[tc], finish_reason="tool_calls", model="deepseek"
        )
        assert r.content == "hello"
        assert len(r.tool_calls) == 1
        assert r.finish_reason == "tool_calls"

    def test_run_result_creation(self) -> None:
        result = RunResult(
            content="Hello!",
            session_id="s1",
            messages=[{"role": "user", "content": "hi"}],
            tool_calls=[],
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
            finish_reason="stop",
        )
        assert result.content == "Hello!"
        assert result.session_id == "s1"
        assert result.usage.total_tokens == 15

    def test_stream_event_text(self) -> None:
        e = StreamEvent(type="text", content="Hello")
        assert e.type == "text"
        assert e.content == "Hello"

    def test_stream_event_done(self) -> None:
        e = StreamEvent(type="done", metadata={"key": "val"})
        assert e.type == "done"
        assert e.metadata["key"] == "val"

    def test_stream_event_error(self) -> None:
        e = StreamEvent(type="error", error="Something went wrong")
        assert e.type == "error"
        assert e.error == "Something went wrong"

    def test_runtime_status_values(self) -> None:
        assert RuntimeStatus.IDLE.value == "idle"
        assert RuntimeStatus.RUNNING.value == "running"
        assert RuntimeStatus.PAUSED.value == "paused"
        assert RuntimeStatus.ERROR.value == "error"
        assert RuntimeStatus.ENDED.value == "ended"

    def test_priority_hints_defaults(self) -> None:
        ph = PriorityHints()
        assert ph.preserve_last_n_history == 3
        assert ph.max_tokens == 4096
        assert ph.reserve_for_response == 1024

    def test_context_payload_empty_serialize(self) -> None:
        cp = ContextPayload()
        result = cp.serialize_to_system_message()
        assert result == ""

    def test_context_payload_with_system_prompt(self) -> None:
        cp = ContextPayload(system_prompt="You are a helpful assistant.")
        result = cp.serialize_to_system_message()
        assert "helpful assistant" in result

    def test_context_payload_with_tone_and_profile(self) -> None:
        cp = ContextPayload(
            system_prompt="You are a bot.",
            tone_instruction="Speak formally.",
            entity_profile={"name": {"value": "Alice"}},
        )
        result = cp.serialize_to_system_message()
        assert "Speak formally" in result
        assert "Alice" in result

    def test_context_payload_with_memories(self) -> None:
        cp = ContextPayload(
            system_prompt="Bot.",
            memories=[{"summary": "User likes Python", "created_at": "2024-01-01"}],
        )
        result = cp.serialize_to_system_message()
        assert "User likes Python" in result
        assert "Recent Memories" in result

    def test_context_payload_all_sections(self) -> None:
        cp = ContextPayload(
            system_prompt="Core prompt.",
            tone_instruction="Be concise.",
            entity_profile={"role": {"value": "developer"}},
            memories=[{"summary": "Memory 1", "created_at": "2024-01-01"}],
            concepts=[{"name": "Python", "description": "A language"}],
            rag_documents=[{"title": "Doc 1"}],
            injected_context=["Extra context"],
        )
        result = cp.serialize_to_system_message()
        assert "Core prompt" in result
        assert "Be concise" in result
        assert "developer" in result
        assert "Memory 1" in result
        assert "Python" in result
        assert "Doc 1" in result
        assert "Extra context" in result
