"""
测试 MessageSerializer / DefaultSerializer。
"""

from __future__ import annotations

from src.runtime.context._payload import ContextPayload
from src.runtime.context._serializer import DefaultSerializer


class TestDefaultSerializer:
    """测试 DefaultSerializer。"""

    async def test_serialize_empty(self) -> None:
        serializer = DefaultSerializer()
        payload = ContextPayload()
        messages = await serializer.serialize(payload)
        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == ""

    async def test_serialize_with_system_prompt(self) -> None:
        serializer = DefaultSerializer()
        payload = ContextPayload(system_prompt="你是一个助手")
        messages = await serializer.serialize(payload)
        assert len(messages) == 1
        assert messages[0]["content"] == "你是一个助手"

    async def test_serialize_with_memories(self) -> None:
        serializer = DefaultSerializer()
        payload = ContextPayload(
            system_prompt="你是助手",
            memories=["记忆1", "记忆2"],
        )
        messages = await serializer.serialize(payload)
        assert len(messages) == 1
        assert "[记忆]" in messages[0]["content"]
        assert "记忆1" in messages[0]["content"]
        assert "记忆2" in messages[0]["content"]

    async def test_serialize_with_rag_documents(self) -> None:
        serializer = DefaultSerializer()
        payload = ContextPayload(
            system_prompt="你是助手",
            rag_documents=["文档1", "文档2"],
        )
        messages = await serializer.serialize(payload)
        assert "[参考文档]" in messages[0]["content"]

    async def test_serialize_with_injected_context(self) -> None:
        serializer = DefaultSerializer()
        payload = ContextPayload(
            system_prompt="你是助手",
            injected_context=["额外信息"],
        )
        messages = await serializer.serialize(payload)
        assert "[附加上下文]" in messages[0]["content"]

    async def test_serialize_with_history(self) -> None:
        serializer = DefaultSerializer()
        payload = ContextPayload(
            system_prompt="你是助手",
            history=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
        )
        messages = await serializer.serialize(payload)
        assert len(messages) == 3
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"

    async def test_serialize_with_tool_results(self) -> None:
        serializer = DefaultSerializer()
        payload = ContextPayload(
            system_prompt="你是助手",
            tool_results=[
                {"role": "tool", "content": "result1"},
                {"role": "tool", "content": "result2"},
            ],
        )
        messages = await serializer.serialize(payload)
        assert len(messages) == 3
        assert messages[1]["role"] == "tool"
        assert messages[2]["role"] == "tool"

    async def test_dirty_flag_caching(self) -> None:
        serializer = DefaultSerializer()
        payload = ContextPayload(system_prompt="你是助手")
        payload.mark_clean()

        # 不 dirty 时复用缓存
        messages1 = await serializer.serialize(payload)
        messages2 = await serializer.serialize(payload)
        assert len(messages1) == 1
        assert messages1 == messages2

    async def test_dirty_flag_reserialize(self) -> None:
        serializer = DefaultSerializer()
        payload = ContextPayload(system_prompt="原始")
        messages1 = await serializer.serialize(payload)
        assert "原始" in messages1[0]["content"]

        # 修改后重新序列化
        payload.system_prompt = "更新后"
        payload.mark_dirty()
        messages2 = await serializer.serialize(payload)
        assert "更新后" in messages2[0]["content"]
