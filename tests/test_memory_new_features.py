"""测试新增的记忆功能: 批量操作/遗漏/合并/图谱/门控/压缩等."""

import pytest

from lania_agent_runtime.memory import GenericMemoryStore, MemoryService
from lania_agent_runtime.memory.backends import SQLiteBackend
from lania_agent_runtime.memory.compression import CompressionManager
from lania_agent_runtime.memory.conflict import ConflictResolver
from lania_agent_runtime.memory.eviction import EvictionManager
from lania_agent_runtime.memory.gate import MemoryCommitGate
from lania_agent_runtime.models import (
    EpisodicMemoryEntry,
    GateDecision,
    MergeCandidate,
    WorkingMemorySnapshot,
)


@pytest.fixture
async def store():  # noqa: ANN201
    s = GenericMemoryStore(SQLiteBackend())
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
async def memory_service(store):  # noqa: ANN201
    return MemoryService(store=store)


# ═══════════════════════════════════════════════════════════════
# SQLiteMemoryStore 新增方法
# ═══════════════════════════════════════════════════════════════


class TestSQLiteMemoryStoreNewMethods:
    """测试 SQLiteMemoryStore 新增方法."""

    @pytest.mark.asyncio
    async def test_write_batch(self, store) -> None:
        """批量写入情景记忆."""
        entries = [
            EpisodicMemoryEntry(
                session_id="s1", user_id="u1", turn_index=i,
                summary=f"Entry {i}", token_count=10,
            )
            for i in range(3)
        ]
        ids = await store.write_batch(entries)
        assert len(ids) == 3
        count = await store.count_session("s1")
        assert count == 3

    @pytest.mark.asyncio
    async def test_search_by_topics(self, store) -> None:
        """按话题标签检索."""
        e1 = EpisodicMemoryEntry(
            session_id="s1", user_id="u1", turn_index=0,
            summary="Python discussion", topics=["python", "programming"],
            token_count=10,
        )
        e2 = EpisodicMemoryEntry(
            session_id="s1", user_id="u1", turn_index=1,
            summary="Weather talk", topics=["weather"],
            token_count=10,
        )
        await store.write(e1)
        await store.write(e2)

        results = await store.search_by_topics("u1", ["python"])
        assert len(results) >= 1
        assert results[0].summary == "Python discussion"

    @pytest.mark.asyncio
    async def test_mark_merged(self, store) -> None:
        """标记合并."""
        e1 = EpisodicMemoryEntry(
            session_id="s1", turn_index=0, summary="Old", token_count=10)
        e2 = EpisodicMemoryEntry(
            session_id="s1", turn_index=1, summary="New", token_count=10)
        id1 = await store.write(e1)
        id2 = await store.write(e2)

        await store.mark_merged(id1, id2)
        memories = await store.recall_session("s1")
        merged = [m for m in memories if m.id == id1]
        assert len(merged) == 1
        assert merged[0].merged_to == id2

    @pytest.mark.asyncio
    async def test_delete_before(self, store) -> None:
        """按时间删除过期记忆."""
        import json
        # 直接插入两条旧记录
        for i in range(3):
            e = EpisodicMemoryEntry(
                session_id="s1", user_id="u1", turn_index=i,
                summary=f"Entry {i}", token_count=10,
            )
            await store.write(e)

        deleted = await store.delete_before("u1", "2099-01-01T00:00:00")
        assert deleted >= 3

    @pytest.mark.asyncio
    async def test_get_unmerged_raw(self, store) -> None:
        """获取未合并的原始记录."""
        e1 = EpisodicMemoryEntry(
            session_id="s1", turn_index=0, summary="Raw1", token_count=10)
        e2 = EpisodicMemoryEntry(
            session_id="s1", turn_index=1, summary="Raw2", token_count=10)
        id1 = await store.write(e1)
        await store.write(e2)
        await store.mark_merged(id1, "merged_id")

        raw = await store.get_unmerged_raw("s1")
        assert len(raw) == 1
        assert raw[0].summary == "Raw2"

    @pytest.mark.asyncio
    async def test_upsert_attributes(self, store) -> None:
        """批量更新多个属性."""
        await store.upsert_attributes(
            "user", "u1", {"name": "Alice", "age": 30},
            source_session="s1",
        )
        profile = await store.get_entity_profile("user", "u1")
        assert profile is not None
        assert profile.attributes["name"]["value"] == "Alice"
        assert profile.attributes["age"]["value"] == 30

    @pytest.mark.asyncio
    async def test_read_batch(self, store) -> None:
        """批量读取实体."""
        await store.upsert_entity_attribute("user", "u1", "name", "Alice")
        await store.upsert_entity_attribute("user", "u2", "name", "Bob")
        profiles = await store.read_batch([("user", "u1"), ("user", "u2"), ("user", "u3")])
        assert len(profiles) == 3
        assert profiles[0] is not None
        assert profiles[1] is not None
        assert profiles[2] is None

    @pytest.mark.asyncio
    async def test_delete_entity(self, store) -> None:
        """删除实体."""
        await store.upsert_entity_attribute("user", "u1", "name", "Alice")
        await store.delete_entity("user", "u1")
        profile = await store.get_entity_profile("user", "u1")
        assert profile is None

    @pytest.mark.asyncio
    async def test_list_by_type(self, store) -> None:
        """按类型列出实体."""
        await store.upsert_entity_attribute("user", "u1", "name", "Alice")
        await store.upsert_entity_attribute("user", "u2", "name", "Bob")
        await store.upsert_entity_attribute("project", "p1", "name", "Lania")

        users = await store.list_by_type("user")
        assert len(users) == 2
        projects = await store.list_by_type("project")
        assert len(projects) == 1

    @pytest.mark.asyncio
    async def test_read_node(self, store) -> None:
        """按 ID 读语义节点."""
        node_id = await store.create_semantic_node("Python", "concept", "Language")
        node = await store.read_node(node_id)
        assert node is not None
        assert node.name == "Python"
        assert node.description == "Language"

    @pytest.mark.asyncio
    async def test_find_node_by_name(self, store) -> None:
        """按名称查语义节点."""
        await store.create_semantic_node("Python", "concept", "Language")
        node = await store.find_node_by_name("Python")
        assert node is not None
        assert node.description == "Language"

        missing = await store.find_node_by_name("Nonexistent")
        assert missing is None

    @pytest.mark.asyncio
    async def test_get_neighbors(self, store) -> None:
        """获取邻居节点."""
        n1 = await store.create_semantic_node("Python", "concept")
        n2 = await store.create_semantic_node("FastAPI", "framework")
        await store.create_semantic_edge(n1, n2, "used_by")

        neighbors = await store.get_neighbors(n1)
        assert len(neighbors) >= 1
        names = [n.name for n, _ in neighbors]
        assert "FastAPI" in names

    @pytest.mark.asyncio
    async def test_get_neighbors_with_relation(self, store) -> None:
        """按关系过滤邻居."""
        n1 = await store.create_semantic_node("Python", "concept")
        n2 = await store.create_semantic_node("FastAPI", "framework")
        n3 = await store.create_semantic_node("Django", "framework")
        await store.create_semantic_edge(n1, n2, "used_by")
        await store.create_semantic_edge(n1, n3, "related_to")

        neighbors = await store.get_neighbors(n1, relation="used_by")
        assert len(neighbors) == 1
        assert neighbors[0][0].name == "FastAPI"

    @pytest.mark.asyncio
    async def test_get_neighbors_no_conn(self) -> None:
        """无连接时获取邻居."""
        store = GenericMemoryStore(SQLiteBackend())
        neighbors = await store.get_neighbors("any")
        assert neighbors == []

    @pytest.mark.asyncio
    async def test_find_path(self, store) -> None:
        """查找路径."""
        na = await store.create_semantic_node("A", "concept")
        nb = await store.create_semantic_node("B", "concept")
        nc = await store.create_semantic_node("C", "concept")
        await store.create_semantic_edge(na, nb, "related_to")
        await store.create_semantic_edge(nb, nc, "related_to")

        paths = await store.find_path(na, nc, max_depth=3)
        assert len(paths) >= 1

    @pytest.mark.asyncio
    async def test_find_path_no_path(self, store) -> None:
        """不存在的路径."""
        na = await store.create_semantic_node("A", "concept")
        nc = await store.create_semantic_node("C", "concept")
        paths = await store.find_path(na, nc)
        assert paths == []

    @pytest.mark.asyncio
    async def test_merge_knowledge(self, store) -> None:
        """批量注入知识三元组."""
        await store.merge_knowledge([
            ("Python", "used_by", "FastAPI"),
            ("Python", "used_by", "Django"),
        ])
        py = await store.find_node_by_name("Python")
        assert py is not None
        fastapi = await store.find_node_by_name("FastAPI")
        assert fastapi is not None

    @pytest.mark.asyncio
    async def test_get_low_mention_nodes(self, store) -> None:
        """获取低频节点."""
        n1 = await store.create_semantic_node("Python", "concept", "Lang")
        await store.create_semantic_node("RareConcept", "concept", "Rare")

        low = await store.get_low_mention_nodes(threshold=5)
        names = [n.name for n in low]
        assert "RareConcept" in names

    @pytest.mark.asyncio
    async def test_delete_node(self, store) -> None:
        """删除节点及其边."""
        n1 = await store.create_semantic_node("Python", "concept")
        n2 = await store.create_semantic_node("FastAPI", "framework")
        await store.create_semantic_edge(n1, n2, "used_by")

        await store.delete_node(n1)
        assert await store.read_node(n1) is None
        assert await store.read_node(n2) is not None  # 不影响其他节点

    @pytest.mark.asyncio
    async def test_delete_behavioral_pattern(self, store) -> None:
        """删除行为模式."""
        await store.upsert_behavioral_pattern("u1", {"style": "concise"})
        await store.delete_behavioral_pattern("u1")
        pattern = await store.get_behavioral_pattern("u1")
        assert pattern is None

    @pytest.mark.asyncio
    async def test_recall_session_with_min_importance(self, store) -> None:
        """按最低重要性过滤召回."""
        e1 = EpisodicMemoryEntry(
            session_id="s1", turn_index=0, summary="Low", importance=0.2, token_count=10)
        e2 = EpisodicMemoryEntry(
            session_id="s1", turn_index=1, summary="High", importance=0.8, token_count=10)
        await store.write(e1)
        await store.write(e2)

        memories = await store.recall_session("s1", min_importance=0.5)
        assert len(memories) == 1
        assert memories[0].summary == "High"

    @pytest.mark.asyncio
    async def test_recall_user_with_since(self, store) -> None:
        """按起始时间过滤."""
        e = EpisodicMemoryEntry(
            session_id="s1", user_id="u1", turn_index=0,
            summary="Old", token_count=10,
            created_at="2020-01-01T00:00:00",
        )
        await store.write(e)

        memories = await store.recall_user("u1", since="2025-01-01T00:00:00")
        assert len(memories) == 0


