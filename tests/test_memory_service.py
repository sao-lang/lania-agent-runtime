"""
MemoryService 集成测试。

覆盖 recall / recall_raw / commit / checkpoint / restore 等核心方法。
"""

from __future__ import annotations

import pytest

from src.memory._backends._sqlite import SQLitePersistence
from src.memory._service import MemoryService
from src.memory._types import (
    EpisodicMemoryEntry,
    StepContext,
    WorkingMemorySnapshot,
)


@pytest.fixture
async def memory():
    persistence = SQLitePersistence(":memory:")
    svc = MemoryService(persistence=persistence)
    yield svc


class TestMemoryService:
    """MemoryService 核心功能测试。"""

    async def test_recall_raw_empty(self, memory):
        result = await memory.recall_raw("sess_1")
        assert result.episodic_memories == []
        assert result.entity_profile == {}
        assert result.concepts == []
        assert result.tone_instruction == ""

    async def test_recall_raw_with_data(self, memory):
        entry = EpisodicMemoryEntry(
            session_id="sess_1", turn_index=0, summary="test"
        )
        await memory._episodic.write(entry)
        result = await memory.recall_raw("sess_1")
        assert len(result.episodic_memories) == 1
        assert result.episodic_memories[0].summary == "test"

    async def test_recall_raw_turn_ranges(self, memory):
        for i in range(5):
            entry = EpisodicMemoryEntry(
                session_id="sess_1", turn_index=i, summary=f"turn_{i}"
            )
            await memory._episodic.write(entry)

        result = await memory.recall_raw("sess_1", turn_ranges=[(1, 3)])
        turns = {e.turn_index for e in result.episodic_memories}
        assert turns == {1, 2, 3}

    async def test_recall_basic(self, memory):
        entry = EpisodicMemoryEntry(
            session_id="sess_1", turn_index=0, summary="test_memory"
        )
        await memory._episodic.write(entry)
        result = await memory.recall("sess_1")
        assert "test_memory" in str(result.get("memories", []))

    async def test_commit_episodic(self, memory):
        step = StepContext(
            turn_index=0,
            session_id="sess_1",
            user_id="u1",
            summary="test",
            raw="hello world",
            importance=0.5,
        )
        await memory.commit("sess_1", "u1", step)
        entries = await memory._episodic.recall_session("sess_1")
        assert len(entries) == 1
        assert entries[0].summary == "test"

    async def test_commit_critical_event(self, memory):
        step = StepContext(
            turn_index=0,
            session_id="sess_1",
            user_id="u1",
            summary="important",
            raw="我叫小明",
            importance=0.9,
        )
        await memory.commit("sess_1", "u1", step)
        entries = await memory._episodic.recall_session("sess_1")
        assert entries[0].content_type == "critical_event"

    async def test_checkpoint_and_restore(self, memory):
        snap = WorkingMemorySnapshot(
            session_id="sess_1", step_index=3,
            messages=[{"role": "user", "content": "hi"}],
        )
        await memory.checkpoint(snap)
        restored = await memory.restore("sess_1")
        assert restored is not None
        assert restored.step_index == 3

    async def test_discard_checkpoint(self, memory):
        snap = WorkingMemorySnapshot(session_id="sess_1")
        await memory.checkpoint(snap)
        await memory.discard_checkpoint("sess_1")
        assert await memory.restore("sess_1") is None

    async def test_recall_with_user_id(self, memory):
        await memory._entity.upsert_attribute(
            "user", "u1", "name", "Alice",
            source_session="sess_1",
        )
        result = await memory.recall_raw("sess_1", user_id="u1")
        assert "name" in result.entity_profile

    async def test_property_accessors(self, memory):
        assert memory.episodic is not None
        assert memory.entity is not None
        assert memory.semantic is not None
        assert memory.pattern is not None

    async def test_safe_background_task_success(self):
        async def good():
            return 42

        result = await MemoryService._safe_background_task(good(), "good")
        assert result is None  # _safe_background_task 不返回值

    async def test_safe_background_task_failure(self):
        async def bad():
            raise ValueError("test error")

        # 不应该抛出异常
        await MemoryService._safe_background_task(bad(), "bad")
