"""
记忆持久化接口——MemoryPersistence ABC。

用户只需实现 4 个方法（get / put / delete / list_keys），
MemoryService 在内部处理序列化（dict ↔ bytes）、键名约定和复杂查询逻辑，
覆盖全部 5 层记忆的持久化需求。

MemoryService 内部使用的键名约定（用户无需关心，仅供参考）：
  wm:{session_id}                         → Working Memory
  ep:{session_id}:{turn_index}:{entry_id}  → Episodic
  en:{entity_type}:{entity_key}             → Entity
  sn:{node_id}                             → Semantic Node
  se:{source_id}:{target_id}:{relation}    → Semantic Edge
  bp:{user_id}                             → Behavioral Pattern
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class MemoryPersistence(ABC):
    """
    记忆持久化后端接口——用户实现此接口，MemoryService 内部使用。

    只需实现 4 个基本方法，MemoryService 在内部处理序列化（dict ↔ bytes）、
    键名约定和复杂查询逻辑，覆盖全部 5 层记忆的持久化需求。
    """

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """
        读取原始字节数据。

        Args:
            key: 存储键名。

        Returns:
            字节数据，如果键不存在则返回 None。
        """
        ...

    @abstractmethod
    async def put(self, key: str, value: bytes) -> None:
        """
        写入原始字节数据（覆盖写）。

        Args:
            key: 存储键名。
            value: 要写入的字节数据。
        """
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """
        删除单个键。

        如果键不存在，静默忽略。

        Args:
            key: 要删除的存储键名。
        """
        ...

    @abstractmethod
    async def list_keys(self, prefix: str) -> list[str]:
        """
        按前缀列出所有匹配的键（用于扫描和查询）。

        Args:
            prefix: 键名前缀。

        Returns:
            匹配前缀的所有键名列表。
        """
        ...
