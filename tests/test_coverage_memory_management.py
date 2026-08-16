"""
Memory 管理与工具调度覆盖率补测。

覆盖 ConflictResolver / EvictionManager / CompressionManager / BaseStore /
EntityMemoryStore / MemoryCommitHook / MemoryService 分支、ToolDispatcher
路由与异常路径、Builder 的 MCP/Skills 接线。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.memory import MemoryService
from src.memory._backends._sqlite import SQLitePersistence
from src.memory._hooks import MemoryCommitHook
from src.memory._management._compressor import CompressionManager
from src.memory._management._conflict import ConflictResolver
from src.memory._management._eviction import EvictionManager
from src.memory._management._gate import MemoryCommitGate
from src.memory._stores import (
    EntityMemoryStore,
    EpisodicMemoryStore,
    SemanticKnowledgeStore,
)
from src.memory._types import (
    EntityAttributeValue,
    EpisodicMemoryEntry,
    GateDecision,
    SemanticNode,
    StepContext,
)
from src.runtime._runtime import AgentRuntime
from src.tools import ToolDispatcher, ToolRegistry
from src.tools._spec import ToolSpec


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


@pytest.fixture
async def entity() -> EntityMemoryStore:
    """创建基于 SQLite 内存后端的实体 Store。"""
    persistence = SQLitePersistence(":memory:")
    store = EntityMemoryStore(persistence)
    yield store
    await persistence.close()


class TestConflictResolver:
    """ConflictResolver 未覆盖分支。"""

    async def test_new_attr_direct_write(self, entity: EntityMemoryStore) -> None:
        resolver = ConflictResolver(entity)
        ok, reason = await resolver.resolve("user", "u1", "name", "张三", 0.9)
        assert ok is True
        assert "新属性" in reason

    async def test_confidence_ratio_override(self, entity: EntityMemoryStore) -> None:
        resolver = ConflictResolver(entity)
        await entity.upsert_attribute(
            "user", "u1", "name", "旧", confidence=0.5, source_session="s1"
        )
        ok, reason = await resolver.resolve("user", "u1", "name", "新", 0.9)
        assert ok is True
        assert "新置信度" in reason

    async def test_stale_naive_datetime_override(self, entity: EntityMemoryStore) -> None:
        resolver = ConflictResolver(entity)
        await entity.upsert_attribute(
            "user", "u1", "name", "很旧", confidence=0.8, source_session="s1"
        )
        record = await entity.read("user", "u1")
        assert record is not None
        # 构造无时区且超过 30 天的旧记录
        record.attributes["name"] = EntityAttributeValue(
            value="很旧",
            confidence=0.8,
            recorded_at=datetime.now() - timedelta(days=40),
        )
        await entity._save(record)
        ok, reason = await resolver.resolve("user", "u1", "name", "新", 0.5)
        assert ok is True
        assert "天" in reason

    async def test_low_confidence_rejected(self, entity: EntityMemoryStore) -> None:
        resolver = ConflictResolver(entity)
        await entity.upsert_attribute(
            "user", "u1", "name", "旧", confidence=0.9, source_session="s1"
        )
        ok, reason = await resolver.resolve("user", "u1", "name", "新", 0.5)
        assert ok is False
        assert "不足以覆盖" in reason


class TestEvictionManager:
    """EvictionManager 未覆盖分支。"""

    async def test_evict_cold_low_mention_node(
        self, episodic: EpisodicMemoryStore, semantic: SemanticKnowledgeStore
    ) -> None:
        manager = EvictionManager(episodic, semantic)
        cold = SemanticNode(
            name="cold",
            mention_count=0,
            last_seen_at=datetime.now(timezone.utc) - timedelta(days=100),
        )
        fresh = SemanticNode(
            name="fresh",
            mention_count=0,
            last_seen_at=datetime.now(timezone.utc),
        )
        no_seen = SemanticNode(name="noseen", mention_count=0, last_seen_at=None)
        for node in (cold, fresh, no_seen):
            await semantic.create_node(node)
        await manager.evict_expired("u1")
        assert await semantic.read_node(cold.id) is None
        assert await semantic.read_node(fresh.id) is not None
        assert await semantic.read_node(no_seen.id) is not None


class TestCompressionManager:
    """CompressionManager 未覆盖分支。"""

    async def test_should_merge_false_on_empty(self, episodic: EpisodicMemoryStore) -> None:
        manager = CompressionManager(episodic)
        assert await manager.should_merge("s1") is False

    async def test_merge_truncates_long_summary(self, episodic: EpisodicMemoryStore) -> None:
        manager = CompressionManager(episodic)
        long_summary = "长" * 1200
        await episodic.write(
            EpisodicMemoryEntry(
                session_id="s1",
                turn_index=0,
                summary=long_summary,
                importance=0.5,
            )
        )
        await manager.merge_session("s1")
        recalled = await episodic.recall_session("s1")
        merged = next(e for e in recalled if e.content_type == "summary")
        assert merged.summary.endswith("...")
        assert len(merged.summary) <= 1004


class TestBaseStore:
    """BaseStore 反序列化容错。"""

    async def test_deserialize_key_error_returns_none(self, episodic: EpisodicMemoryStore) -> None:
        result = episodic._deserialize_json(
            b'{"a": 1}',
            lambda raw: raw["missing"],
        )
        assert result is None


class TestEntityStoreCoverage:
    """EntityMemoryStore 未覆盖分支。"""

    async def test_read_batch(self, entity: EntityMemoryStore) -> None:
        await entity.upsert_attribute("user", "u1", "name", "张三", source_session="s1")
        results = await entity.read_batch([("user", "u1"), ("user", "u2")])
        assert results[0] is not None
        assert results[1] is None

    async def test_history_trim(self, entity: EntityMemoryStore) -> None:
        for i in range(10):
            await entity.upsert_attribute("user", "u1", "name", f"v{i}", source_session="s1")
        record = await entity.read("user", "u1")
        assert record is not None
        assert len(record.history["name"]) <= entity._MAX_HISTORY

    async def test_list_by_type_skips_bad_and_breaks_at_limit(
        self, entity: EntityMemoryStore
    ) -> None:
        for i in range(3):
            await entity.upsert_attribute("user", f"u{i}", "name", f"n{i}", source_session="s1")
        # 混入损坏数据（data 存在但反序列化失败）
        await entity._store.put("en:user:bad", b"not-json")
        entries = await entity.list_by_type("user", limit=2)
        assert len(entries) == 2


class RejectGate(MemoryCommitGate):
    """始终拒绝的门控替身。"""

    async def evaluate(
        self, user_message: str | None, assistant_message: str | None
    ) -> GateDecision:
        return GateDecision(importance=0.1, should_record=False, reason="reject")


class BoomGate(MemoryCommitGate):
    """抛出异常的门控替身。"""

    async def evaluate(
        self, user_message: str | None, assistant_message: str | None
    ) -> GateDecision:
        raise RuntimeError("gate boom")


class CtxStub:
    """极简 ctx 替身。"""

    def __init__(self, messages: list) -> None:
        self.messages = tuple(messages)
        self.services = {"user_id": "u1"}
        self.step_index = 1
        self.session_id = "s1"


class TestMemoryCommitHookCoverage:
    """MemoryCommitHook 未覆盖分支。"""

    async def test_gate_reject_returns(self) -> None:
        memory = AsyncMock()
        hook = MemoryCommitHook(memory, gate=RejectGate())
        result = await hook({}, CtxStub([{"role": "user", "content": "hi"}]))
        assert result == {}
        memory.commit.assert_not_called()

    async def test_gate_error_silent(self) -> None:
        memory = AsyncMock()
        hook = MemoryCommitHook(memory, gate=BoomGate())
        result = await hook({}, CtxStub([{"role": "user", "content": "hi"}]))
        assert result == {}
        memory.commit.assert_not_called()


class FakePersistence:
    """无 close 方法的持久化后端替身。"""

    async def get(self, key: str) -> bytes | None:
        return None

    async def put(self, key: str, value: bytes) -> None:
        return None

    async def delete(self, key: str) -> None:
        return None

    async def list_keys(self, prefix: str) -> list[str]:
        return []


class TestMemoryServiceBranches:
    """MemoryService 剩余分支。"""

    async def test_shutdown_cancel_branches(self) -> None:
        memory = MemoryService(SQLitePersistence(":memory:"))
        try:

            async def slow() -> None:
                await asyncio.sleep(30)

            memory._bg_tasks.start(slow())
            await memory._bg_tasks.shutdown(wait=True, timeout=0)  # 超时强制取消
            assert memory._bg_tasks._tasks == set()

            memory._bg_tasks.start(slow())
            await memory._bg_tasks.shutdown(wait=False)  # 直接取消
            assert memory._bg_tasks._tasks == set()
        finally:
            await memory.close()

    async def test_recall_with_concepts(self) -> None:
        memory = MemoryService(SQLitePersistence(":memory:"))
        try:
            node = SemanticNode(name="Python", description="编程语言")
            await memory.semantic.create_node(node)
            result = await memory.recall("s1", "u1", "python")
            assert any("Python" in c for c in result["concepts"])
        finally:
            await memory.close()

    async def test_recall_raw_user_without_entity(self) -> None:
        memory = MemoryService(SQLitePersistence(":memory:"))
        try:
            result = await memory.recall_raw("s1", "u1")
            assert result.entity_profile == {}
        finally:
            await memory.close()

    async def test_semantic_pipeline_skips_non_str(self) -> None:
        memory = MemoryService(SQLitePersistence(":memory:"))
        try:
            await memory._semantic_pipeline([("u1", "e1", {"count": 1})])
            await memory._semantic_pipeline([("u1", "e1", {"short": "ab"})])
            # 未抛出即通过
        finally:
            await memory.close()

    async def test_extract_entities_without_user(self) -> None:
        memory = MemoryService(SQLitePersistence(":memory:"))
        try:
            extracted = await memory._extract_entities(
                StepContext(user_id=None, entities_detected=["x"])
            )
            assert extracted == []
        finally:
            await memory.close()

    async def test_close_skips_backend_without_close(self) -> None:
        memory = MemoryService(FakePersistence())
        await memory.close()  # 不抛异常


class TestToolDispatcherCoverage:
    """ToolDispatcher 未覆盖分支。"""

    async def test_default_mcp_manager_created(self) -> None:
        dispatcher = ToolDispatcher(ToolRegistry())
        assert dispatcher.mcp_manager is not None

    async def test_dispatch_error_result(self) -> None:
        registry = ToolRegistry()

        async def boom(**kwargs: Any) -> str:
            raise RuntimeError("工具崩了")

        registry.register(
            ToolSpec(
                name="boom",
                description="boom",
                parameters={},
                handler=boom,
            )
        )
        dispatcher = ToolDispatcher(registry)
        from src.runtime.context._context import RuntimeContext

        ctx = RuntimeContext(
            messages=(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "boom", "arguments": "{}"},
                        }
                    ],
                },
            )
        )
        results = await dispatcher.dispatch(ctx)
        assert results is not None
        assert "Tool execution error" in results[0]["content"]

    async def test_execute_direct_format_and_mcp_missing(self) -> None:
        registry = ToolRegistry()

        async def echo(**kwargs: Any) -> str:
            return str(kwargs)

        registry.register(
            ToolSpec(
                name="echo",
                description="echo",
                parameters={"x": {"type": "string"}},
                handler=echo,
            )
        )
        mcp = AsyncMock()
        mcp.execute = AsyncMock(side_effect=KeyError("nope"))
        dispatcher = ToolDispatcher(registry, mcp_manager=mcp)
        # 直接格式（无 function 嵌套）
        direct = await dispatcher._execute_single_tool_call(
            {"id": "c2", "name": "echo", "arguments": {"x": 1}}
        )
        assert direct["content"] == "{'x': 1}"
        # MCP 前缀且工具缺失
        missing = await dispatcher._execute_single_tool_call(
            {"id": "c3", "name": "mcp_srv_tool", "arguments": {}}
        )
        assert "未找到" in missing["content"]


class TestBuilderMcpSkillsCoverage:
    """Builder MCP/Skills 接线补测。"""

    async def test_build_with_mcp_and_skills(self) -> None:
        from src.runtime._types import HookPoint
        from src.tools import MCPServerManager, SkillManager

        runtime = AgentRuntime.builder().mcp(MCPServerManager()).skills(SkillManager()).build()
        names = {h.name for h in runtime._hooks.list(HookPoint.BEFORE_LLM)}
        assert "_tools_schema_refresh" in names
        assert "_skill_inject" in names
