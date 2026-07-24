"""
BehavioralPatternStore——行为模式存储适配器。

基于 MemoryPersistence 实现，键名前缀 bp:{user_id}。
特性：
- 每个用户一行
- 全量覆盖写（收敛后替换整个 patterns）
- 低频读写
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.memory._persistence import MemoryPersistence
from src.memory._types import BehavioralPattern


class BehavioralPatternStore:
    """
    行为模式存储适配器。

    将 BehavioralPattern 的读写转化为 MemoryPersistence 的键值操作。
    键名格式: bp:{user_id}
    """

    def __init__(self, persistence: MemoryPersistence) -> None:
        """
        初始化 BehavioralPatternStore。

        Args:
            persistence: MemoryPersistence 实例。
        """
        self._store = persistence

    def _key(self, user_id: str) -> str:
        return f"bp:{user_id}"

    def _serialize(self, pattern: BehavioralPattern) -> bytes:
        data: dict[str, Any] = {
            "user_id": pattern.user_id,
            "patterns": pattern.patterns,
            "total_interactions": pattern.total_interactions,
            "version": pattern.version,
            "last_converged_at": (
                pattern.last_converged_at.isoformat()
                if pattern.last_converged_at else None
            ),
            "last_interaction_at": (
                pattern.last_interaction_at.isoformat()
                if pattern.last_interaction_at else None
            ),
            "created_at": (
                pattern.created_at.isoformat()
                if pattern.created_at else None
            ),
        }
        return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")

    def _deserialize(self, data: bytes) -> BehavioralPattern | None:
        try:
            raw = json.loads(data.decode("utf-8"))
            return BehavioralPattern(
                user_id=raw.get("user_id", ""),
                patterns=raw.get("patterns", {}),
                total_interactions=raw.get("total_interactions", 0),
                version=raw.get("version", 1),
                last_converged_at=(
                    datetime.fromisoformat(raw["last_converged_at"])
                    if raw.get("last_converged_at") else None
                ),
                last_interaction_at=(
                    datetime.fromisoformat(raw["last_interaction_at"])
                    if raw.get("last_interaction_at") else None
                ),
                created_at=(
                    datetime.fromisoformat(raw["created_at"])
                    if raw.get("created_at") else None
                ),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    async def read(self, user_id: str) -> BehavioralPattern | None:
        """
        读取用户的行为模式。

        Args:
            user_id: 用户 ID。

        Returns:
            行为模式，不存在则返回 None。
        """
        data = await self._store.get(self._key(user_id))
        if data is None:
            return None
        return self._deserialize(data)

    async def write(self, pattern: BehavioralPattern) -> None:
        """
        写入/覆盖用户行为模式。

        Args:
            pattern: 行为模式。
        """
        pattern.version += 1
        data = self._serialize(pattern)
        await self._store.put(self._key(pattern.user_id), data)

    async def delete(self, user_id: str) -> None:
        """
        删除用户行为模式。

        Args:
            user_id: 用户 ID。
        """
        await self._store.delete(self._key(user_id))
