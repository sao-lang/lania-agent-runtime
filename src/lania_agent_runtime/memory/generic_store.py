"""通用记忆存储: 基于 StorageBackend 原语实现完整的 MemoryStore (5层记忆)."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from lania_agent_runtime.memory.backends import StorageBackend
from lania_agent_runtime.memory.interfaces import MemoryStore
from lania_agent_runtime.models import (
    BehavioralPattern,
    EntityMemoryEntry,
    EpisodicMemoryEntry,
    SemanticEdge,
    SemanticNode,
    WorkingMemorySnapshot,
)


def _to_json(obj: Any) -> str:
    return json.dumps(asdict(obj), ensure_ascii=False, default=str)


class GenericMemoryStore(MemoryStore):
    """通用记忆存储: 将 5 层记忆的 40+ 个方法翻译为 StorageBackend 原语操作.

    用户只需实现 StorageBackend (约 25 个原语), 即获得完整的 5 层记忆系统.
    """

    def __init__(self, backend: StorageBackend) -> None:
        self._backend = backend

    # ── 生命周期 ──

    async def initialize(self) -> None:
        """初始化后端连接."""
        await self._backend.initialize()

    async def close(self) -> None:
        """关闭后端连接."""
        await self._backend.close()

    # ── 属性 ──

    @property
    def backend(self) -> StorageBackend:
        return self._backend

    # ════════════════════════════════════════════════════════
    # Layer 1: 工作记忆
    # ════════════════════════════════════════════════════════

    async def save_working_memory(self, snapshot: WorkingMemorySnapshot) -> None:
        ttl = getattr(snapshot, "ttl", 3600)
        await self._backend.kv_set(
            f"wm:{snapshot.session_id}",
            _to_json(snapshot),
            ttl=ttl,
        )

    async def load_working_memory(
        self, session_id: str
    ) -> WorkingMemorySnapshot | None:
        data = await self._backend.kv_get(f"wm:{session_id}")
        if data is None:
            return None
        return WorkingMemorySnapshot(**json.loads(data))

    async def delete_working_memory(self, session_id: str) -> None:
        await self._backend.kv_delete(f"wm:{session_id}")

    async def exists_working_memory(self, session_id: str) -> bool:
        return await self._backend.kv_exists(f"wm:{session_id}")

    # ════════════════════════════════════════════════════════
    # Layer 2: 情景记忆
    # ════════════════════════════════════════════════════════

    async def _episodic_key(self, session_id: str) -> str:
        return f"ep:{session_id}"

    async def _episodic_user_key(self, user_id: str) -> str:
        return f"ep_user:{user_id}"

    async def _episodic_entity_key(self, entity: str, session_id: str) -> str:
        return f"ep_entity:{entity}:{session_id}"

    async def _episodic_topic_key(self, topic: str, session_id: str) -> str:
        return f"ep_topic:{topic}:{session_id}"

    async def write(self, entry: EpisodicMemoryEntry) -> str:
        entry_id = entry.id or uuid.uuid4().hex
        entry.id = entry_id
        entry_json = _to_json(entry)

        # 按 ID 存储 (用于标签搜索回查)
        await self._backend.kv_set(f"ep_entry:{entry_id}", entry_json)

        # 按 session 追加
        await self._backend.list_push(
            await self._episodic_key(entry.session_id), entry_json
        )

        # 用户索引
        if entry.user_id:
            await self._backend.list_push(
                await self._episodic_user_key(entry.user_id), entry_json
            )

        # 实体标签索引
        for entity in (entry.entities or []):
            await self._backend.set_add(
                await self._episodic_entity_key(entity, entry.session_id), entry_id
            )

        # 话题标签索引
        for topic in (entry.topics or []):
            await self._backend.set_add(
                await self._episodic_topic_key(topic, entry.session_id), entry_id
            )

        return entry_id

    async def write_batch(self, entries: list[EpisodicMemoryEntry]) -> list[str]:
        return [await self.write(e) for e in entries]

    async def recall_session(
        self,
        session_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        min_importance: float = 0.0,
    ) -> list[EpisodicMemoryEntry]:
        all_entries = await self._backend.list_range(
            await self._episodic_key(session_id), 0, -1
        )
        result = []
        for raw in reversed(all_entries):
            entry = EpisodicMemoryEntry(**json.loads(raw))
            if entry.importance < min_importance:
                continue
            # 检查是否被合并 (从独立 KV 读取)
            merged_to = await self._backend.kv_get(f"ep_merged:{entry.id}")
            if merged_to:
                entry.merged_to = merged_to
            result.append(entry)
            if len(result) >= offset + limit:
                break
        return result[offset:]

    async def recall_user(
        self,
        user_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        min_importance: float = 0.0,
        since: str | None = None,
    ) -> list[EpisodicMemoryEntry]:
        all_entries = await self._backend.list_range(
            await self._episodic_user_key(user_id), 0, -1
        )
        result = []
        for raw in reversed(all_entries):
            entry = EpisodicMemoryEntry(**json.loads(raw))
            if entry.importance < min_importance:
                continue
            if since and entry.created_at and entry.created_at < since:
                continue
            result.append(entry)
            if len(result) >= offset + limit:
                break
        return result[offset:]

    async def search_by_entities(
        self,
        user_id: str,
        entities: list[str],
        *,
        limit: int = 10,
    ) -> list[EpisodicMemoryEntry]:
        return await self._search_by_tags(user_id, entities, "entities", limit=limit)

    async def search_by_topics(
        self,
        user_id: str,
        topics: list[str],
        *,
        limit: int = 10,
    ) -> list[EpisodicMemoryEntry]:
        return await self._search_by_tags(user_id, topics, "topics", limit=limit)

    async def _search_by_tags(
        self,
        user_id: str,
        tags: list[str],
        attr: str = "entities",
        *,
        limit: int = 10,
    ) -> list[EpisodicMemoryEntry]:
        """通过标签搜索记忆条目 (客户端过滤)."""
        tag_set = set(t.lower() for t in tags)
        all_entries = await self._backend.list_range(
            await self._episodic_user_key(user_id), 0, -1
        )
        result: list[EpisodicMemoryEntry] = []
        for raw in reversed(all_entries):
            entry = EpisodicMemoryEntry(**json.loads(raw))
            entry_tags = set(t.lower() for t in (entry.entities if attr == "entities" else entry.topics or []))
            if tag_set & entry_tags:
                result.append(entry)
                if len(result) >= limit:
                    break
        return result

    async def count_session(self, session_id: str) -> int:
        return await self._backend.list_len(await self._episodic_key(session_id))

    async def mark_merged(self, entry_id: str, merged_to_id: str) -> None:
        """标记一条记录已被合并."""
        await self._backend.kv_set(f"ep_merged:{entry_id}", merged_to_id)

    async def delete_before(self, user_id: str, before: str) -> int:
        """删除指定时间之前的记录."""
        # 从用户列表中扫描并过滤
        all_entries = await self._backend.list_range(
            await self._episodic_user_key(user_id), 0, -1
        )
        deleted = 0
        keep: list[str] = []
        for raw in all_entries:
            entry = EpisodicMemoryEntry(**json.loads(raw))
            if entry.created_at and entry.created_at < before and not entry.merged_to:
                deleted += 1
            else:
                keep.append(raw)
        if deleted > 0:
            # 重写用户列表 (移除过期条目)
            for _ in all_entries:
                await self._backend.list_remove(
                    await self._episodic_user_key(user_id), all_entries[0], count=1
                )
            for raw in keep:
                await self._backend.list_push(
                    await self._episodic_user_key(user_id), raw
                )
        return deleted

    async def get_unmerged_raw(
        self, session_id: str, *, limit: int = 50
    ) -> list[EpisodicMemoryEntry]:
        all_entries = await self._backend.list_range(
            await self._episodic_key(session_id), 0, -1
        )
        result: list[EpisodicMemoryEntry] = []
        for raw in all_entries:
            entry = EpisodicMemoryEntry(**json.loads(raw))
            # 检查是否已合并
            merged = await self._backend.kv_get(f"ep_merged:{entry.id}")
            if merged is None:
                result.append(entry)
                if len(result) >= limit:
                    break
        return result

    # ════════════════════════════════════════════════════════
    # Layer 3: 实体记忆
    # ════════════════════════════════════════════════════════

    def _entity_key(self, entity_type: str, entity_key: str) -> str:
        return f"entity:{entity_type}:{entity_key}"

    def _entity_type_key(self, entity_type: str) -> str:
        return f"entity_type:{entity_type}"

    async def upsert_entity_attribute(
        self,
        entity_type: str,
        entity_key: str,
        attr_name: str,
        value: Any,
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> None:
        key = self._entity_key(entity_type, entity_key)
        raw = await self._backend.kv_get(key)
        now = datetime.now(timezone.utc).isoformat()

        if raw:
            entry = EntityMemoryEntry(**json.loads(raw))
        else:
            entry = EntityMemoryEntry(
                entity_type=entity_type,
                entity_key=entity_key,
                attributes={},
                history={},
                created_at=now,
                last_updated_at=now,
                last_source_session=source_session,
            )

        # 更新属性
        entry.attributes[attr_name] = {
            "value": value,
            "confidence": confidence,
            "recorded_at": now,
            "source_session": source_session,
        }
        # 更新历史 (滑动窗口 20 条)
        if attr_name not in entry.history:
            entry.history[attr_name] = []
        entry.history[attr_name].append({
            "value": value,
            "confidence": confidence,
            "recorded_at": now,
            "source_session": source_session,
        })
        if len(entry.history[attr_name]) > 20:
            entry.history[attr_name] = entry.history[attr_name][-20:]

        entry.last_updated_at = now
        entry.last_source_session = source_session

        await self._backend.kv_set(key, _to_json(entry))
        # 维护类型索引
        await self._backend.set_add(
            self._entity_type_key(entity_type), entity_key
        )

    async def upsert_attributes(
        self,
        entity_type: str,
        entity_key: str,
        attributes: dict[str, Any],
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> None:
        for attr_name, value in attributes.items():
            await self.upsert_entity_attribute(
                entity_type, entity_key, attr_name, value,
                confidence=confidence, source_session=source_session,
            )

    async def get_entity_profile(
        self, entity_type: str, entity_key: str
    ) -> EntityMemoryEntry | None:
        raw = await self._backend.kv_get(self._entity_key(entity_type, entity_key))
        if raw is None:
            return None
        return EntityMemoryEntry(**json.loads(raw))

    async def read_batch(
        self, keys: list[tuple[str, str]]
    ) -> list[EntityMemoryEntry | None]:
        result = []
        for entity_type, entity_key in keys:
            result.append(await self.get_entity_profile(entity_type, entity_key))
        return result

    async def delete_entity(self, entity_type: str, entity_key: str) -> None:
        await self._backend.kv_delete(self._entity_key(entity_type, entity_key))

    async def list_by_type(
        self, entity_type: str, *, limit: int = 100
    ) -> list[EntityMemoryEntry]:
        keys = await self._backend.set_members(
            self._entity_type_key(entity_type)
        )
        result = []
        for key in list(keys)[:limit]:
            raw = await self._backend.kv_get(
                self._entity_key(entity_type, key)
            )
            if raw:
                result.append(EntityMemoryEntry(**json.loads(raw)))
        return result

    # ════════════════════════════════════════════════════════
    # Layer 4: 语义知识
    # ════════════════════════════════════════════════════════

    async def create_semantic_node(
        self,
        name: str,
        node_type: str = "concept",
        description: str = "",
    ) -> str:
        node_id = uuid.uuid4().hex
        created = await self._backend.graph_node_create(
            node_id, name, node_type, description
        )
        if not created:
            existing = await self._backend.graph_node_find_by_name(name)
            if existing:
                return existing["id"]
            # 后端不可用 (未初始化)
            return ""
        return node_id

    async def read_node(self, node_id: str) -> SemanticNode | None:
        raw = await self._backend.graph_node_get(node_id)
        if raw is None:
            return None
        return SemanticNode(**raw)

    async def find_node_by_name(self, name: str) -> SemanticNode | None:
        raw = await self._backend.graph_node_find_by_name(name)
        if raw is None:
            return None
        return SemanticNode(**raw)

    async def search_semantic(
        self,
        query: str,
        *,
        type_filter: str | None = None,
        limit: int = 10,
    ) -> list[SemanticNode]:
        raw_nodes = await self._backend.graph_node_search(
            query, type_filter=type_filter, limit=limit
        )
        return [SemanticNode(**n) for n in raw_nodes]

    async def create_semantic_edge(
        self,
        source_node: str,
        target_node: str,
        relation: str,
        *,
        confidence: float = 1.0,
    ) -> str:
        edge_id = uuid.uuid4().hex
        created = await self._backend.graph_edge_create(
            source_node, target_node, relation, confidence
        )
        return edge_id if created else ""

    async def get_semantic_edges(
        self,
        node_id: str,
        *,
        direction: str = "both",
        limit: int = 20,
    ) -> list[SemanticEdge]:
        raw_edges = await self._backend.graph_edge_list(
            node_id, direction=direction, limit=limit
        )
        return [SemanticEdge(**e) for e in raw_edges]

    async def get_neighbors(
        self,
        node_id: str,
        *,
        relation: str | None = None,
        max_depth: int = 1,
        limit: int = 20,
    ) -> list[tuple[SemanticNode, str]]:
        raw = await self._backend.graph_neighbors(
            node_id, relation=relation, max_depth=max_depth, limit=limit
        )
        result: list[tuple[SemanticNode, str]] = []
        for n, r in raw:
            # 移除后端返回的附加字段 (如 rel)
            clean = {k: v for k, v in n.items() if k in SemanticNode.__dataclass_fields__}
            result.append((SemanticNode(**clean), r))
        return result

    async def find_path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 5,
    ) -> list[list[tuple[str, str]]]:
        return await self._backend.graph_find_path(
            source_id, target_id, max_depth=max_depth
        )

    async def merge_knowledge(
        self,
        extractions: list[tuple[str, str, str]],
        *,
        source: str = "extracted_from_dialogue",
    ) -> None:
        for source_name, relation, target_name in extractions:
            src_id = await self.create_semantic_node(source_name)
            tgt_id = await self.create_semantic_node(target_name)
            await self.create_semantic_edge(src_id, tgt_id, relation)

    async def increment_mention(self, node_id: str) -> None:
        await self._backend.graph_node_increment_mention(node_id)

    async def get_low_mention_nodes(
        self, threshold: int = 3, *, limit: int = 50
    ) -> list[SemanticNode]:
        raw = await self._backend.graph_node_get_low_mention(threshold, limit)
        return [SemanticNode(**n) for n in raw]

    async def delete_node(self, node_id: str) -> None:
        await self._backend.graph_node_delete(node_id)

    # ════════════════════════════════════════════════════════
    # Layer 5: 行为模式
    # ════════════════════════════════════════════════════════

    def _pattern_key(self, user_id: str) -> str:
        return f"pattern:{user_id}"

    def _pattern_lock_key(self, user_id: str) -> str:
        return f"pattern_lock:{user_id}"

    async def upsert_behavioral_pattern(
        self, user_id: str, patterns: dict[str, Any]
    ) -> None:
        key = self._pattern_key(user_id)
        raw = await self._backend.kv_get(key)
        now = datetime.now(timezone.utc).isoformat()

        if raw:
            existing = BehavioralPattern(**json.loads(raw))
            version = existing.version + 1
        else:
            version = 1

        entry = BehavioralPattern(
            user_id=user_id,
            patterns=patterns,
            version=version,
            last_converged_at=now,
        )
        await self._backend.kv_set(key, _to_json(entry))

    async def get_behavioral_pattern(
        self, user_id: str
    ) -> BehavioralPattern | None:
        raw = await self._backend.kv_get(self._pattern_key(user_id))
        if raw is None:
            return None
        return BehavioralPattern(**json.loads(raw))

    async def delete_behavioral_pattern(self, user_id: str) -> None:
        await self._backend.kv_delete(self._pattern_key(user_id))

    async def acquire_lock(self, user_id: str, ttl: int = 30) -> bool:
        return await self._backend.acquire_lock(
            self._pattern_lock_key(user_id), ttl=ttl
        )