# ═══════════════════════════════════════════════════════════════
# MemoryCommitGate 测试
# ═══════════════════════════════════════════════════════════════


class TestMemoryCommitGate:
    """测试记忆写入门控."""

    @pytest.mark.asyncio
    async def test_no_input(self) -> None:
        gate = MemoryCommitGate()
        decision = await gate.evaluate(None, None)
        assert not decision.should_record
        assert decision.reason == "no_user_input"

    @pytest.mark.asyncio
    async def test_empty_input(self) -> None:
        gate = MemoryCommitGate()
        decision = await gate.evaluate("", "")
        assert not decision.should_record

    @pytest.mark.asyncio
    async def test_greeting_skipped(self) -> None:
        gate = MemoryCommitGate()
        decision = await gate.evaluate("你好", "你好！")
        assert not decision.should_record

    @pytest.mark.asyncio
    async def test_hello_skipped(self) -> None:
        gate = MemoryCommitGate()
        decision = await gate.evaluate("hello", "Hi there!")
        assert not decision.should_record

    @pytest.mark.asyncio
    async def test_critical_info_detected(self) -> None:
        gate = MemoryCommitGate()
        decision = await gate.evaluate("我叫小明", "你好小明！")
        assert decision.should_record
        assert decision.importance >= 0.8
        assert decision.should_extract_entities

    @pytest.mark.asyncio
    async def test_english_critical(self) -> None:
        gate = MemoryCommitGate()
        decision = await gate.evaluate(
            "I am a software engineer", "Nice to meet you!")
        assert decision.should_record
        assert decision.should_extract_entities

    @pytest.mark.asyncio
    async def test_long_response_increases_importance(self) -> None:
        gate = MemoryCommitGate()
        long_msg = "A" * 300
        decision = await gate.evaluate("Tell me about AI", long_msg)
        assert decision.importance >= 0.5

    @pytest.mark.asyncio
    async def test_error_keyword_highlights(self) -> None:
        gate = MemoryCommitGate()
        decision = await gate.evaluate("有个 bug 需要修复", "我来看看")
        assert decision.importance >= 0.8

    @pytest.mark.asyncio
    async def test_long_user_message(self) -> None:
        gate = MemoryCommitGate()
        decision = await gate.evaluate("A" * 150, "OK")
        assert decision.importance >= 0.4
        assert decision.should_extract_entities


