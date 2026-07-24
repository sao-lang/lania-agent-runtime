"""
Stores 单元测试。

覆盖 WorkingMemoryStore / EpisodicMemoryStore / EntityMemoryStore /
SemanticKnowledgeStore / BehavioralPatternStore 全部 5 个 Store。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.memory._backends._sqlite import SQLitePersistence
from src.memory._stores import (
    BehavioralPatternStore,
    EntityMemoryStore,
    EpisodicMemoryStore,
    SemanticKnowledgeStore,
    WorkingMemoryStore,
)
from src.memory._types import (
    BehavioralPattern,
    EpisodicMemoryEntry,
    SemanticNode,
    WorkingMemorySnapshot,
)


@pytest.fixture
async def persistence():
    store = SQLitePersistence(":memory:")
    yield store
    await store.close()


class TestWorkingMemoryStore:
    """WorkingMemoryStore 测试。"""

    async def test_save_and_load(self, persistence):
        store = WorkingMemoryStore(persistence)
        snap = WorkingMemorySnapshot(
            session_id="sess_1",
            step_index=5,
            messages=[{"role": "user", "content": "hi"}],
            status="running",
        )
        await store.save(snap)

        loaded = await store.load("sess_1")
        assert loaded is not None
        assert loaded.session_id == "sess_1"
        assert loaded.step_index == 5
        assert loaded.status == "running"

    async def test_load_nonexistent(self, persistence):
        store = WorkingMemoryStore(persistence)
        loaded = await store.load("nonexistent")
        assert loaded is None

    async def test_overwrite(self, persistence):
        store = WorkingMemoryStore(persistence)
        snap1 = WorkingMemorySnapshot(session_id="sess_1", step_index=1)
        snap2 = WorkingMemorySnapshot(session_id="sess_1", step_index=2)
        await store.save(snap1)
        await store.save(snap2)

        loaded = await store.load("sess_1")
        assert loaded.step_index == 2

    async def test_delete(self, persistence):
        store = WorkingMemoryStore(persistence)
        snap = WorkingMemorySnapshot(session_id="sess_1")
        await store.save(snap)
        await store.delete("sess_1")
        assert await store.load("sess_1") is None

    async def test_exists(self, persistence):
        store = WorkingMemoryStore(persistence)
        snap = WorkingMemorySnapshot(session_id="sess_1")
        await store.save(snap)
        assert await store.exists("sess_1") is True
        await store.delete("sess_1")
        assert await store.exists("sess_1") is False


class TestEpisodicMemoryStore:
    """EpisodicMemoryStore 测试。"""

    async def test_write_and_recall(self, persistence):
        store = EpisodicMemoryStore(persistence)
        entry = EpisodicMemoryEntry(
            session_id="sess_1", turn_index=0, summary="test"
        )
        await store.write(entry)

        entries = await store.recall_session("sess_1")
        assert len(entries) == 1
        assert entries[0].summary == "test"

    async def test_recall_by_turn_range(self, persistence):
        store = EpisodicMemoryStore(persistence)
        for i in range(5):
            entry = EpisodicMemoryEntry(
                session_id="sess_1", turn_index=i, summary=f"turn_{i}"
            )
            await store.write(entry)

        entries = await store.recall_by_turn_range("sess_1", 1, 3)
        assert len(entries) == 3
        assert [e.turn_index for e in entries] == [1, 2, 3]

    async def test_recall_session_limit(self, persistence):
        store = EpisodicMemoryStore(persistence)
        for i in range(10):
            entry = EpisodicMemoryEntry(
                session_id="sess_1", turn_index=i, summary=f"turn_{i}"
            )
            await store.write(entry)

        entries = await store.recall_session("sess_1", limit=3)
        assert len(entries) == 3
        # 按 turn_index DESC，最近的在前面
        assert entries[0].turn_index == 9

    async def test_count_session(self, persistence):
        store = EpisodicMemoryStore(persistence)
        for i in range(5):
            entry = EpisodicMemoryEntry(
                session_id="sess_1", turn_index=i, summary=f"turn_{i}"
            )
            await store.write(entry)
        assert await store.count_session("sess_1") == 5

    async def test_search_by_entities(self, persistence):
        store = EpisodicMemoryStore(persistence)
        entry1 = EpisodicMemoryEntry(
            session_id="sess_1", user_id="u1", turn_index=0,
            summary="about Python", entities=["python", "code"],
        )
        entry2 = EpisodicMemoryEntry(
            session_id="sess_1", user_id="u1", turn_index=1,
            summary="about Java", entities=["java"],
        )
        await store.write(entry1)
        await store.write(entry2)

        results = await store.search_by_entities("u1", ["python"])
        assert len(results) == 1
        assert "python" in results[0].entities

    async def test_mark_merged(self, persistence):
        store = EpisodicMemoryStore(persistence)
        entry = EpisodicMemoryEntry(
            session_id="sess_1", turn_index=0, summary="original"
        )
        await store.write(entry)
        await store.mark_merged(entry.id, "merged_id")
        entries = await store.recall_session("sess_1")
        assert entries[0].merged_to == "merged_id"

    async def test_recall_user(self, persistence):
        store = EpisodicMemoryStore(persistence)
        e1 = EpisodicMemoryEntry(
            session_id="sess_1", user_id="u1", turn_index=0,
            summary="u1_msg", created_at=datetime.utcnow(),
        )
        e2 = EpisodicMemoryEntry(
            session_id="sess_2", user_id="u1", turn_index=0,
            summary="u1_other", created_at=datetime.utcnow(),
        )
        e3 = EpisodicMemoryEntry(
            session_id="sess_3", user_id="u2", turn_index=0,
            summary="u2_msg", created_at=datetime.utcnow(),
        )
        await store.write(e1)
        await store.write(e2)
        await store.write(e3)

        results = await store.recall_user("u1")
        assert len(results) == 2
        for r in results:
            assert r.user_id == "u1"


class TestEntityMemoryStore:
    """EntityMemoryStore 测试。"""

    async def test_upsert_and_read(self, persistence):
        store = EntityMemoryStore(persistence)
        entry = await store.upsert_attribute(
            "user", "u1", "name", "Alice",
        )
        assert entry.entity_type == "user"
        assert entry.entity_key == "u1"
        assert entry.attributes["name"].value == "Alice"

        loaded = await store.read("user", "u1")
        assert loaded is not None
        assert loaded.attributes["name"].value == "Alice"

    async def test_upsert_multiple(self, persistence):
        store = EntityMemoryStore(persistence)
        await store.upsert_attribute("user", "u1", "name", "Alice")
        await store.upsert_attribute("user", "u1", "age", 30)

        loaded = await store.read("user", "u1")
        assert loaded.attributes["name"].value == "Alice"
        assert loaded.attributes["age"].value == 30

    async def test_overwrite_attribute(self, persistence):
        store = EntityMemoryStore(persistence)
        await store.upsert_attribute("user", "u1", "name", "Alice")
        await store.upsert_attribute("user", "u1", "name", "Bob")

        loaded = await store.read("user", "u1")
        assert loaded.attributes["name"].value == "Bob"
        assert len(loaded.history["name"]) == 2

    async def test_read_nonexistent(self, persistence):
        store = EntityMemoryStore(persistence)
        result = await store.read("user", "nonexistent")
        assert result is None

    async def test_delete_entity(self, persistence):
        store = EntityMemoryStore(persistence)
        await store.upsert_attribute("user", "u1", "name", "Alice")
        await store.delete_entity("user", "u1")
        assert await store.read("user", "u1") is None

    async def test_list_by_type(self, persistence):
        store = EntityMemoryStore(persistence)
        await store.upsert_attribute("user", "u1", "name", "Alice")
        await store.upsert_attribute("user", "u2", "name", "Bob")
        await store.upsert_attribute("project", "p1", "name", "Proj")

        users = await store.list_by_type("user")
        assert len(users) == 2

        projects = await store.list_by_type("project")
        assert len(projects) == 1

    async def test_upsert_attributes_batch(self, persistence):
        store = EntityMemoryStore(persistence)
        entry = await store.upsert_attributes(
            "user", "u1", {"name": "Alice", "age": 30},
        )
        assert entry.attributes["name"].value == "Alice"
        assert entry.attributes["age"].value == 30


class TestSemanticKnowledgeStore:
    """SemanticKnowledgeStore 测试。"""

    async def test_create_and_read_node(self, persistence):
        store = SemanticKnowledgeStore(persistence)
        node = SemanticNode(name="Python", type="concept", description="Language")
        node_id = await store.create_node(node)

        loaded = await store.read_node(node_id)
        assert loaded is not None
        assert loaded.name == "Python"
        assert loaded.description == "Language"

    async def test_find_node_by_name(self, persistence):
        store = SemanticKnowledgeStore(persistence)
        node = SemanticNode(name="Python", type="concept")
        await store.create_node(node)

        found = await store.find_node_by_name("Python")
        assert found is not None
        assert found.name == "Python"

    async def test_create_edge(self, persistence):
        store = SemanticKnowledgeStore(persistence)
        n1 = SemanticNode(name="Python")
        n2 = SemanticNode(name="Django")
        id1 = await store.create_node(n1)
        id2 = await store.create_node(n2)

        edge_id = await store.create_edge(id1, id2, "is_framework")
        assert edge_id is not None

    async def test_get_neighbors(self, persistence):
        store = SemanticKnowledgeStore(persistence)
        n1 = SemanticNode(name="Python")
        n2 = SemanticNode(name="Django")
        n3 = SemanticNode(name="Flask")
        id1 = await store.create_node(n1)
        id2 = await store.create_node(n2)
        id3 = await store.create_node(n3)

        await store.create_edge(id1, id2, "is_framework")
        await store.create_edge(id1, id3, "is_framework")

        neighbors = await store.get_neighbors(id1)
        assert len(neighbors) == 2
        names = {n.name for n, _ in neighbors}
        assert names == {"Django", "Flask"}

    async def test_search_nodes(self, persistence):
        store = SemanticKnowledgeStore(persistence)
        await store.create_node(SemanticNode(
            name="WorkingMemory", description="工作记忆层",
        ))
        await store.create_node(SemanticNode(
            name="EpisodicMemory", description="情景记忆层",
        ))

        results = await store.search_nodes("memory")
        assert len(results) >= 2

    async def test_increment_mention(self, persistence):
        store = SemanticKnowledgeStore(persistence)
        node = SemanticNode(name="Python")
        node_id = await store.create_node(node)

        await store.increment_mention(node_id)
        loaded = await store.read_node(node_id)
        assert loaded.mention_count == 1

        await store.increment_mention(node_id)
        loaded = await store.read_node(node_id)
        assert loaded.mention_count == 2

    async def test_merge_knowledge(self, persistence):
        store = SemanticKnowledgeStore(persistence)
        await store.merge_knowledge([
            ("Python", "is_a", "编程语言"),
            ("Django", "is_framework_of", "Python"),
        ])
        python = await store.find_node_by_name("Python")
        django = await store.find_node_by_name("Django")
        assert python is not None
        assert django is not None

    async def test_find_path(self, persistence):
        store = SemanticKnowledgeStore(persistence)
        n1 = SemanticNode(name="A")
        n2 = SemanticNode(name="B")
        n3 = SemanticNode(name="C")
        id1 = await store.create_node(n1)
        id2 = await store.create_node(n2)
        id3 = await store.create_node(n3)
        await store.create_edge(id1, id2, "to")
        await store.create_edge(id2, id3, "to")

        paths = await store.find_path(id1, id3)
        assert len(paths) >= 1


class TestBehavioralPatternStore:
    """BehavioralPatternStore 测试。"""

    async def test_write_and_read(self, persistence):
        store = BehavioralPatternStore(persistence)
        pattern = BehavioralPattern(
            user_id="u1",
            patterns={"style": {"value": "concise"}},
        )
        await store.write(pattern)

        loaded = await store.read("u1")
        assert loaded is not None
        assert loaded.patterns["style"]["value"] == "concise"

    async def test_read_nonexistent(self, persistence):
        store = BehavioralPatternStore(persistence)
        result = await store.read("nonexistent")
        assert result is None

    async def test_overwrite(self, persistence):
        store = BehavioralPatternStore(persistence)
        p1 = BehavioralPattern(user_id="u1", patterns={"a": 1})
        await store.write(p1)
        p2 = BehavioralPattern(user_id="u1", patterns={"b": 2})
        await store.write(p2)

        loaded = await store.read("u1")
        assert loaded.patterns == {"b": 2}
        assert loaded.version > 1

    async def test_delete(self, persistence):
        store = BehavioralPatternStore(persistence)
        pattern = BehavioralPattern(user_id="u1")
        await store.write(pattern)
        await store.delete("u1")
        assert await store.read("u1") is None
