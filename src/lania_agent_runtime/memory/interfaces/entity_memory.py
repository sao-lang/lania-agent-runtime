"""Layer 3: 实体记忆存储接口."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from lania_agent_runtime.models import EntityMemoryEntry


class EntityStore(ABC):
    """实体记忆存储接口 (Layer 3).

    特性:
    - UPSERT 语义 (写时基于 (type, key) 合并)
    - 保留属性变更历史
    - 读取时一次返回完整画像
    """

    @abstractmethod
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
        """更新实体单个属性. 如果实体不存在则创建."""

    @abstractmethod
    async def upsert_attributes(
        self,
        entity_type: str,
        entity_key: str,
        attributes: dict[str, Any],
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> None:
        """批量更新多个属性."""

    @abstractmethod
    async def get_entity_profile(
        self, entity_type: str, entity_key: str
    ) -> EntityMemoryEntry | None:
        """读取完整实体画像(attributes + history)."""

    @abstractmethod
    async def read_batch(
        self, keys: list[tuple[str, str]]
    ) -> list[EntityMemoryEntry | None]:
        """批量读取实体画像."""

    @abstractmethod
    async def delete_entity(self, entity_type: str, entity_key: str) -> None:
        """删除整个实体及其历史."""

    @abstractmethod
    async def list_by_type(
        self, entity_type: str, *, limit: int = 100
    ) -> list[EntityMemoryEntry]:
        """按类型列出所有实体."""
