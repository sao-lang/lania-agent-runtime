"""
EntityMemoryStore——实体记忆存储适配器。

基于 MemoryPersistence 实现，键名前缀 en:{entity_type}:{entity_key}。
特性：
- UPSERT 语义（写时基于 (type, key) 合并）
- 保留属性变更历史
- 读取时一次返回完整画像
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.memory._persistence import MemoryPersistence
from src.memory._stores._base import BaseStore
from src.memory._types import EntityAttributeValue, EntityMemoryEntry


class EntityMemoryStore(BaseStore[EntityMemoryEntry]):
    """
    实体记忆存储适配器。

    将 EntityMemoryEntry 的读写转化为 MemoryPersistence 的键值操作。
    键名格式: en:{entity_type}:{entity_key}
    """

    _MAX_HISTORY = 20  # 每个属性保留的最大历史记录数

    def __init__(self, persistence: MemoryPersistence) -> None:
        """初始化 EntityMemoryStore。"""
        super().__init__(persistence)

    def _key(self, entity_type: str, entity_key: str) -> str:
        """构造存储键名。"""
        return f"en:{entity_type}:{entity_key}"

    def _serialize(self, entry: EntityMemoryEntry) -> bytes:
        """将实体序列化为 bytes。"""
        return self._serialize_json(entry, self._entry_to_dict)

    def _deserialize(self, data: bytes) -> EntityMemoryEntry | None:
        """将 bytes 反序列化为实体条目。"""
        return self._deserialize_json(data, self._entry_from_dict)

    @staticmethod
    def _attr_to_dict(attr: EntityAttributeValue) -> dict:
        return {
            "value": attr.value,
            "confidence": attr.confidence,
            "recorded_at": attr.recorded_at.isoformat() if attr.recorded_at else None,
            "source_session": attr.source_session,
        }

    @staticmethod
    def _attr_from_dict(d: dict) -> EntityAttributeValue:
        return EntityAttributeValue(
            value=d.get("value"),
            confidence=d.get("confidence", 1.0),
            recorded_at=(
                datetime.fromisoformat(d["recorded_at"])
                if d.get("recorded_at")
                else None
            ),
            source_session=d.get("source_session", ""),
        )

    def _entry_to_dict(self, entry: EntityMemoryEntry) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "entity_type": entry.entity_type,
            "entity_key": entry.entity_key,
            "attributes": {
                name: self._attr_to_dict(attr)
                for name, attr in entry.attributes.items()
            },
            "history": {
                name: [self._attr_to_dict(a) for a in hist]
                for name, hist in entry.history.items()
            },
            "created_at": (
                entry.created_at.isoformat() if entry.created_at else now.isoformat()
            ),
            "last_updated_at": now.isoformat(),
            "last_source_session": entry.last_source_session,
            "ttl": entry.ttl.isoformat() if entry.ttl else None,
        }

    @staticmethod
    def _entry_from_dict(raw: dict) -> EntityMemoryEntry:
        attributes = {
            name: EntityMemoryStore._attr_from_dict(attr)
            for name, attr in raw.get("attributes", {}).items()
        }
        history = {
            name: [EntityMemoryStore._attr_from_dict(a) for a in hist]
            for name, hist in raw.get("history", {}).items()
        }
        return EntityMemoryEntry(
            entity_type=raw.get("entity_type", ""),
            entity_key=raw.get("entity_key", ""),
            attributes=attributes,
            history=history,
            created_at=(
                datetime.fromisoformat(raw["created_at"])
                if raw.get("created_at")
                else None
            ),
            last_updated_at=(
                datetime.fromisoformat(raw["last_updated_at"])
                if raw.get("last_updated_at")
                else None
            ),
            last_source_session=raw.get("last_source_session", ""),
            ttl=(
                datetime.fromisoformat(raw["ttl"])
                if raw.get("ttl")
                else None
            ),
        )

    async def read(
        self,
        entity_type: str,
        entity_key: str,
    ) -> EntityMemoryEntry | None:
        """
        读取完整实体（attributes + history）。

        Args:
            entity_type: 实体类型。
            entity_key: 实体标识。

        Returns:
            实体条目，不存在则返回 None。
        """
        data = await self._store.get(self._key(entity_type, entity_key))
        if data is None:
            return None
        return self._deserialize(data)

    async def read_batch(
        self,
        keys: list[tuple[str, str]],
    ) -> list[EntityMemoryEntry | None]:
        """
        批量读取实体。

        Args:
            keys: (entity_type, entity_key) 列表。

        Returns:
            实体条目列表，不存在的项为 None。
        """
        results: list[EntityMemoryEntry | None] = []
        for entity_type, entity_key in keys:
            entry = await self.read(entity_type, entity_key)
            results.append(entry)
        return results

    async def upsert_attribute(
        self,
        entity_type: str,
        entity_key: str,
        attr_name: str,
        value: Any,
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> EntityMemoryEntry:
        """
        更新实体单个属性。

        - 如果实体不存在则创建
        - attributes[attr_name] 更新为新值
        - history[attr_name] 追加快照

        Args:
            entity_type: 实体类型。
            entity_key: 实体标识。
            attr_name: 属性名。
            value: 属性值。
            confidence: 置信度。
            source_session: 来源会话 ID。

        Returns:
            更新后的实体条目。
        """
        now = datetime.now(timezone.utc)
        existing = await self.read(entity_type, entity_key)

        if existing is None:
            new_attr = EntityAttributeValue(
                value=value,
                confidence=confidence,
                recorded_at=now,
                source_session=source_session,
            )
            entry = EntityMemoryEntry(
                entity_type=entity_type,
                entity_key=entity_key,
                attributes={attr_name: new_attr},
                history={attr_name: [new_attr]},
                created_at=now,
                last_updated_at=now,
                last_source_session=source_session,
            )
            await self._save(entry)
            return entry

        # 更新属性
        new_attr = EntityAttributeValue(
            value=value,
            confidence=confidence,
            recorded_at=now,
            source_session=source_session,
        )
        existing.attributes[attr_name] = new_attr

        # 追加历史
        if attr_name not in existing.history:
            existing.history[attr_name] = []
        existing.history[attr_name].append(new_attr)
        # 限制历史记录数量
        if len(existing.history[attr_name]) > self._MAX_HISTORY:
            existing.history[attr_name] = existing.history[attr_name][-self._MAX_HISTORY:]

        existing.last_updated_at = now
        existing.last_source_session = source_session

        await self._save(existing)
        return existing

    async def upsert_attributes(
        self,
        entity_type: str,
        entity_key: str,
        attributes: dict[str, Any],
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> EntityMemoryEntry:
        """
        批量更新多个属性。

        Args:
            entity_type: 实体类型。
            entity_key: 实体标识。
            attributes: 属性字典。
            confidence: 置信度。
            source_session: 来源会话 ID。

        Returns:
            更新后的实体条目。
        """
        entry = await self.read(entity_type, entity_key)
        result = entry
        for attr_name, value in attributes.items():
            result = await self.upsert_attribute(
                entity_type,
                entity_key,
                attr_name,
                value,
                confidence=confidence,
                source_session=source_session,
            )
        return result

    async def delete_entity(
        self,
        entity_type: str,
        entity_key: str,
    ) -> None:
        """
        删除整个实体及其历史。

        Args:
            entity_type: 实体类型。
            entity_key: 实体标识。
        """
        await self._store.delete(self._key(entity_type, entity_key))

    async def list_by_type(
        self,
        entity_type: str,
        *,
        limit: int = 100,
    ) -> list[EntityMemoryEntry]:
        """
        按类型列出所有实体。

        Args:
            entity_type: 实体类型。
            limit: 最大返回条数。

        Returns:
            实体条目列表。
        """
        keys = await self._store.list_keys(f"en:{entity_type}:")
        entries: list[EntityMemoryEntry] = []
        for key in keys:
            data = await self._store.get(key)
            if data is not None:
                entry = self._deserialize(data)
                if entry:
                    entries.append(entry)
                    if len(entries) >= limit:
                        break
        return entries

    async def _save(self, entry: EntityMemoryEntry) -> None:
        """保存实体到存储。"""
        data = self._serialize(entry)
        await self._store.put(
            self._key(entry.entity_type, entry.entity_key),
            data,
        )
