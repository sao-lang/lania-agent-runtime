"""
Memory 层覆盖率补测。

覆盖 EpisodicMemoryStore / SemanticKnowledgeStore / MemoryService /
MemoryCommitHook / 包惰性导出的未覆盖分支与异常路径。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.memory import MemoryService
from src.memory._backends._sqlite import SQLitePersistence
from src.memory._hooks import MemoryCommitHook
from src.memory._management._gate import MemoryCommitGate
from src.memory._stores import (
    EpisodicMemoryStore,
    SemanticKnowledgeStore,
)
from src.memory._types import (
    BehavioralPattern,
    EpisodicMemoryEntry,
    GateDecision,
    MemorySource,
    SemanticNode,
    StepContext,
    ToolCallRecord,
)


@pytest.fixture
async def episodic() -> EpisodicMemoryStore:
    """创建基于 SQLite 内存后端的情景记忆 Store。"""
    persistence = SQLitePersistence(":memory:")
    store = EpisodicMemoryStore(persistence)
    yield store
    await persistence.close()


@pytest.fixture
async def semantic() -> SemanticKnowledgeStore:
    """创建基于 SQLite 内存后端的语义知识 Store。"""
    persistence = SQLitePersistence(":memory:")
    store = SemanticKnowledgeStore(persistence)
    yield store
    await persistence.close()


def make_entry(
    session_id: str = "s1",
    user_id: str = "u1",
    turn_index: int = 0,
    summary: str = "摘要",
    **kwargs: Any,
) -> EpisodicMemoryEntry:
    """构造情景记忆条目。"""
    if "created_at" not in kwargs:
        kwargs["created_at"] = datetime.now(timezone.utc)
    return EpisodicMemoryEntry(
        session_id=session_id,
        user_id=user_id,
        turn_index=turn_index,
        summary=summary,
        **kwargs,
    )


class TestEpisodicStoreCoverage:
    """EpisodicMemoryStore 未覆盖分支。"""

    async def test_parse_key_invalid(self, episodic: EpisodicMemoryStore) -> None:
        assert episodic._parse_key("ep:only") is None
        assert episodic._parse_key("ep:s1:bad:entry") is None

    async def test_source_roundtrip_with_tool_calls(self, episodic: EpisodicMemoryStore) -> None:
        entry = make_entry(
            source=MemorySource(
                user_message="你好",
                assistant_message="收到",
                tool_calls=[ToolCallRecord(tool_name="search", args={"q": "x"}, result="r")],
            )
        )
        await episodic.write(entry)
        recalled = await episodic.recall_session("s1")
        assert recalled[0].source is not None
        assert recalled[0].source.tool_calls[0].tool_name == "search"

    async def test_write_without_user_id(self, episodic: EpisodicMemoryStore) -> None:
        entry = make_entry(user_id="")
        await episodic.write(entry)
        keys = await episodic._store.list_keys("ep_user:")
        assert keys == []

    async def test_write_batch(self, episodic: EpisodicMemoryStore) -> None:
        ids = await episodic.write_batch([make_entry(), make_entry(turn_index=1)])
        assert len(ids) == 2
        assert await episodic.count_session("s1") == 2

    async def test_recall_user_since_filter(self, episodic: EpisodicMemoryStore) -> None:
        old = make_entry(turn_index=0, created_at=datetime.now(timezone.utc) - timedelta(days=2))
        new = make_entry(turn_index=1)
        await episodic.write(old)
        await episodic.write(new)
        recent = await episodic.recall_user(
            "u1", since=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        assert [e.turn_index for e in recent] == [1]

    async def test_search_by_entities_and_topics(self, episodic: EpisodicMemoryStore) -> None:
        await episodic.write(make_entry(turn_index=0, entities=["python"], importance=0.5))
        await episodic.write(
            make_entry(turn_index=1, entities=["java"], topics=["backend"], importance=0.9)
        )
        matched = await episodic.search_by_entities("u1", ["PYTHON"])
        assert [e.turn_index for e in matched] == [0]
        matched_topics = await episodic.search_by_topics("u1", ["Backend"])
        assert [e.turn_index for e in matched_topics] == [1]

    async def test_recall_by_turn_range(self, episodic: EpisodicMemoryStore) -> None:
        for turn in (0, 1, 2):
            await episodic.write(make_entry(turn_index=turn))
        # 混入非法键，验证解析跳过
        await episodic._store.put("ep:s1:bad:entry", b"{}")
        result = await episodic.recall_by_turn_range("s1", 1, 2)
        assert [e.turn_index for e in result] == [1, 2]

    async def test_mark_merged(self, episodic: EpisodicMemoryStore) -> None:
        e1 = make_entry()
        e2 = make_entry(turn_index=1)
        await episodic.write(e1)
        await episodic.write(e2)
        await episodic.mark_merged(e1.id, e2.id)
        recalled = await episodic.recall_session("s1")
        merged = next(e for e in recalled if e.id == e1.id)
        assert merged.merged_to == e2.id
        # 不存在的条目：静默返回
        await episodic.mark_merged("missing", "x")

    async def test_delete_before(self, episodic: EpisodicMemoryStore) -> None:
        old = datetime.now(timezone.utc) - timedelta(days=2)
        await episodic.write(make_entry(turn_index=0, created_at=old, merged_to="target"))
        await episodic.write(make_entry(turn_index=1, created_at=old))
        await episodic.write(make_entry(turn_index=2, user_id="u2", created_at=old))
        await episodic.write(make_entry(turn_index=3))
        await episodic.delete_before("u1", datetime.now(timezone.utc) - timedelta(days=1))
        remaining = await episodic.recall_session("s1")
        assert {e.turn_index for e in remaining} == {0, 2, 3}


class TestSemanticStoreCoverage:
    """SemanticKnowledgeStore 未覆盖分支。"""

    async def test_create_node_idempotent(self, semantic: SemanticKnowledgeStore) -> None:
        node = SemanticNode(name="Python")
        first = await semantic.create_node(node)
        second = await semantic.create_node(SemanticNode(name="Python"))
        assert first == second

    async def test_find_node_by_name_missing(self, semantic: SemanticKnowledgeStore) -> None:
        assert await semantic.find_node_by_name("不存在") is None

    async def test_search_nodes_scoring(self, semantic: SemanticKnowledgeStore) -> None:
        await semantic.create_node(
            SemanticNode(name="Python", description="编程语言", aliases=["py"])
        )
        await semantic.create_node(
            SemanticNode(name="Java", description="python 相关技术栈", aliases=[])
        )
        await semantic.create_node(SemanticNode(name="Rust", description="", aliases=["python-rs"]))
        result = await semantic.search_nodes("python", top_k=10)
        names = [n.name for n in result]
        # 名称命中优先于描述/别名命中
        assert names[0] == "Python"
        assert "Java" in names
        assert "Rust" in names

    async def test_update_embedding(self, semantic: SemanticKnowledgeStore) -> None:
        node = SemanticNode(name="向量")
        await semantic.create_node(node)
        await semantic.update_embedding(node.id, [0.1, 0.2, 0.3])
        updated = await semantic.read_node(node.id)
        assert updated is not None
        assert updated.embedding_dim == 3

    async def test_increment_mention(self, semantic: SemanticKnowledgeStore) -> None:
        node = SemanticNode(name="话题")
        await semantic.create_node(node)
        await semantic.increment_mention(node.id)
        await semantic.increment_mention(node.id)
        updated = await semantic.read_node(node.id)
        assert updated is not None
        assert updated.mention_count == 2
        assert updated.last_seen_at is not None

    async def test_create_edge_duplicate(self, semantic: SemanticKnowledgeStore) -> None:
        a = SemanticNode(name="a")
        b = SemanticNode(name="b")
        await semantic.create_node(a)
        await semantic.create_node(b)
        first = await semantic.create_edge(a.id, b.id, "knows")
        second = await semantic.create_edge(a.id, b.id, "knows")
        assert first == second

    async def test_get_neighbors_depth_and_relation(self, semantic: SemanticKnowledgeStore) -> None:
        a = SemanticNode(name="a")
        b = SemanticNode(name="b")
        c = SemanticNode(name="c")
        for node in (a, b, c):
            await semantic.create_node(node)
        await semantic.create_edge(a.id, b.id, "knows")
        await semantic.create_edge(b.id, c.id, "knows")
        await semantic.create_edge(a.id, c.id, "likes")
        neighbors = await semantic.get_neighbors(a.id, relation="knows", max_depth=2)
        names = {n.name for n, _ in neighbors}
        assert names == {"b", "c"}

    async def test_find_path(self, semantic: SemanticKnowledgeStore) -> None:
        a = SemanticNode(name="a")
        b = SemanticNode(name="b")
        c = SemanticNode(name="c")
        for node in (a, b, c):
            await semantic.create_node(node)
        await semantic.create_edge(a.id, b.id, "knows")
        await semantic.create_edge(b.id, c.id, "knows")
        paths = await semantic.find_path(a.id, c.id, max_depth=3)
        assert len(paths) == 1
        assert paths[0][-1] == (c.id, "knows")
        self_path = await semantic.find_path(a.id, a.id)
        assert self_path == [[(a.id, "")]]

    async def test_merge_knowledge(self, semantic: SemanticKnowledgeStore) -> None:
        await semantic.merge_knowledge([("Python", "has_attribute", "动态类型")])
        node = await semantic.find_node_by_name("Python")
        assert node is not None
        assert await semantic.find_node_by_name("动态类型") is not None

    async def test_get_low_mention_nodes(self, semantic: SemanticKnowledgeStore) -> None:
        low = SemanticNode(name="低提及")
        high = SemanticNode(name="高提及", mention_count=10)
        await semantic.create_node(low)
        await semantic.create_node(high)
        result = await semantic.get_low_mention_nodes(threshold=3)
        assert [n.name for n in result] == ["低提及"]

    async def test_delete_node_removes_edges(self, semantic: SemanticKnowledgeStore) -> None:
        a = SemanticNode(name="a")
        b = SemanticNode(name="b")
        await semantic.create_node(a)
        await semantic.create_node(b)
        await semantic.create_edge(a.id, b.id, "knows")
        await semantic.delete_node(a.id)
        assert await semantic.read_node(a.id) is None
        assert await semantic.get_neighbors(b.id) == []


class AlwaysGate(MemoryCommitGate):
    """始终放行的门控替身。"""

    async def evaluate(
        self, user_message: str | None, assistant_message: str | None
    ) -> GateDecision:
        return GateDecision(importance=0.9, should_record=True, reason="test")


class TestMemoryServiceCoverage:
    """MemoryService 未覆盖分支。"""

    async def test_default_persistence_creation(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        memory = MemoryService()
        try:
            assert memory._store is not None
            assert memory._store._db_path.endswith("memory.db")
        finally:
            await memory.close()

    async def test_recall_with_user_profile_and_tone(self) -> None:
        memory = MemoryService(SQLitePersistence(":memory:"))
        try:
            await memory.pattern.write(
                BehavioralPattern(
                    user_id="u1",
                    patterns={"communication_style": {"value": "简洁"}},
                )
            )
            await memory.entity.upsert_attribute("user", "u1", "name", "张三", source_session="s1")
            result = await memory.recall("s1", "u1", "你好")
            assert "简洁" in result["tone_instruction"]
            assert result["entity_profile"]["name"] == "张三"
        finally:
            await memory.close()

    async def test_recall_raw_turn_ranges_and_query(self) -> None:
        memory = MemoryService(SQLitePersistence(":memory:"))
        try:
            await memory.episodic.write(make_entry(turn_index=0))
            await memory.episodic.write(make_entry(turn_index=1))
            ranged = await memory.recall_raw("s1", turn_ranges=[(0, 0)])
            assert [e.turn_index for e in ranged.episodic_memories] == [0]

            node = SemanticNode(name="Python", description="编程语言")
            await memory.semantic.create_node(node)
            queried = await memory.recall_raw("s1", query="python")
            assert any(c["name"] == "Python" for c in queried.concepts)
        finally:
            await memory.close()

    async def test_commit_with_entities_triggers_pipeline(self) -> None:
        memory = MemoryService(SQLitePersistence(":memory:"))
        try:
            step_ctx = StepContext(
                user_message="学习 Python",
                assistant_message="好的",
                turn_index=0,
                session_id="s1",
                user_id="u1",
                importance=0.8,
                summary="学习 Python",
                entities_detected=["python"],
            )
            await memory.commit("s1", "u1", step_ctx)
            await memory._bg_tasks.shutdown(wait=True)
            await memory._bg_tasks.shutdown(wait=True)  # 排干嵌套语义任务
            entity = await memory.entity.read("user", "u1")
            assert entity is not None
            assert await memory.semantic.find_node_by_name("python") is not None
        finally:
            await memory.close()

    async def test_discard_and_restore_missing(self) -> None:
        memory = MemoryService(SQLitePersistence(":memory:"))
        try:
            assert await memory.restore("nope") is None
            await memory.discard_checkpoint("nope")  # 静默
        finally:
            await memory.close()

    async def test_async_context_manager(self) -> None:
        async with MemoryService(SQLitePersistence(":memory:")) as memory:
            assert memory is not None
        # 退出后 close 已调用（后端关闭幂等）


class TestMemoryCommitHookCoverage:
    """MemoryCommitHook 未覆盖分支。"""

    async def test_empty_messages_skips(self) -> None:
        memory = AsyncMock()
        hook = MemoryCommitHook(memory)
        ctx = MagicMockCtx(messages=[])
        await hook({}, ctx)
        memory.commit.assert_not_called()

    async def test_commits_with_gate_allow(self) -> None:
        memory = AsyncMock()
        hook = MemoryCommitHook(memory, gate=AlwaysGate())
        ctx = MagicMockCtx(messages=[{"role": "user", "content": "hi"}])
        await hook({}, ctx)
        memory.commit.assert_called_once()

    async def test_commit_error_silent(self) -> None:
        memory = AsyncMock()
        memory.commit = AsyncMock(side_effect=RuntimeError("boom"))
        hook = MemoryCommitHook(memory, gate=AlwaysGate())
        ctx = MagicMockCtx(messages=[{"role": "user", "content": "hi"}])
        result = await hook({}, ctx)
        assert result == {}


class MagicMockCtx:
    """极简 ctx 替身。"""

    def __init__(self, messages: list) -> None:
        self.messages = tuple(messages)
        self.services = {"user_id": "u1"}
        self.step_index = 1
        self.session_id = "s1"


class TestPackageLazyExports:
    """memory 包惰性导出。"""

    def test_lazy_imports(self) -> None:
        import src.memory as memory_pkg

        assert memory_pkg.MemoryService is MemoryService
        assert memory_pkg.WorkingMemorySnapshot is not None
        assert memory_pkg.StepContext is StepContext

    def test_unknown_attribute_raises(self) -> None:
        import src.memory as memory_pkg

        with pytest.raises(AttributeError):
            memory_pkg.NonExistent  # noqa: B018
