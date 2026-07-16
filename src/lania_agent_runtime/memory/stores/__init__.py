"""存储引擎实现层.

设计:
  - base.py         — StorageEngine 抽象基类
  - sqlite_engine.py — SQLiteStorageEngine (纯连接管理)
  - *_sqlite.py     — 各层 Store 实现 (仅继承接口 ABC, 通过组合持有 SQLiteStorageEngine)
"""

from __future__ import annotations

from lania_agent_runtime.memory.interfaces import (
    BehavioralStore,
    EntityStore,
    EpisodicStore,
    SemanticStore,
    WorkingMemoryStore,
)
from lania_agent_runtime.memory.stores.base import StorageEngine
from lania_agent_runtime.memory.stores.base_sqlite import SQLiteStore
from lania_agent_runtime.memory.stores.sqlite_engine import SQLiteStorageEngine
from lania_agent_runtime.memory.stores.working_file import WorkingMemoryFileStore
from lania_agent_runtime.memory.stores.working_sqlite import WorkingMemorySQLiteStore
from lania_agent_runtime.memory.stores.episodic_sqlite import EpisodicMemorySQLiteStore
from lania_agent_runtime.memory.stores.entity_sqlite import EntityMemorySQLiteStore
from lania_agent_runtime.memory.stores.semantic_sqlite import (
    SemanticKnowledgeSQLiteStore,
)
from lania_agent_runtime.memory.stores.pattern_sqlite import (
    BehavioralPatternSQLiteStore,
)


