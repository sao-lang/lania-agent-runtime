"""Layer 2: 情景记忆存储接口."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lania_agent_runtime.models import EpisodicMemoryEntry


class EpisodicStore(ABC):
    """情景记忆存储接口 (Layer 2).

    特性:
    - append-only (写入后不修改, 仅 merged_to 字段可更新)
    - 时间序索引 + 标签索引
    - 支持按实体/话题检索
    """

    @abstractmethod
    async def write(self, entry: EpisodicMemoryEntry) -> str:
        """写入一条情景记忆, 返回 entry.id."""

    @abstractmethod
    async def write_batch(self, entries: list[EpisodicMemoryEntry]) -> list[str]:
        """批量写入情景记忆, 返回 ID 列表."""

    @abstractmethod
    async def recall_session(
        self,
        session_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        min_importance: float = 0.0,
    ) -> list[EpisodicMemoryEntry]:
        """按 session 召回, 按 turn_index DESC 排序, 可选最低重要性过滤."""

    @abstractmethod
    async def recall_user(
        self,
        user_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        min_importance: float = 0.0,
        since: str | None = None,
    ) -> list[EpisodicMemoryEntry]:
        """按用户跨 session 召回, 按 created_at DESC, 可选起始时间和重要性."""

    @abstractmethod
    async def search_by_entities(
        self,
        user_id: str,
        entities: list[str],
        *,
        limit: int = 10,
    ) -> list[EpisodicMemoryEntry]:
        """按实体标签召回记忆."""

    @abstractmethod
    async def search_by_topics(
        self,
        user_id: str,
        topics: list[str],
        *,
        limit: int = 10,
    ) -> list[EpisodicMemoryEntry]:
        """按话题标签召回记忆."""

    @abstractmethod
    async def count_session(self, session_id: str) -> int:
        """统计 session 中的记录数."""

    @abstractmethod
    async def mark_merged(self, entry_id: str, merged_to_id: str) -> None:
        """标记一条记录已被合并到另一条."""

    @abstractmethod
    async def delete_before(self, user_id: str, before: str) -> int:
        """删除指定时间之前的记录(遗忘), 返回删除数. 不会删除已被合并的记录."""

    @abstractmethod
    async def get_unmerged_raw(
        self, session_id: str, *, limit: int = 50
    ) -> list[EpisodicMemoryEntry]:
        """获取未合并的原始记录, 按 turn_index ASC 排序."""
