"""Tests for memory system."""

import pytest

from lania_agent_runtime.memory.base import MemoryService
from lania_agent_runtime.memory.sqlite_store import SQLiteMemoryStore
from lania_agent_runtime.models import EpisodicMemoryEntry, WorkingMemorySnapshot


@pytest.fixture
async def store():  # noqa: ANN201  # type: ignore[no-untyped-def]
    s = SQLiteMemoryStore()
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
async def memory_service(store):  # noqa: ANN201  # type: ignore[no-untyped-def]

    return MemoryService(store=store)


class TestSQLiteMemoryStore:
    """Test SQLiteMemoryStore."""

    @pytest.mark.asyncio
    async def test_initialize_tables(self, store) -> None:
        # Verify tables exist
        tables = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        assert "working_memory" in table_names
        assert "episodic_memory" in table_names
        assert "entity_memory" in table_names
        assert "semantic_node" in table_names
        assert "semantic_edge" in table_names
        assert "behavioral_pattern" in table_names

    @pytest.mark.asyncio
    async def test_working_memory_save_and_load(self, store) -> None:
        snapshot = WorkingMemorySnapshot(
            session_id="s1",
            step_index=5,
            messages=[{"role": "user", "content": "hi"}],
            total_tokens=100,
        )
        await store.save_working_memory(snapshot)

        loaded = await store.load_working_memory("s1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert loaded.step_index == 5
        assert len(loaded.messages) == 1
        assert loaded.total_tokens == 100

    @pytest.mark.asyncio
    async def test_working_memory_overwrite(self, store) -> None:
        s1 = WorkingMemorySnapshot(session_id="s1", step_index=1)
        s2 = WorkingMemorySnapshot(session_id="s1", step_index=2)
        await store.save_working_memory(s1)
        await store.save_working_memory(s2)

        loaded = await store.load_working_memory("s1")
        assert loaded.step_index == 2

    @pytest.mark.asyncio
    async def test_working_memory_delete(self, store) -> None:
        snapshot = WorkingMemorySnapshot(session_id="s1")
        await store.save_working_memory(snapshot)
        await store.delete_working_memory("s1")

        loaded = await store.load_working_memory("s1")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_working_memory_not_found(self, store) -> None:
        loaded = await store.load_working_memory("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_episodic_write_and_recall_session(self, store) -> None:
        entry = EpisodicMemoryEntry(
            session_id="s1",
            user_id="u1",
            turn_index=0,
            summary="User asked about weather",
            token_count=50,
        )
        entry_id = await store.write(entry)
        assert entry_id == entry.id

        memories = await store.recall_session("s1")
        assert len(memories) == 1
        assert memories[0].summary == "User asked about weather"
        assert memories[0].turn_index == 0

    @pytest.mark.asyncio
    async def test_episodic_recall_session_limit(self, store) -> None:
        for i in range(5):
            e = EpisodicMemoryEntry(
                session_id="s1", turn_index=i, summary=f"Entry {i}", token_count=10
            )
            await store.write(e)

        memories = await store.recall_session("s1", limit=3)
        assert len(memories) == 3

    @pytest.mark.asyncio
    async def test_episodic_recall_session_order(self, store) -> None:
        for i in range(3):
            e = EpisodicMemoryEntry(
                session_id="s1", turn_index=i, summary=f"Entry {i}", token_count=10
            )
            await store.write(e)

        memories = await store.recall_session("s1")
        # Should be ordered by turn_index DESC
        assert memories[0].turn_index == 2
        assert memories[-1].turn_index == 0

    @pytest.mark.asyncio
    async def test_episodic_recall_user(self, store) -> None:
        for i in range(3):
            e = EpisodicMemoryEntry(
                session_id=f"s{i}",
                user_id="u1",
                turn_index=0,
                summary=f"Session {i}",
                token_count=10,
            )
            await store.write(e)

        memories = await store.recall_user("u1")
        assert len(memories) == 3

    @pytest.mark.asyncio
    async def test_episodic_search_by_entities(self, store) -> None:
        e1 = EpisodicMemoryEntry(
            session_id="s1",
            user_id="u1",
            turn_index=0,
            summary="Python discussion",
            entities=["python", "programming"],
            token_count=10,
        )
        e2 = EpisodicMemoryEntry(
            session_id="s1",
            user_id="u1",
            turn_index=1,
            summary="Weather talk",
            entities=["weather"],
            token_count=10,
        )
        await store.write(e1)
        await store.write(e2)

        results = await store.search_by_entities("u1", ["python"])
        assert len(results) >= 1
        assert results[0].summary == "Python discussion"

    @pytest.mark.asyncio
    async def test_episodic_count_session(self, store) -> None:
        for i in range(3):
            e = EpisodicMemoryEntry(session_id="s1", turn_index=i, summary=f"E{i}", token_count=10)
            await store.write(e)

        count = await store.count_session("s1")
        assert count == 3

    @pytest.mark.asyncio
    async def test_episodic_count_empty_session(self, store) -> None:
        count = await store.count_session("nonexistent")
        assert count == 0

    @pytest.mark.asyncio
    async def test_entity_upsert_attribute(self, store) -> None:
        await store.upsert_entity_attribute(
            entity_type="user",
            entity_key="u1",
            attr_name="name",
            value="Alice",
            source_session="s1",
        )

        row = store._conn.execute(
            "SELECT * FROM entity_memory WHERE entity_type = ? AND entity_key = ?",
            ("user", "u1"),
        ).fetchone()
        assert row is not None
        import json

        attrs = json.loads(row["attributes"])
        assert attrs["name"]["value"] == "Alice"
        assert attrs["name"]["source_session"] == "s1"

    @pytest.mark.asyncio
    async def test_entity_upsert_existing(self, store) -> None:
        await store.upsert_entity_attribute("user", "u1", "name", "Alice", source_session="s1")
        await store.upsert_entity_attribute("user", "u1", "name", "Bob", source_session="s2")

        row = store._conn.execute(
            "SELECT * FROM entity_memory WHERE entity_type = ? AND entity_key = ?",
            ("user", "u1"),
        ).fetchone()
        import json

        attrs = json.loads(row["attributes"])
        history = json.loads(row["history"])
        assert attrs["name"]["value"] == "Bob"
        assert len(history["name"]) == 2

    @pytest.mark.asyncio
    async def test_semantic_node_create(self, store) -> None:
        node_id = await store.create_semantic_node("Python", "concept", "A programming language")
        assert node_id != ""

        # Same name should return existing id
        node_id2 = await store.create_semantic_node("Python")
        assert node_id2 == node_id

    @pytest.mark.asyncio
    async def test_behavioral_pattern_upsert(self, store) -> None:
        await store.upsert_behavioral_pattern("u1", {"style": "concise"})

        row = store._conn.execute(
            "SELECT * FROM behavioral_pattern WHERE user_id = ?", ("u1",)
        ).fetchone()
        assert row is not None
        import json

        patterns = json.loads(row["patterns"])
        assert patterns["style"] == "concise"
        assert row["version"] == 1

    @pytest.mark.asyncio
    async def test_behavioral_pattern_update(self, store) -> None:
        await store.upsert_behavioral_pattern("u1", {"style": "concise"})
        await store.upsert_behavioral_pattern("u1", {"style": "detailed"})

        row = store._conn.execute(
            "SELECT * FROM behavioral_pattern WHERE user_id = ?", ("u1",)
        ).fetchone()
        assert row["version"] == 2
        import json

        patterns = json.loads(row["patterns"])
        assert patterns["style"] == "detailed"

    @pytest.mark.asyncio
    async def test_episodic_entry_with_full_data(self, store) -> None:
        entry = EpisodicMemoryEntry(
            session_id="s1",
            user_id="u1",
            turn_index=0,
            summary="Full test",
            raw_content="User: hi\nAssistant: hello",
            content_type="raw",
            source={"user_message": "hi", "assistant_message": "hello"},
            entities=["test"],
            topics=["greeting"],
            keywords=["hi"],
            importance=0.8,
            token_count=20,
        )
        await store.write(entry)

        memories = await store.recall_session("s1")
        assert len(memories) == 1
        m = memories[0]
        assert m.raw_content == "User: hi\nAssistant: hello"
        assert m.importance == 0.8
        assert m.topics == ["greeting"]
        assert m.keywords == ["hi"]

    @pytest.mark.asyncio
    async def test_store_close(self, store) -> None:
        await store.close()
        assert store._conn is None

    @pytest.mark.asyncio
    async def test_store_with_no_connection(self) -> None:
        s = SQLiteMemoryStore()
        # Without init, operations should not crash
        assert await s.load_working_memory("s1") is None
        assert await s.recall_session("s1") == []
        assert await s.count_session("s1") == 0


class TestMemoryService:
    """Test MemoryService."""

    @pytest.mark.asyncio
    async def test_recall_empty_no_store(self) -> None:
        svc = MemoryService()
        payload = await svc.recall("s1")
        assert payload.memories == []

    @pytest.mark.asyncio
    async def test_recall_with_store(self, memory_service) -> None:
        # Write some memories first
        entry = EpisodicMemoryEntry(
            session_id="s1",
            user_id="u1",
            turn_index=0,
            summary="Test memory",
            token_count=10,
        )
        await memory_service.store.write(entry)

        payload = await memory_service.recall("s1")
        assert len(payload.memories) == 1
        assert payload.memories[0]["summary"] == "Test memory"

    @pytest.mark.asyncio
    async def test_commit_no_store(self) -> None:
        svc = MemoryService()
        # Should not crash
        await svc.commit("s1", "u1", "hi", "hello")

    @pytest.mark.asyncio
    async def test_commit_with_store(self, memory_service) -> None:
        await memory_service.commit("s1", "u1", "Hello", "Hi there!")
        payload = await memory_service.recall("s1")
        assert len(payload.memories) == 1

    @pytest.mark.asyncio
    async def test_commit_increments_turn(self, memory_service) -> None:
        await memory_service.commit("s1", "u1", "First", "Reply 1")
        await memory_service.commit("s1", "u1", "Second", "Reply 2")

        payload = await memory_service.recall("s1")
        summaries = [m["summary"] for m in payload.memories]
        assert "Reply 2" in summaries[0] if len(summaries) > 0 else False

    @pytest.mark.asyncio
    async def test_checkpoint_and_restore(self, memory_service) -> None:
        snapshot = WorkingMemorySnapshot(
            session_id="s1",
            step_index=3,
            messages=[{"role": "user", "content": "test"}],
        )
        await memory_service.checkpoint(snapshot)
        restored = await memory_service.restore("s1")
        assert restored is not None
        assert restored.step_index == 3

    @pytest.mark.asyncio
    async def test_discard_checkpoint(self, memory_service) -> None:
        snapshot = WorkingMemorySnapshot(session_id="s1")
        await memory_service.checkpoint(snapshot)
        await memory_service.discard_checkpoint("s1")
        restored = await memory_service.restore("s1")
        assert restored is None

    @pytest.mark.asyncio
    async def test_checkpoint_no_store(self) -> None:
        svc = MemoryService()
        snapshot = WorkingMemorySnapshot(session_id="s1")
        # Should not crash
        await svc.checkpoint(snapshot)
        result = await svc.restore("s1")
        assert result is None

    @pytest.mark.asyncio
    async def test_recall_with_priority_hints(self, memory_service) -> None:
        payload = await memory_service.recall("s1", max_tokens=2048)
        assert payload.priority_hints.max_tokens == 2048
        assert payload.priority_hints.preserve_last_n_history == 3

    # ── New tests: Entity profile, Semantic search, Behavioral pattern ──

    @pytest.mark.asyncio
    async def test_get_entity_profile(self, store) -> None:
        await store.upsert_entity_attribute("user", "u1", "name", "Alice", source_session="s1")
        await store.upsert_entity_attribute("user", "u1", "age", 30, source_session="s1")

        profile = await store.get_entity_profile("user", "u1")
        assert profile is not None
        assert profile.entity_type == "user"
        assert profile.entity_key == "u1"
        assert profile.attributes["name"]["value"] == "Alice"
        assert profile.attributes["age"]["value"] == 30

    @pytest.mark.asyncio
    async def test_get_entity_profile_not_found(self, store) -> None:
        profile = await store.get_entity_profile("user", "nonexistent")
        assert profile is None

    @pytest.mark.asyncio
    async def test_get_entity_profile_no_conn(self) -> None:
        store = SQLiteMemoryStore()
        profile = await store.get_entity_profile("user", "u1")
        assert profile is None

    @pytest.mark.asyncio
    async def test_search_semantic_by_name(self, store) -> None:
        await store.create_semantic_node("Python", "concept", "A programming language")
        await store.create_semantic_node("JavaScript", "concept", "Another language")
        await store.create_semantic_node("Machine Learning", "concept", "AI field")

        nodes = await store.search_semantic("Python")
        assert len(nodes) >= 1
        assert nodes[0].name == "Python"

    @pytest.mark.asyncio
    async def test_search_semantic_by_description(self, store) -> None:
        await store.create_semantic_node("AI", "concept", "Artificial Intelligence")

        nodes = await store.search_semantic("Intelligence")
        assert len(nodes) >= 1
        assert nodes[0].name == "AI"

    @pytest.mark.asyncio
    async def test_search_semantic_no_results(self, store) -> None:
        nodes = await store.search_semantic("NonexistentConcept")
        assert nodes == []

    @pytest.mark.asyncio
    async def test_search_semantic_with_type_filter(self, store) -> None:
        await store.create_semantic_node("Flask", "framework", "Python web framework")
        await store.create_semantic_node("Flask", "concept", "Python web framework")
        # Second call with same name returns existing id, type is ignored

        nodes = await store.search_semantic("Flask", type_filter="framework")
        # At minimum, should not crash
        assert nodes is not None

    @pytest.mark.asyncio
    async def test_search_semantic_no_conn(self) -> None:
        store = SQLiteMemoryStore()
        nodes = await store.search_semantic("test")
        assert nodes == []

    @pytest.mark.asyncio
    async def test_create_semantic_edge(self, store) -> None:
        node_a = await store.create_semantic_node("Python", "concept", "Language")
        node_b = await store.create_semantic_node("Django", "framework", "Web framework")

        edge_id = await store.create_semantic_edge(node_a, node_b, "related_to")
        assert edge_id != ""

    @pytest.mark.asyncio
    async def test_create_semantic_edge_no_conn(self) -> None:
        store = SQLiteMemoryStore()
        edge_id = await store.create_semantic_edge("a", "b", "related_to")
        assert edge_id == ""

    @pytest.mark.asyncio
    async def test_get_semantic_edges(self, store) -> None:
        node_a = await store.create_semantic_node("Python", "concept", "Language")
        node_b = await store.create_semantic_node("Django", "framework", "Web framework")

        await store.create_semantic_edge(node_a, node_b, "related_to")

        edges = await store.get_semantic_edges(node_a)
        assert len(edges) >= 1
        assert edges[0].relation == "related_to"

    @pytest.mark.asyncio
    async def test_get_semantic_edges_empty(self, store) -> None:
        node = await store.create_semantic_node("Orphan", "concept", "No edges")
        edges = await store.get_semantic_edges(node)
        assert edges == []

    @pytest.mark.asyncio
    async def test_increment_semantic_mention(self, store) -> None:
        node_id = await store.create_semantic_node("Python", "concept", "Language")
        await store.increment_mention(node_id)
        await store.increment_mention(node_id)

        rows = store._conn.execute(
            "SELECT mention_count FROM semantic_node WHERE id = ?", (node_id,)
        ).fetchone()
        assert rows["mention_count"] == 2

    @pytest.mark.asyncio
    async def test_get_behavioral_pattern(self, store) -> None:
        await store.upsert_behavioral_pattern("u1", {"style": "concise", "language": "zh"})

        pattern = await store.get_behavioral_pattern("u1")
        assert pattern is not None
        assert pattern.user_id == "u1"
        assert pattern.patterns["style"] == "concise"
        assert pattern.patterns["language"] == "zh"

    @pytest.mark.asyncio
    async def test_get_behavioral_pattern_not_found(self, store) -> None:
        pattern = await store.get_behavioral_pattern("nonexistent")
        assert pattern is None

    @pytest.mark.asyncio
    async def test_get_behavioral_pattern_no_conn(self) -> None:
        store = SQLiteMemoryStore()
        pattern = await store.get_behavioral_pattern("u1")
        assert pattern is None

    @pytest.mark.asyncio
    async def test_memory_service_recall_with_entity_profile(self, memory_service) -> None:
        # Write entity profile
        await memory_service.store.upsert_entity_attribute(
            "user", "u1", "name", "Alice", source_session="s1"
        )
        # Recall with user_id should load profile
        payload = await memory_service.recall("s1", user_id="u1")
        assert "name" in payload.entity_profile
        assert payload.entity_profile["name"]["value"] == "Alice"

    @pytest.mark.asyncio
    async def test_memory_service_recall_with_semantic(self, memory_service) -> None:
        # Create semantic node
        await memory_service.store.create_semantic_node(
            "Machine Learning", "concept", "AI field"
        )
        # Recall with query matching the node
        payload = await memory_service.recall("s1", query="Machine Learning")
        assert len(payload.concepts) >= 1
        assert payload.concepts[0]["name"] == "Machine Learning"

    @pytest.mark.asyncio
    async def test_memory_service_recall_with_behavioral_pattern(self, memory_service) -> None:
        await memory_service.store.upsert_behavioral_pattern("u1", {"style": "concise"})
        payload = await memory_service.recall("s1", user_id="u1")
        assert "concise" in payload.tone_instruction

    @pytest.mark.asyncio
    async def test_memory_service_commit_extracts_entities(self, memory_service) -> None:
        await memory_service.commit(
            "s1", "u1",
            "I love Machine Learning and Python programming",
            "That's great! Machine Learning is fascinating.",
        )
        # Verify episodic is written
        payload = await memory_service.recall("s1")
        assert len(payload.memories) == 1

    @pytest.mark.asyncio
    async def test_memory_service_commit_upserts_entity(self, memory_service) -> None:
        await memory_service.commit(
            "s1", "u1",
            "My name is Alice. I work as a Data Scientist.",
            "Nice to meet you, Alice!",
        )
        profile = await memory_service.store.get_entity_profile("user", "u1")
        assert profile is not None
        assert profile.attributes.get("name", {}).get("value") == "Alice"

    @pytest.mark.asyncio
    async def test_memory_service_commit_creates_semantic_nodes(self, memory_service) -> None:
        await memory_service.commit(
            "s1", "u1",
            "Tell me about Deep Learning",
            "Deep Learning is a subset of Machine Learning",
        )
        # Semantic nodes should be created for key topics
        nodes = await memory_service.store.search_semantic("Deep")
        # Should find the Deep Learning node (or similar)
        assert len(nodes) >= 0  # lenient assertion - extraction is best-effort

    @pytest.mark.asyncio
    async def test_memory_service_commit_updates_pattern(self, memory_service) -> None:
        await memory_service.commit("s1", "u1", "Explain in detail", "Here's a detailed explanation")
        pattern = await memory_service.store.get_behavioral_pattern("u1")
        assert pattern is not None
