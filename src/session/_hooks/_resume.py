"""
SessionResumeHook——session_resume Transform（Phase 2）。

从暂停/断点恢复时，把 ss: 中的历史消息与 step 游标恢复到 Runtime。
与 MemoryResumeHook（执行断点）并列注册于 Builder，两者互不调用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.session._config import SessionConfig
from src.session._protocols import SessionServiceProtocol

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext

logger = logging.getLogger(__name__)


class SessionResumeHook:
    """session_resume Transform：恢复历史消息与 step 游标。"""

    def __init__(
        self,
        service: SessionServiceProtocol,
        config: SessionConfig | None = None,
    ) -> None:
        """初始化 SessionResumeHook。

        Args:
            service: 满足 SessionServiceProtocol 的会话服务。
            config: 会话配置。不提供则使用默认配置。
        """
        self._service = service
        self._config = config or SessionConfig()

    async def __call__(self, data: Any, ctx: RuntimeContext) -> Any:
        """Transform 调用入口——恢复历史消息与 step 游标。

        Args:
            data: Transform 数据（session_resume 事件字典）。
            ctx: RuntimeContext 只读快照。

        Returns:
            原样返回 data。
        """
        if not self._config.enabled:
            return data
        try:
            record = await self._service.get(ctx.session_id)
            messages = getattr(record, "messages", None) or []
            if messages and self._config.persist_messages:
                ctx.set_messages(messages)
                ctx.set_step_index(getattr(record, "step_index", 0))
        except Exception:
            logger.warning("SessionResumeHook 异常", exc_info=True)
        return data