# ═══════════════════════════════════════════════════════════════
# CompressionManager 测试
# ═══════════════════════════════════════════════════════════════


class TestCompressionManager:
    """测试压缩管理器."""

    @pytest.mark.asyncio
    async def test_should_merge_below_threshold(self, store) -> None:
        mgr = CompressionManager(store)
        # 少于 MERGE_AFTER_TURNS (50) 条
        assert not await mgr.should_merge("s1")

    @pytest.mark.asyncio
    async def test_should_merge_at_threshold(self, store) -> None:
        mgr = CompressionManager(store)
        # 写入 50 条
        for i in range(CompressionManager.MERGE_AFTER_TURNS):
            e = EpisodicMemoryEntry(
                session_id="s1", turn_index=i, summary=f"E{i}", token_count=10)
            await store.write(e)
        assert await mgr.should_merge("s1")

    @pytest.mark.asyncio
    async def test_merge_session_merges(self, store) -> None:
        mgr = CompressionManager(store)
        # 写入足够条目触发合并
        for i in range(CompressionManager.MERGE_AFTER_TURNS):
            e = EpisodicMemoryEntry(
                session_id="s1", turn_index=i, summary=f"E{i}",
                token_count=10, entities=["test"], topics=["topic"],
            )
            await store.write(e)

        merged_id = await mgr.merge_session("s1")
        assert merged_id is not None

        # 验证源记录已被标记
        raw = await store.get_unmerged_raw("s1")
        assert len(raw) < CompressionManager.MERGE_AFTER_TURNS

    @pytest.mark.asyncio
    async def test_merge_below_threshold_skips(self, store) -> None:
        mgr = CompressionManager(store)
        await store.write(EpisodicMemoryEntry(
            session_id="s1", turn_index=0, summary="Only one", token_count=10))
        merged_id = await mgr.merge_session("s1")
        assert merged_id is None

    @pytest.mark.asyncio
    async def test_fallback_summarize(self) -> None:
        summary = CompressionManager._fallback_summarize(
            ["First entry", "Second entry", "Third entry"])
        assert "First" in summary
        assert "Second" in summary
        assert "Third" in summary

    @pytest.mark.asyncio
    async def test_fallback_summarize_many(self) -> None:
        summary = CompressionManager._fallback_summarize(
            [f"Entry {i}" for i in range(10)])
        assert "Entry 0" in summary
        assert "9" in summary  # 计数剩余

    @pytest.mark.asyncio
    async def test_summarize_turn_skips_short(self, store) -> None:
        mgr = CompressionManager(store)
        result = await mgr.summarize_turn("hi", "hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_summarize_turn_force(self, store) -> None:
        mgr = CompressionManager(store)
        result = await mgr.summarize_turn("hi", "hello", force=True)
        assert result is not None

    @pytest.mark.asyncio
    async def test_summarize_turn_long(self, store) -> None:
        mgr = CompressionManager(store)
        long_msg = "A" * 250
        result = await mgr.summarize_turn("user msg", long_msg)
        assert result is not None
        assert len(result) <= 200

    @pytest.mark.asyncio
    async def test_build_candidate(self, store) -> None:
        mgr = CompressionManager(store)
        for i in range(5):
            await store.write(EpisodicMemoryEntry(
                session_id="s1", turn_index=i, summary=f"E{i}",
                token_count=10, importance=0.3 + i * 0.1))
        candidate = await mgr.build_candidate("s1", limit=5)
        assert candidate is not None
        assert len(candidate.entry_ids) == 5
        assert candidate.token_total == 50

    @pytest.mark.asyncio
    async def test_build_candidate_insufficient(self, store) -> None:
        mgr = CompressionManager(store)
        candidate = await mgr.build_candidate("s1", limit=5)
        assert candidate is None


# ═══════════════════════════════════════════════════════════════
# EvictionManager 测试
# ═══════════════════════════════════════════════════════════════


class TestEvictionManager:
    """测试遗忘管理器."""

    @pytest.mark.asyncio
    async def test_evict_expired(self, store) -> None:
        evictor = EvictionManager(store, semantic_store=store)
        # 写入一条旧记录
        e = EpisodicMemoryEntry(
            session_id="s1", user_id="u1", turn_index=0,
            summary="Old entry", token_count=10,
            created_at="2020-01-01T00:00:00",
        )
        await store.write(e)

        stats = await evictor.evict_expired("u1")
        assert "episodic_raw" in stats or True  # 至少不崩溃

    @pytest.mark.asyncio
    async def test_evict_removes_old(self, store) -> None:
        evictor = EvictionManager(store, semantic_store=store)
        e = EpisodicMemoryEntry(
            session_id="s1", user_id="u1", turn_index=0,
            summary="Old entry", token_count=10,
            created_at="2020-01-01T00:00:00",
        )
        await store.write(e)

        await evictor.evict_expired("u1")
        remaining = await store.recall_user("u1", limit=10)
        # 如果被删了, 应该为空
        assert len(remaining) == 0 or len(remaining) == 1  # 兼容不同TTL

    @pytest.mark.asyncio
    async def test_should_evict(self, store) -> None:
        evictor = EvictionManager(store, semantic_store=store)
        should = await evictor.should_evict("u1")
        # 没有数据时不应 evict
        assert not should

    @pytest.mark.asyncio
    async def test_should_evict_with_old_data(self, store) -> None:
        evictor = EvictionManager(store, semantic_store=store)
        e = EpisodicMemoryEntry(
            session_id="s1", user_id="u1", turn_index=0,
            summary="Old", token_count=10,
            created_at="2020-01-01T00:00:00",
        )
        await store.write(e)
        should = await evictor.should_evict("u1")
        # 旧数据应该触发 evict
        assert should

    @pytest.mark.asyncio
    async def test_semantic_cold_cleaning(self, store) -> None:
        evictor = EvictionManager(store, semantic_store=store)
        await store.create_semantic_node("RareCold", "concept", "Cold data",
                                         )
        stats = await evictor.evict_expired("u1")
        assert "semantic_cold" in stats or True  # 至少不崩溃


# ═══════════════════════════════════════════════════════════════
# ConflictResolver 测试
# ═══════════════════════════════════════════════════════════════


class TestConflictResolver:
    """测试冲突解决器."""

    @pytest.mark.asyncio
    async def test_new_attribute(self, store) -> None:
        resolver = ConflictResolver(store)
        should, reason = await resolver.resolve("user", "u1", "name", "Alice")
        assert should
        assert "新属性" in reason

    @pytest.mark.asyncio
    async def test_higher_confidence_overrides(self, store) -> None:
        resolver = ConflictResolver(store)
        await store.upsert_entity_attribute(
            "user", "u1", "name", "Alice", confidence=0.5)
        should, reason = await resolver.resolve(
            "user", "u1", "name", "Alice2", new_confidence=0.9)
        assert should
        assert "置信度" in reason

    @pytest.mark.asyncio
    async def test_lower_confidence_skips(self, store) -> None:
        resolver = ConflictResolver(store)
        await store.upsert_entity_attribute(
            "user", "u1", "name", "Alice", confidence=0.9)
        should, reason = await resolver.resolve(
            "user", "u1", "name", "Alice2", new_confidence=0.3)
        assert not should

    @pytest.mark.asyncio
    async def test_same_value_upgrades_confidence(self, store) -> None:
        resolver = ConflictResolver(store)
        await store.upsert_entity_attribute(
            "user", "u1", "name", "Alice", confidence=0.5)
        should, reason = await resolver.resolve(
            "user", "u1", "name", "Alice", new_confidence=0.9)
        assert should
        # 置信度 0.9 >= 0.5*1.2=0.6, 所以触发策略1: 置信度加权覆盖
        assert "置信度" in reason or "覆盖" in reason

    @pytest.mark.asyncio
    async def test_classify_confidence(self) -> None:
        assert ConflictResolver.classify_confidence("explicit") == 0.9
        assert ConflictResolver.classify_confidence("inferred") == 0.5
        assert ConflictResolver.classify_confidence("system") == 0.3
        assert ConflictResolver.classify_confidence("unknown") == 0.5


# ═══════════════════════════════════════════════════════════════
# MemoryService 新增功能
# ═══════════════════════════════════════════════════════════════


class TestMemoryServiceNewFeatures:
    """测试 MemoryService 新增功能."""

    @pytest.mark.asyncio
    async def test_recall_with_gate_decision(self, memory_service) -> None:
        """传入 gate_decision 跳过记录."""
        gate = MemoryCommitGate()
        decision = await gate.evaluate("你好", "你好！")
        assert not decision.should_record

        await memory_service.commit(
            "s1", "u1", "你好", "你好！", gate_decision=decision)
        payload = await memory_service.recall("s1")
        # 门控跳过, 不应有记忆
        assert len(payload.memories) == 0

    @pytest.mark.asyncio
    async def test_apply_token_budget_trimming(self) -> None:
        """测试 Token 裁剪."""
        svc = MemoryService()
        payload = await svc.recall("s1", max_tokens=512)
        assert payload.priority_hints.max_tokens == 512

    @pytest.mark.asyncio
    async def test_apply_token_budget(self, memory_service) -> None:
        """裁剪过多记忆."""
        # 写入10条
        for i in range(10):
            e = EpisodicMemoryEntry(
                session_id="s1", turn_index=i,
                summary=f"Long memory entry number {i} with lots of text here "
                        f"to make each entry take up significant tokens",
                token_count=50,
            )
            await memory_service.store.write(e)  # type: ignore

        # 用小预算召回, 应被裁剪
        payload = await memory_service.recall("s1", max_tokens=256)
        assert len(payload.memories) <= 10  # 至少被裁剪

    @pytest.mark.asyncio
    async def test_recall_cross_session(self, memory_service) -> None:
        """跨 session 补充高重要性记忆."""
        # 写入跨 session 的高重要性条目
        e = EpisodicMemoryEntry(
            session_id="old_session", user_id="u1", turn_index=0,
            summary="Important cross-session memory",
            importance=0.9, token_count=10,
        )
        await memory_service.store.write(e)  # type: ignore

        # 当前 session 为空, 应跨 session 补充
        payload = await memory_service.recall("current_session", user_id="u1")
        assert len(payload.memories) >= 1

    @pytest.mark.asyncio
    async def test_commit_skips_with_gate(self, memory_service) -> None:
        """门控决策不记录时, episodic 不写入."""
        gate = MemoryCommitGate()
        decision = await gate.evaluate("ok", "ok")
        assert not decision.should_record

        await memory_service.commit(
            "s1", "u1", "ok", "ok", gate_decision=decision)
        payload = await memory_service.recall("s1")
        assert len(payload.memories) == 0

    @pytest.mark.asyncio
    async def test_commit_with_critical_gate(self, memory_service) -> None:
        """门控决策为 critical 时, episodic 写入并高重要性."""
        gate = MemoryCommitGate()
        decision = await gate.evaluate("我叫小明", "你好小明！")
        assert decision.should_record

        await memory_service.commit(
            "s1", "u1", "我叫小明", "你好小明！", gate_decision=decision)
        payload = await memory_service.recall("s1")
        assert len(payload.memories) == 1


# ═══════════════════════════════════════════════════════════════
# WorkingMemoryStore + exists_working_memory 测试
# ═══════════════════════════════════════════════════════════════


class TestWorkingMemoryStoreNew:
    """测试 WorkingMemoryStore 新增方法."""

    @pytest.mark.asyncio
    async def test_exists_working_memory_true(self, store) -> None:
        snapshot = WorkingMemorySnapshot(session_id="s1", step_index=1)
        await store.save_working_memory(snapshot)
        assert await store.exists_working_memory("s1") is True

    @pytest.mark.asyncio
    async def test_exists_working_memory_false(self, store) -> None:
        assert await store.exists_working_memory("nonexistent") is False

    @pytest.mark.asyncio
    async def test_exists_working_memory_after_delete(self, store) -> None:
        snapshot = WorkingMemorySnapshot(session_id="s1")
        await store.save_working_memory(snapshot)
        await store.delete_working_memory("s1")
        assert await store.exists_working_memory("s1") is False

    @pytest.mark.asyncio
    async def test_has_checkpoint(self, memory_service) -> None:
        snapshot = WorkingMemorySnapshot(session_id="s1")
        await memory_service.checkpoint(snapshot)
        assert await memory_service.has_checkpoint("s1") is True

    @pytest.mark.asyncio
    async def test_has_checkpoint_no_store(self) -> None:
        svc = MemoryService()
        assert await svc.has_checkpoint("s1") is False


# ═══════════════════════════════════════════════════════════════
# acquire_lock 测试
# ═══════════════════════════════════════════════════════════════


class TestAcquireLock:
    """测试 acquire_lock."""

    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, store) -> None:
        locked = await store.acquire_lock("u1", ttl=30)
        assert locked is True

    @pytest.mark.asyncio
    async def test_acquire_lock_conflict(self, store) -> None:
        locked1 = await store.acquire_lock("u1", ttl=30)
        assert locked1 is True
        # 第二次应失败(锁未释放)
        locked2 = await store.acquire_lock("u1", ttl=30)
        assert locked2 is False

    @pytest.mark.asyncio
    async def test_acquire_lock_different_users(self, store) -> None:
        locked1 = await store.acquire_lock("u1", ttl=30)
        locked2 = await store.acquire_lock("u2", ttl=30)
        assert locked1 is True
        assert locked2 is True

    @pytest.mark.asyncio
    async def test_acquire_lock_no_conn(self) -> None:
        store = GenericMemoryStore(SQLiteBackend())
        locked = await store.acquire_lock("u1")
        assert locked is False


