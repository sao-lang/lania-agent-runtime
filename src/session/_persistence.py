"""
会话持久化后端接口定义。

SessionPersistence 与 MemoryPersistence 完全同构（4 个方法），
因此任何已实现 MemoryPersistence 的实例（如 SQLitePersistence）
天然满足此接口（duck typing）。共享后端实例不构成组件耦合——
两者按各自 key 前缀（ss: vs wm:/ep:）隔离读写。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SessionPersistence(ABC):
    """会话持久化后端接口——SessionStore 内部使用。"""

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """读取 key 对应的字节数据。"""

    @abstractmethod
    async def put(self, key: str, value: bytes) -> None:
        """写入 key 对应的字节数据。"""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """删除 key 对应的数据。"""

    @abstractmethod
    async def list_keys(self, prefix: str) -> list[str]:
        """列出指定前缀下的所有 key。"""
