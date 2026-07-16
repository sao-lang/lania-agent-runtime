"""Layer 1: 工作记忆存储接口."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lania_agent_runtime.models import WorkingMemorySnapshot


class WorkingMemoryStore(ABC):
    """工作记忆存储接口 (Layer 1).

    特性:
    - 覆盖写 (一个 session 只保留最新快照)
    - TTL 自动过期
    """

    @abstractmethod
    async def save_working_memory(self, snapshot: WorkingMemorySnapshot) -> None:
        """保存工作记忆快照 (覆盖写)."""

    @abstractmethod
    async def load_working_memory(self, session_id: str) -> WorkingMemorySnapshot | None:
        """加载工作记忆快照. 返回 None 表示已过期或不存在."""

    @abstractmethod
    async def delete_working_memory(self, session_id: str) -> None:
        """删除工作记忆快照."""

    @abstractmethod
    async def exists_working_memory(self, session_id: str) -> bool:
        """检查工作记忆快照是否存在且未过期."""
