"""
SessionEndHook——session_end Transform。

归档会话元数据与统计（状态 / token / step / last_error）。
消息已在 step 间由 SessionCommitHook 提交，此处只 finalize。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.session._protocols import SessionServiceProtocol

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext

logger = logging.getLogger(__name__)


class SessionEndHook:
    """session_end Transform：归档元数据与统计。"""

    def __init__(self, service: SessionServiceProtocol) -> None:
        """初始化 SessionEndHook。

        Args:
            service: 满足 SessionServiceProtocol 的会话服务。
        """
        self._service = service

    async def __call__(self, data: Any, ctx: RuntimeContext) -> Any:
        """Transform 调用入口——finalize 会话记录。

        Args:
            data: Transform 数据（session_end 事件字典，含 status / last_error）。
            ctx: RuntimeContext 只读快照。

        Returns:
            原样返回 data。
        """
        try:
            status = data.get("status", "ended") if isinstance(data, dict) else "ended"
            last_error = data.get("last_error") if isinstance(data, dict) else None
            await self._service.finalize(
                ctx.session_id,
                status=status,
                token_used=ctx.budget.token_used,
                step_count=ctx.step_index,
                last_error=last_error,
            )
        except Exception:
            logger.warning("SessionEndHook 归档失败", exc_info=True)
        return data
