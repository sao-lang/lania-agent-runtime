"""SessionCleanupHook: session_end Transform.

设计文档: memory-system-design.md §7.2
会话结束时清理工作记忆快照并触发遗忘.
"""

from __future__ import annotations

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.memory.eviction import EvictionManager
from lania_agent_runtime.memory.service import MemoryService


class SessionCleanupHook:
    """session_end Transform: 清理快照 + 触发遗忘."""

    def __init__(
        self,
        memory_service: MemoryService,
        evictor: EvictionManager | None = None,
    ) -> None:
        self._memory = memory_service
        self._evictor = evictor

    async def __call__(self, data: dict, ctx: RuntimeContext) -> dict:
        """执行会话清理."""
        # 丢弃工作记忆快照
        await self._memory.discard_checkpoint(ctx.session_id)

        # 触发遗忘
        user_id = ctx.services.get("user_id") if isinstance(ctx.services, dict) else None
        if self._evictor and user_id:
            await self._evictor.evict_expired(user_id)

        return data
