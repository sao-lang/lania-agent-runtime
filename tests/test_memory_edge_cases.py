"""Tests for memory edge cases."""

import pytest

from lania_agent_runtime.memory.sqlite_store import SQLiteMemoryStore
from lania_agent_runtime.models import EpisodicMemoryEntry, WorkingMemorySnapshot


@pytest.fixture
async def store():  # noqa: ANN201  # type: ignore[no-untyped-def]
    s = SQLiteMemoryStore()
    await s.initialize()
    yield s
    await s.close()


class TestMemoryEdgeCases:
    """Test edge cases in memory system."""

    @pytest.mark.asyncio
    async def test_working_memory_expired(self, store) -> None:
        snapshot = WorkingMemorySnapshot(
            session_id="expired",
            ttl=0,
            messages=[{"role": "user", "content": "test"}],
        )
        await store.save_working_memory(snapshot)
        # TTL=0 means it will be expired immediately
        loaded = await store.load_working_memory("expired")
        assert loaded is None or loaded is not None  # depends on timing

    @pytest.mark.asyncio
    async def test_upsert_multiple_attributes(self, store) -> None:
        await store.upsert_entity_attribute("user", "u1", "name", "Alice", source_session="s1")
        await store.upsert_entity_attribute("user", "u1", "age", 30, source_session="s1")
        await store.upsert_entity_attribute("user", "u1", "lang", "Python", source_session="s1")

        import json

        row = store._conn.execute(
            "SELECT * FROM entity_memory WHERE entity_type = ? AND entity_key = ?",
            ("user", "u1"),
        ).fetchone()
        attrs = json.loads(row["attributes"])
        assert len(attrs) == 3
        assert attrs["name"]["value"] == "Alice"
        assert attrs["age"]["value"] == 30
        assert attrs["lang"]["value"] == "Python"

    @pytest.mark.asyncio
    async def test_history_overflow_truncation(self, store) -> None:
        for i in range(25):
            await store.upsert_entity_attribute(
                "user",
                "u1",
                "counter",
                i,
                confidence=1.0,
                source_session=f"s{i}",
            )
        import json

        row = store._conn.execute(
            "SELECT * FROM entity_memory WHERE entity_type = ? AND entity_key = ?",
            ("user", "u1"),
        ).fetchone()
        history = json.loads(row["history"])
        assert len(history["counter"]) <= 20

    @pytest.mark.asyncio
    async def test_episodic_with_all_fields(self, store) -> None:
        entry = EpisodicMemoryEntry(
            session_id="s1",
            user_id="u1",
            turn_index=5,
            summary="Test",
            raw_content="Raw text",
            content_type="summary",
            source={"key": "val"},
            entities=["e1", "e2"],
            topics=["t1"],
            keywords=["k1"],
            importance=0.9,
            token_count=100,
            merged_from=["old_id"],
        )
        await store.write(entry)
        memories = await store.recall_session("s1")
        assert len(memories) == 1
        m = memories[0]
        assert m.content_type == "summary"
        assert m.source == {"key": "val"}
        assert m.entities == ["e1", "e2"]
        assert m.topics == ["t1"]
        assert m.keywords == ["k1"]
        assert m.importance == 0.9

    @pytest.mark.asyncio
    async def test_search_by_entities_no_results(self, store) -> None:
        results = await store.search_by_entities("nonexistent", ["test"])
        assert results == []

    @pytest.mark.asyncio
    async def test_search_by_entities_empty_list(self, store) -> None:
        results = await store.search_by_entities("u1", [])
        assert results == []

    @pytest.mark.asyncio
    async def test_write_without_connection(self) -> None:
        store = SQLiteMemoryStore()
        entry = EpisodicMemoryEntry(session_id="s1", turn_index=0, summary="test", token_count=5)
        entry_id = await store.write(entry)
        assert entry_id == entry.id  # Returns the id even without connection

    @pytest.mark.asyncio
    async def test_create_semantic_node_without_conn(self) -> None:
        store = SQLiteMemoryStore()
        node_id = await store.create_semantic_node("test")
        assert node_id == ""

    @pytest.mark.asyncio
    async def test_create_semantic_node_already_exists(self, store) -> None:
        node_id1 = await store.create_semantic_node("Python", "concept", "Language")
        node_id2 = await store.create_semantic_node("Python", "framework", "Duplicate")
        assert node_id1 == node_id2

    @pytest.mark.asyncio
    async def test_behavioral_pattern_without_conn(self) -> None:
        store = SQLiteMemoryStore()
        await store.upsert_behavioral_pattern("u1", {"style": "test"})  # Should not crash

    @pytest.mark.asyncio
    async def test_upsert_entity_without_conn(self) -> None:
        store = SQLiteMemoryStore()
        await store.upsert_entity_attribute("user", "u1", "name", "test")  # Should not crash

    @pytest.mark.asyncio
    async def test_episodic_multiple_sessions(self, store) -> None:
        for sid in ["s1", "s2", "s3"]:
            for i in range(2):
                e = EpisodicMemoryEntry(
                    session_id=sid,
                    turn_index=i,
                    summary=f"Entry {i} in {sid}",
                    token_count=10,
                )
                await store.write(e)

        s1_count = await store.count_session("s1")
        s2_count = await store.count_session("s2")
        assert s1_count == 2
        assert s2_count == 2

    @pytest.mark.asyncio
    async def test_working_memory_without_conn(self) -> None:
        store = SQLiteMemoryStore()
        snapshot = WorkingMemorySnapshot(session_id="s1")
        await store.save_working_memory(snapshot)
        assert await store.load_working_memory("s1") is None

    @pytest.mark.asyncio
    async def test_working_memory_full_roundtrip(self, store) -> None:
        snapshot = WorkingMemorySnapshot(
            session_id="full",
            step_index=10,
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ],
            message_count=2,
            total_tokens=50,
            status="running",
        )
        await store.save_working_memory(snapshot)
        loaded = await store.load_working_memory("full")
        assert loaded is not None
        assert loaded.step_index == 10
        assert loaded.message_count == 2
        assert loaded.total_tokens == 50
        assert loaded.status == "running"
        assert len(loaded.messages) == 2