class CombinedSQLiteMemoryStore(
    WorkingMemoryStore,
    EpisodicStore,
    EntityStore,
    SemanticStore,
    BehavioralStore,
):
    """全层组合 SQLite 存储: 组合 Layer 1-5 全部 Store.

    通过 Composition 而非多继承, 内部共享一个 SQLiteStorageEngine.
    用户可替换为 PostgresStorageEngine + 自定义 Store 实现.

    Usage:
        # 快速上手 (内存 DB)
        store = CombinedSQLiteMemoryStore()
        await store.initialize()

        # 指定文件路径
        store = CombinedSQLiteMemoryStore("path/to/memory.db")
        await store.initialize()

        # 共享引擎
        engine = SQLiteStorageEngine("path/to/memory.db")
        store = CombinedSQLiteMemoryStore(engine=engine)
        await store.initialize()
    """

    def __init__(
        self,
        db_path: str | None = None,
        *,
        engine: SQLiteStorageEngine | None = None,
    ) -> None:
        if engine is not None:
            self._engine = engine
        else:
            self._engine = SQLiteStorageEngine(db_path or ":memory:")

        self._working = WorkingMemorySQLiteStore(self._engine)
        self._episodic = EpisodicMemorySQLiteStore(self._engine)
        self._entity = EntityMemorySQLiteStore(self._engine)
        self._semantic = SemanticKnowledgeSQLiteStore(self._engine)
        self._pattern = BehavioralPatternSQLiteStore(self._engine)

    # ── 生命周期 ──

    async def initialize(self) -> None:
        """初始化引擎连接 + 所有 5 层表."""
        await self._engine.initialize()
        await self._working.initialize()
        await self._episodic.initialize()
        await self._entity.initialize()
        await self._semantic.initialize()
        await self._pattern.initialize()

    async def close(self) -> None:
        """关闭引擎连接."""
        await self._engine.close()

    # ── 向后兼容属性 ──

    @property
    def _conn(self):
        """向后兼容: 获取底层 SQLite 连接 (供测试用)."""
        return self._engine.conn

    # ── 各层 Store 访问 ──

    @property
    def working_store(self) -> WorkingMemorySQLiteStore:
        return self._working

    @property
    def episodic_store(self) -> EpisodicMemorySQLiteStore:
        return self._episodic

    @property
    def entity_store(self) -> EntityMemorySQLiteStore:
        return self._entity

    @property
    def semantic_store(self) -> SemanticKnowledgeSQLiteStore:
        return self._semantic

    @property
    def pattern_store(self) -> BehavioralPatternSQLiteStore:
        return self._pattern

    # ── Layer 1: 工作记忆 ──

    async def save_working_memory(self, snapshot):
        return await self._working.save_working_memory(snapshot)

    async def load_working_memory(self, session_id: str):
        return await self._working.load_working_memory(session_id)

    async def delete_working_memory(self, session_id: str):
        return await self._working.delete_working_memory(session_id)

    async def exists_working_memory(self, session_id: str) -> bool:
        return await self._working.exists_working_memory(session_id)

    # ── Layer 2: 情景记忆 ──

    async def write(self, entry):
        return await self._episodic.write(entry)

    async def write_batch(self, entries):
        return await self._episodic.write_batch(entries)

    async def recall_session(
        self, session_id, *, limit=20, offset=0, min_importance=0.0
    ):
        return await self._episodic.recall_session(
            session_id,
            limit=limit,
            offset=offset,
            min_importance=min_importance,
        )

    async def recall_user(
        self, user_id, *, limit=20, offset=0, min_importance=0.0, since=None
    ):
        return await self._episodic.recall_user(
            user_id,
            limit=limit,
            offset=offset,
            min_importance=min_importance,
            since=since,
        )

    async def search_by_entities(self, user_id, entities, *, limit=10):
        return await self._episodic.search_by_entities(user_id, entities, limit=limit)

    async def search_by_topics(self, user_id, topics, *, limit=10):
        return await self._episodic.search_by_topics(user_id, topics, limit=limit)

    async def count_session(self, session_id: str) -> int:
        return await self._episodic.count_session(session_id)

    async def mark_merged(self, entry_id, merged_to_id):
        return await self._episodic.mark_merged(entry_id, merged_to_id)

    async def delete_before(self, user_id, before):
        return await self._episodic.delete_before(user_id, before)

    async def get_unmerged_raw(self, session_id, *, limit=50):
        return await self._episodic.get_unmerged_raw(session_id, limit=limit)

    # ── Layer 3: 实体记忆 ──

    async def upsert_entity_attribute(
        self,
        entity_type,
        entity_key,
        attr_name,
        value,
        *,
        confidence=1.0,
        source_session="",
    ):
        return await self._entity.upsert_entity_attribute(
            entity_type,
            entity_key,
            attr_name,
            value,
            confidence=confidence,
            source_session=source_session,
        )

    async def upsert_attributes(
        self, entity_type, entity_key, attributes, *, confidence=1.0, source_session=""
    ):
        return await self._entity.upsert_attributes(
            entity_type,
            entity_key,
            attributes,
            confidence=confidence,
            source_session=source_session,
        )

    async def get_entity_profile(self, entity_type, entity_key):
        return await self._entity.get_entity_profile(entity_type, entity_key)

    async def read_batch(self, keys):
        return await self._entity.read_batch(keys)

    async def delete_entity(self, entity_type, entity_key):
        return await self._entity.delete_entity(entity_type, entity_key)

    async def list_by_type(self, entity_type, *, limit=100):
        return await self._entity.list_by_type(entity_type, limit=limit)

    # ── Layer 4: 语义知识 ──

    async def create_semantic_node(self, name, node_type="concept", description=""):
        return await self._semantic.create_semantic_node(name, node_type, description)

    async def read_node(self, node_id):
        return await self._semantic.read_node(node_id)

    async def find_node_by_name(self, name):
        return await self._semantic.find_node_by_name(name)

    async def search_semantic(self, query, *, type_filter=None, limit=10):
        return await self._semantic.search_semantic(
            query, type_filter=type_filter, limit=limit
        )

    async def create_semantic_edge(
        self, source_node, target_node, relation, *, confidence=1.0
    ):
        return await self._semantic.create_semantic_edge(
            source_node, target_node, relation, confidence=confidence
        )

    async def get_semantic_edges(self, node_id, *, direction="both", limit=20):
        return await self._semantic.get_semantic_edges(
            node_id, direction=direction, limit=limit
        )

    async def get_neighbors(self, node_id, *, relation=None, max_depth=1, limit=20):
        return await self._semantic.get_neighbors(
            node_id, relation=relation, max_depth=max_depth, limit=limit
        )

    async def find_path(self, source_id, target_id, *, max_depth=5):
        return await self._semantic.find_path(source_id, target_id, max_depth=max_depth)

    async def merge_knowledge(self, extractions, *, source="extracted_from_dialogue"):
        return await self._semantic.merge_knowledge(extractions, source=source)

    async def increment_mention(self, node_id):
        return await self._semantic.increment_mention(node_id)

    async def get_low_mention_nodes(self, threshold=3, *, limit=50):
        return await self._semantic.get_low_mention_nodes(threshold, limit=limit)

    async def delete_node(self, node_id):
        return await self._semantic.delete_node(node_id)

    # ── Layer 5: 行为模式 ──

    async def upsert_behavioral_pattern(self, user_id, patterns):
        return await self._pattern.upsert_behavioral_pattern(user_id, patterns)

    async def get_behavioral_pattern(self, user_id):
        return await self._pattern.get_behavioral_pattern(user_id)

    async def delete_behavioral_pattern(self, user_id):
        return await self._pattern.delete_behavioral_pattern(user_id)

    async def acquire_lock(self, user_id, ttl=30):
        return await self._pattern.acquire_lock(user_id, ttl=ttl)


# 向后兼容: SQLiteMemoryStore 指向组合类
SQLiteMemoryStore = CombinedSQLiteMemoryStore


__all__ = [
    "StorageEngine",
    "SQLiteStorageEngine",
    "SQLiteStore",
    "WorkingMemoryFileStore",
    "WorkingMemorySQLiteStore",
    "EpisodicMemorySQLiteStore",
    "EntityMemorySQLiteStore",
    "SemanticKnowledgeSQLiteStore",
    "BehavioralPatternSQLiteStore",
    "CombinedSQLiteMemoryStore",
    "SQLiteMemoryStore",
]
