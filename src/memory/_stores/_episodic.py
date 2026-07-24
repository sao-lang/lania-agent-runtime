"""
EpisodicMemoryStore——情景记忆存储适配器。

基于 MemoryPersistence 实现，键名前缀 ep:{session_id}:{turn_index}:{entry_id}。
特性：
- append-only（写入后不修改，仅 merged_to 字段可更新）
- 时间序索引 + 标签索引
- 支持按实体/话题检索（通过前缀扫描后内存过滤）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.memory._persistence import MemoryPersistence
from src.memory._types import EpisodicMemoryEntry, MemorySource, ToolCallRecord


class EpisodicMemoryStore:
    """
    情景记忆存储适配器。

    将 EpisodicMemoryEntry 的读写转化为 MemoryPersistence 的键值操作。
    键名格式: ep:{session_id}:{turn_index}:{entry_id}
    """

    def __init__(self, persistence: MemoryPersistence) -> None:
        """
        初始化 EpisodicMemoryStore。

        Args:
            persistence: MemoryPersistence 实例。
        """
        self._store = persistence

    def _key(self, session_id: str, turn_index: int, entry_id: str) -> str:
        """构造存储键名。"""
        return f"ep:{session_id}:{turn_index}:{entry_id}"

    def _parse_key(self, key: str) -> tuple[str, int, str] | None:
        """从键名解析 session_id、turn_index 和 entry_id。"""
        parts = key.split(":", 3)
        if len(parts) == 4 and parts[0] == "ep":
            try:
                return parts[1], int(parts[2]), parts[3]
            except (ValueError, IndexError):
                return None
        return None

    def _serialize(self, entry: EpisodicMemoryEntry) -> bytes:
        """将条目序列化为 bytes。"""
        data: dict[str, Any] = {
            "id": entry.id,
            "session_id": entry.session_id,
            "user_id": entry.user_id,
            "turn_index": entry.turn_index,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "summary": entry.summary,
            "raw_content": entry.raw_content,
            "content_type": entry.content_type,
            "entities": entry.entities,
            "topics": entry.topics,
            "keywords": entry.keywords,
            "importance": entry.importance,
            "token_count": entry.token_count,
            "merged_to": entry.merged_to,
            "merged_from": entry.merged_from,
        }
        if entry.source:
            data["source"] = {
                "user_message": entry.source.user_message,
                "assistant_message": entry.source.assistant_message,
                "tool_calls": (
                    [
                        {
                            "tool_name": tc.tool_name,
                            "args": tc.args,
                            "result": tc.result,
                        }
                        for tc in entry.source.tool_calls
                    ]
                    if entry.source.tool_calls
                    else None
                ),
            }
        return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")

    def _deserialize(self, data: bytes) -> EpisodicMemoryEntry | None:
        """将 bytes 反序列化为条目。"""
        try:
            raw = json.loads(data.decode("utf-8"))
            source_raw = raw.get("source")
            source = None
            if source_raw:
                tool_calls_raw = source_raw.get("tool_calls")
                tool_calls = None
                if tool_calls_raw:
                    tool_calls = [
                        ToolCallRecord(
                            tool_name=tc["tool_name"],
                            args=tc.get("args", {}),
                            result=tc.get("result", ""),
                        )
                        for tc in tool_calls_raw
                    ]
                source = MemorySource(
                    user_message=source_raw.get("user_message"),
                    assistant_message=source_raw.get("assistant_message"),
                    tool_calls=tool_calls,
                )

            return EpisodicMemoryEntry(
                id=raw.get("id", ""),
                session_id=raw.get("session_id", ""),
                user_id=raw.get("user_id", ""),
                turn_index=raw.get("turn_index", 0),
                created_at=(
                    datetime.fromisoformat(raw["created_at"])
                    if raw.get("created_at")
                    else None
                ),
                summary=raw.get("summary", ""),
                raw_content=raw.get("raw_content"),
                content_type=raw.get("content_type", "raw"),
                source=source,
                entities=raw.get("entities", []),
                topics=raw.get("topics", []),
                keywords=raw.get("keywords", []),
                importance=raw.get("importance", 0.3),
                token_count=raw.get("token_count", 0),
                merged_to=raw.get("merged_to"),
                merged_from=raw.get("merged_from", []),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    async def write(self, entry: EpisodicMemoryEntry) -> str:
        """
        写入一条情景记忆。

        Args:
            entry: 情景记忆条目。

        Returns:
            条目 ID。
        """
        data = self._serialize(entry)
        await self._store.put(
            self._key(entry.session_id, entry.turn_index, entry.id),
            data,
        )
        return entry.id

    async def write_batch(self, entries: list[EpisodicMemoryEntry]) -> list[str]:
        """
        批量写入情景记忆。

        Args:
            entries: 情景记忆条目列表。

        Returns:
            条目 ID 列表。
        """
        ids: list[str] = []
        for entry in entries:
            await self.write(entry)
            ids.append(entry.id)
        return ids

    async def recall_session(
        self,
        session_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        min_importance: float = 0.0,
    ) -> list[EpisodicMemoryEntry]:
        """
        按 session 召回，按 turn_index DESC 排序。

        Args:
            session_id: 会话 ID。
            limit: 最大返回条数。
            offset: 偏移量。
            min_importance: 最小重要性阈值。

        Returns:
            情景记忆条目列表。
        """
        keys = await self._store.list_keys(f"ep:{session_id}:")
        entries: list[EpisodicMemoryEntry] = []
        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                entry = self._deserialize(data)
                if entry and entry.importance >= min_importance:
                    entries.append(entry)

        entries.sort(key=lambda e: e.turn_index, reverse=True)
        return entries[offset: offset + limit]

    async def recall_user(
        self,
        user_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        since: datetime | None = None,
    ) -> list[EpisodicMemoryEntry]:
        """
        按用户跨 session 召回。

        注意：需要全量扫描后过滤，适合低频操作。

        Args:
            user_id: 用户 ID。
            limit: 最大返回条数。
            offset: 偏移量。
            since: 只返回此时间之后的记录。

        Returns:
            情景记忆条目列表。
        """
        # 获取所有 ep: 前缀的键
        keys = await self._store.list_keys("ep:")
        entries: list[EpisodicMemoryEntry] = []
        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                entry = self._deserialize(data)
                if entry and entry.user_id == user_id:
                    if since and entry.created_at and entry.created_at < since:
                        continue
                    entries.append(entry)

        entries.sort(key=lambda e: e.created_at or datetime.min, reverse=True)
        return entries[offset: offset + limit]

    async def search_by_entities(
        self,
        user_id: str,
        entities: list[str],
        *,
        limit: int = 10,
    ) -> list[EpisodicMemoryEntry]:
        """
        召回包含指定实体标签的记忆。

        Args:
            user_id: 用户 ID。
            entities: 实体名称列表。
            limit: 最大返回条数。

        Returns:
            情景记忆条目列表。
        """
        entity_set = set(e.lower() for e in entities)
        keys = await self._store.list_keys("ep:")
        entries: list[EpisodicMemoryEntry] = []
        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                entry = self._deserialize(data)
                if entry and entry.user_id == user_id:
                    entry_entities = set(e.lower() for e in entry.entities)
                    if entry_entities & entity_set:  # 有交集
                        entries.append(entry)

        entries.sort(key=lambda e: e.importance, reverse=True)
        return entries[:limit]

    async def search_by_topics(
        self,
        user_id: str,
        topics: list[str],
        *,
        limit: int = 10,
    ) -> list[EpisodicMemoryEntry]:
        """
        召回包含指定话题标签的记忆。

        Args:
            user_id: 用户 ID。
            topics: 话题列表。
            limit: 最大返回条数。

        Returns:
            情景记忆条目列表。
        """
        topic_set = set(t.lower() for t in topics)
        keys = await self._store.list_keys("ep:")
        entries: list[EpisodicMemoryEntry] = []
        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                entry = self._deserialize(data)
                if entry and entry.user_id == user_id:
                    entry_topics = set(t.lower() for t in entry.topics)
                    if entry_topics & topic_set:
                        entries.append(entry)

        entries.sort(key=lambda e: e.importance, reverse=True)
        return entries[:limit]

    async def recall_by_turn_range(
        self,
        session_id: str,
        start_turn: int,
        end_turn: int,
    ) -> list[EpisodicMemoryEntry]:
        """
        按 turn_index 范围检索记忆。

        Args:
            session_id: 会话 ID。
            start_turn: 起始 turn（包含）。
            end_turn: 结束 turn（包含）。

        Returns:
            情景记忆条目列表。
        """
        keys = await self._store.list_keys(f"ep:{session_id}:")
        entries: list[EpisodicMemoryEntry] = []
        for key in keys:
            parsed = self._parse_key(key)
            if parsed and start_turn <= parsed[1] <= end_turn:
                data = await self._store.get(key)
                if data is not None:
                    entry = self._deserialize(data)
                    if entry:
                        entries.append(entry)

        entries.sort(key=lambda e: e.turn_index)
        return entries

    async def mark_merged(
        self,
        entry_id: str,
        merged_to_id: str,
    ) -> None:
        """
        标记一条记录已被合并到另一条。

        Args:
            entry_id: 被合并的条目 ID。
            merged_to_id: 目标摘要条目 ID。
        """
        # 需要遍历找到对应的键（因为键名含 session_id 和 turn_index）
        keys = await self._store.list_keys("ep:")
        for key in keys:
            parsed = self._parse_key(key)
            if parsed and parsed[2] == entry_id:
                data = await self._store.get(key)
                if data is not None:
                    entry = self._deserialize(data)
                    if entry:
                        entry.merged_to = merged_to_id
                        await self._store.put(key, self._serialize(entry))
                return

    async def count_session(self, session_id: str) -> int:
        """
        统计 session 的记录数。

        Args:
            session_id: 会话 ID。

        Returns:
            记录数。
        """
        keys = await self._store.list_keys(f"ep:{session_id}:")
        return len(keys)

    async def delete_before(self, user_id: str, before: datetime) -> None:
        """
        批量删除指定时间之前的记录（遗忘）。

        Args:
            user_id: 用户 ID。
            before: 时间边界。
        """
        keys = await self._store.list_keys("ep:")
        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                entry = self._deserialize(data)
                if entry and entry.user_id == user_id:
                    if entry.created_at and entry.created_at < before:
                        if entry.merged_to is None:
                            await self._store.delete(key)
