"""
MemoryResumeHook——session_resume Transform（Phase 2，Memory 侧）。

从暂停/断点恢复时，把 wm: 中的执行断点（plan / budget / pause_state）
恢复到 Runtime。不恢复消息原文——原文由 SessionResumeHook 负责。
与 SessionResumeHook 并列注册于 Builder，两者互不调用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.memory._protocols import MemoryResumeProtocol

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext

logger = logging.getLogger(__name__)


class MemoryResumeHook:
    """session_resume Transform（Memory 侧）：恢复执行断点。"""

    def __init__(self, memory_service: MemoryResumeProtocol) -> None:
        """初始化 MemoryResumeHook。

        Args:
            memory_service: 满足 MemoryResumeProtocol 的记忆服务（MemoryService 实例）。
        """
        self._memory = memory_service

    async def __call__(self, data: Any, ctx: RuntimeContext) -> Any:
        """Transform 调用入口——恢复 plan / budget / pause_state。

        wm 快照仅在 step 边界（pause / error / checkpoint）触发，此时
        Session 已完成本轮提交，两者一致；本 Hook 不读取消息原文。

        Args:
            data: Transform 数据（session_resume 事件字典）。
            ctx: RuntimeContext 只读快照。

        Returns:
            原样返回 data。
        """
        try:
            snapshot = await self._memory.restore(ctx.session_id)
            if snapshot is None:
                return data
            if snapshot.plan is not None:
                ctx.set_plan(dict(snapshot.plan))
            ctx.set_budget(snapshot.budget)
            ctx.set_pause_state(
                {
                    "is_paused": snapshot.pause_state.is_paused,
                    "pending_approvals": list(snapshot.pause_state.pending_approvals),
                    "resume_token": snapshot.pause_state.resume_token or "",
                }
            )
        except Exception:
            logger.warning("MemoryResumeHook 异常", exc_info=True)
        return data
