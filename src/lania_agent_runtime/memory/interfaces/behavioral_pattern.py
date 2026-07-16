"""Layer 5: 行为模式存储接口."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from lania_agent_runtime.models import BehavioralPattern


class BehavioralStore(ABC):
    """行为模式存储接口 (Layer 5).

    特性:
    - 每个用户一行
    - 全量覆盖写 (收敛后替换整个 patterns)
    - 低频读写
    """

    @abstractmethod
    async def upsert_behavioral_pattern(
        self, user_id: str, patterns: dict[str, Any]
    ) -> None:
        """写入/覆盖用户行为模式. version 自增."""

    @abstractmethod
    async def get_behavioral_pattern(self, user_id: str) -> BehavioralPattern | None:
        """读取用户行为模式."""

    @abstractmethod
    async def delete_behavioral_pattern(self, user_id: str) -> None:
        """删除用户行为模式."""

    @abstractmethod
    async def acquire_lock(self, user_id: str, ttl: int = 30) -> bool:
        """获取用户级锁(防止并发收敛冲突). 返回 True 表示获取成功."""
