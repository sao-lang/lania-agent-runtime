"""
记忆管理组件测试。

覆盖 MemoryCommitGate / CompressionManager / EvictionManager / ConflictResolver。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.memory._backends._sqlite import SQLitePersistence
from src.memory._management._compressor import CompressionManager
from src.memory._management._conflict import ConflictResolver
from src.memory._management._eviction import EvictionManager
from src.memory._management._gate import MemoryCommitGate
from src.memory._stores import (
    EntityMemoryStore,
    EpisodicMemoryStore,
    SemanticKnowledgeStore,
)
from src.memory._types import EpisodicMemoryEntry


class TestMemoryCommitGate:
    """MemoryCommitGate 测试。"""

    @pytest.fixture
    def gate(self):
        return MemoryCommitGate()

    async def test_skip_empty(self, gate):
        d = await gate.evaluate("", None)
        assert d.should_record is False

    async def test_skip_hi(self, gate):
        d = await gate.evaluate("你好", None)
        assert d.should_record is False

    async def test_skip_thanks(self, gate):
        d = await gate.evaluate("谢谢", None)
        assert d.should_record is False

    async def test_skip_ok(self, gate):
        d = await gate.evaluate("好的", None)
        assert d.should_record is False

    async def test_skip_no_input(self, gate):
        d = await gate.evaluate(None, None)
        assert d.should_record is False
        assert d.reason == "no_user_input"

    async def test_critical_self_intro(self, gate):
        d = await gate.evaluate("我叫小明", None)
        assert d.should_record is True
        assert d.importance >= 0.9

    async def test_critical_preference(self, gate):
        d = await gate.evaluate("我喜欢Python", None)
        assert d.should_record is True
        assert d.importance >= 0.9

    async def test_critical_working_on(self, gate):
        d = await gate.evaluate("我在做一个项目", None)
        assert d.should_record is True
        assert d.importance >= 0.9

    async def test_long_response_boost(self, gate):
        d = await gate.evaluate("帮我分析这段代码", "x" * 300)
        assert d.should_record is True
        assert d.importance >= 0.5

    async def test_general_conversation(self, gate):
        d = await gate.evaluate("今天天气怎么样", None)
        assert d.should_record is True  # importance >= 0.3
        assert d.importance == 0.3

    async def test_critical_project(self, gate):
        d = await gate.evaluate("我在开发一个电商平台", None)
        assert d.should_record is True
        assert d.importance >= 0.9
        assert d.reason == "critical_info"


class TestCompressionManager:
    """CompressionManager 测试。"""

    async def test_should_merge_false(self):
        store = MagicMock(spec=EpisodicMemoryStore)
        store.count_session = AsyncMock(return_value=10)
        mgr = CompressionManager(store)
        mgr.MERGE_AFTER_TURNS = 50
        result = await mgr.should_merge("sess_1")
        assert result is False

    async def test_should_merge_true(self):
        store = MagicMock(spec=EpisodicMemoryStore)
        store.count_session = AsyncMock(return_value=50)
        mgr = CompressionManager(store)
        mgr.MERGE_AFTER_TURNS = 50
        result = await mgr.should_merge("sess_1")
        assert result is True

    async def test_merge_session(self):
        persistence = SQLitePersistence(":memory:")
        store = EpisodicMemoryStore(persistence)

        for i in range(3):
            entry = EpisodicMemoryEntry(
                session_id="sess_1", turn_index=i,
                summary=f"summary_{i}", importance=0.5 + i * 0.1,
            )
            await store.write(entry)

        mgr = CompressionManager(store)
        mgr.MERGE_WINDOW_SIZE = 20
        await mgr.merge_session("sess_1")

        entries = await store.recall_session("sess_1")
        assert len(entries) == 4

        await persistence.close()

    async def test_merge_empty(self):
        store = MagicMock(spec=EpisodicMemoryStore)
        store.recall_session = AsyncMock(return_value=[])
        mgr = CompressionManager(store)
        await mgr.merge_session("sess_1")


class TestEvictionManager:
    """EvictionManager 测试。"""

    async def test_evict_expired_noop(self):
        epis = MagicMock(spec=EpisodicMemoryStore)
        epis.delete_before = AsyncMock()
        sem = MagicMock(spec=SemanticKnowledgeStore)
        sem.get_low_mention_nodes = AsyncMock(return_value=[])
        mgr = EvictionManager(epis, sem)
        await mgr.evict_expired("u1")
        epis.delete_before.assert_called()


class TestConflictResolver:
    """ConflictResolver 测试。"""

    async def test_new_attribute(self):
        store = MagicMock(spec=EntityMemoryStore)
        store.read = AsyncMock(return_value=None)
        resolver = ConflictResolver(store)
        ok, reason = await resolver.resolve("user", "u1", "name", "Alice", 0.9)
        assert ok is True
        assert "新属性" in reason

    async def test_high_confidence_overrides(self):
        from src.memory._types import EntityAttributeValue

        entity = MagicMock()
        entity.attributes = {
            "name": EntityAttributeValue(value="Bob", confidence=0.5),
        }
        store = MagicMock(spec=EntityMemoryStore)
        store.read = AsyncMock(return_value=entity)
        resolver = ConflictResolver(store)
        ok, reason = await resolver.resolve("user", "u1", "name", "Alice", 0.8)
        # 0.8 >= 0.5 * 1.2 = 0.6 → 覆盖
        assert ok is True

    async def test_low_confidence_no_override(self):
        from src.memory._types import EntityAttributeValue

        entity = MagicMock()
        entity.attributes = {
            "name": EntityAttributeValue(value="Bob", confidence=0.9),
        }
        store = MagicMock(spec=EntityMemoryStore)
        store.read = AsyncMock(return_value=entity)
        resolver = ConflictResolver(store)
        ok, reason = await resolver.resolve("user", "u1", "name", "Alice", 0.5)
        # 0.5 < 0.9 * 1.2 = 1.08 → 不覆盖
        assert ok is False
