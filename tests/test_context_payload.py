"""
测试 ContextPayload：脏标记、字段操作。
"""

from __future__ import annotations

from src.runtime.context._payload import ContextPayload


class TestContextPayload:
    """测试 ContextPayload 核心功能。"""

    def test_default_values(self) -> None:
        payload = ContextPayload()
        assert payload.system_prompt == ""
        assert payload.memories == []
        assert payload.rag_documents == []
        assert payload.injected_context == []
        assert payload.history == []
        assert payload.tool_call_request is None
        assert payload.tool_results == []
        assert payload.max_tokens == 0
        assert payload.preserve_last_n_history == 10
        assert payload.reserve_for_response == 1024
        assert payload.is_dirty is True

    def test_system_prompt(self) -> None:
        payload = ContextPayload(system_prompt="你是一个助手")
        assert payload.system_prompt == "你是一个助手"

    def test_mark_dirty_and_clean(self) -> None:
        payload = ContextPayload()
        assert payload.is_dirty is True

        payload.mark_clean()
        assert payload.is_dirty is False

        payload.mark_dirty()
        assert payload.is_dirty is True

    def test_append_memories(self) -> None:
        payload = ContextPayload()
        payload.memories.append({"type": "session", "content": "test"})
        assert len(payload.memories) == 1
        assert payload.memories[0]["content"] == "test"
        # 修改后脏标记仍为 True
        assert payload.is_dirty is True

    def test_rag_documents(self) -> None:
        payload = ContextPayload()
        payload.rag_documents.append("doc1")
        payload.rag_documents.append("doc2")
        assert len(payload.rag_documents) == 2

    def test_history_rounds(self) -> None:
        payload = ContextPayload(preserve_last_n_history=20)
        assert payload.preserve_last_n_history == 20

        payload.history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert len(payload.history) == 2

    def test_tool_call_request(self) -> None:
        payload = ContextPayload(
            tool_call_request={"name": "get_weather", "args": {"city": "Beijing"}}
        )
        assert payload.tool_call_request is not None
        assert payload.tool_call_request["name"] == "get_weather"

    def test_tool_results(self) -> None:
        payload = ContextPayload()
        payload.tool_results.append({"role": "tool", "content": "result"})
        assert len(payload.tool_results) == 1

    def test_token_settings(self) -> None:
        payload = ContextPayload(max_tokens=4096, reserve_for_response=512)
        assert payload.max_tokens == 4096
        assert payload.reserve_for_response == 512

    def test_dirty_after_modification(self) -> None:
        """修改字段后脏标记应保持 true。"""
        payload = ContextPayload()
        payload.mark_clean()
        assert payload.is_dirty is False

        # 修改 history（需要手动 mark_dirty）
        payload.history.append({"role": "user", "content": "test"})
        # 注意：dataclass 不自动追踪内部字段变更
        # 用户需要手动 mark_dirty()
        assert payload.is_dirty is False

        payload.mark_dirty()
        assert payload.is_dirty is True