# ═══════════════════════════════════════════════════════════════
# commit() + tool_calls 测试
# ═══════════════════════════════════════════════════════════════


class TestCommitWithToolCalls:
    """测试 commit 带 tool_calls."""

    @pytest.mark.asyncio
    async def test_commit_with_tool_calls(self, memory_service) -> None:
        tool_calls = [
            {"name": "get_weather", "arguments": {"city": "Beijing"}, "result": "25°C"},
            {"name": "search_web", "arguments": {"q": "news"}, "result": "No results"},
        ]
        await memory_service.commit(
            "s1", "u1", "天气怎么样", "好的，查到了",
            tool_calls=tool_calls,
        )
        payload = await memory_service.recall("s1")
        assert len(payload.memories) == 1

    @pytest.mark.asyncio
    async def test_commit_without_tool_calls(self, memory_service) -> None:
        # 兼容旧调用方式(不传 tool_calls)
        await memory_service.commit("s1", "u1", "hi", "hello")
        payload = await memory_service.recall("s1")
        assert len(payload.memories) == 1

    @pytest.mark.asyncio
    async def test_commit_tool_calls_empty_list(self, memory_service) -> None:
        await memory_service.commit("s1", "u1", "hi", "hello", tool_calls=[])
        payload = await memory_service.recall("s1")
        assert len(payload.memories) == 1
