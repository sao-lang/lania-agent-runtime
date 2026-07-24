"""
ContextManager 端到端测试。

覆盖：五阶段管线串联、Mock MemoryService、完整 assemble 流程。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.context._config import ContextConfig
from src.context._manager import ContextManager
from src.memory._types import EpisodicMemoryEntry, RecallResult


@pytest.fixture
def mock_memory() -> MagicMock:
    """创建 mock MemoryService。"""
    memory = MagicMock()
    memory.recall_raw = AsyncMock(return_value=RecallResult(
        episodic_memories=[
            EpisodicMemoryEntry(
                id="mem_0", session_id="test", turn_index=0,
                summary="用户询问天气", importance=0.8,
            ),
            EpisodicMemoryEntry(
                id="mem_1", session_id="test", turn_index=1,
                summary="助理回答晴天", importance=0.5,
            ),
        ],
        entity_profile={"name": {"value": "Alice"}},
        concepts=[{"name": "Python", "description": "编程语言"}],
        tone_instruction="用户偏好: 简洁回复",
    ))
    return memory


@pytest.fixture
def ctx() -> MagicMock:
    """创建 mock RuntimeContext。"""
    c = MagicMock()
    c.session_id = "test_sess"
    c.step_index = 2
    c.messages = (
        {"role": "system", "content": "You are a helper"},
        {"role": "user", "content": "天气怎么样？"},
        {"role": "assistant", "content": "今天是晴天。"},
    )
    c.services = {"user_id": "user_1"}
    c.budget.token_limit = 16000
    return c


class TestContextManager:
    """ContextManager 单元测试。"""

    async def test_assemble_basic(self, mock_memory: MagicMock, ctx: MagicMock) -> None:
        """测试 assemble 返回正确的 messages 格式。"""
        manager = ContextManager(
            memory=mock_memory,
            config=ContextConfig(max_context_tokens=16000),
        )
        messages = await manager.assemble(ctx)

        assert isinstance(messages, list)
        assert len(messages) > 0
        # 第一条是 system message
        assert messages[0]["role"] == "system"
        assert "You are a helper" in messages[0]["content"]

    async def test_assemble_includes_raw_messages(
        self, mock_memory: MagicMock, ctx: MagicMock,
    ) -> None:
        """测试 assemble 包含保留的原始消息。"""
        manager = ContextManager(
            memory=mock_memory,
            config=ContextConfig(max_context_tokens=16000, preserve_turns=10),
        )
        messages = await manager.assemble(ctx)

        # 应包含 user 和 assistant 消息
        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "assistant" in roles

    async def test_assemble_with_memory_data(
        self, mock_memory: MagicMock, ctx: MagicMock,
    ) -> None:
        """测试 assemble 包含记忆数据。"""
        manager = ContextManager(
            memory=mock_memory,
            config=ContextConfig(max_context_tokens=16000),
        )
        messages = await manager.assemble(ctx)

        # system message 应包含记忆内容
        system_content = messages[0]["content"]
        assert "用户询问天气" in system_content or "记忆" in system_content

    async def test_assemble_calls_recall_raw(
        self, mock_memory: MagicMock, ctx: MagicMock,
    ) -> None:
        """测试 assemble 调用了 MemoryService.recall_raw。"""
        manager = ContextManager(
            memory=mock_memory,
            config=ContextConfig(max_context_tokens=16000),
        )
        await manager.assemble(ctx)

        mock_memory.recall_raw.assert_awaited_once()
        call_args = mock_memory.recall_raw.await_args
        assert call_args is not None
        assert call_args.kwargs["session_id"] == "test_sess"

    async def test_assemble_empty_messages(self, mock_memory: MagicMock) -> None:
        """测试空消息列表。"""
        ctx = MagicMock()
        ctx.session_id = "test"
        ctx.step_index = 0
        ctx.messages = ()
        ctx.services = {}
        ctx.budget.token_limit = 4096

        manager = ContextManager(
            memory=mock_memory,
            config=ContextConfig(max_context_tokens=4096),
        )
        messages = await manager.assemble(ctx)
        assert isinstance(messages, list)

    async def test_assemble_low_token_budget(
        self, mock_memory: MagicMock, ctx: MagicMock,
    ) -> None:
        """测试低 token 预算下的降级行为。"""
        manager = ContextManager(
            memory=mock_memory,
            config=ContextConfig(max_context_tokens=1000),
        )
        messages = await manager.assemble(ctx)
        assert isinstance(messages, list)
        assert len(messages) > 0

    async def test_custom_components(
        self, mock_memory: MagicMock, ctx: MagicMock,
    ) -> None:
        """测试注入自定义组件。"""
        from src.context._selector import Selector

        custom_selector = Selector()
        manager = ContextManager(
            memory=mock_memory,
            selector=custom_selector,
            config=ContextConfig(max_context_tokens=16000),
        )
        messages = await manager.assemble(ctx)
        assert isinstance(messages, list)
        assert len(messages) > 0
