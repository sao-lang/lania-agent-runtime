"""
SessionStartHook——session_start Transform。

加载或创建会话记录，恢复历史消息与 step 游标到 Runtime。
只依赖 SessionServiceProtocol；RuntimeContext 仅在 TYPE_CHECKING 下引用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.session._config import SessionConfig
from src.session._protocols import SessionServiceProtocol

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext

logger = logging.getLogger(__name__)


class SessionStartHook:
    """session_start Transform：加载或创建会话，恢复历史消息与 step 游标。"""

    def __init__(
        self,
        service: SessionServiceProtocol,
        config: SessionConfig | None = None,
    ) -> None:
        """初始化 SessionStartHook。

        Args:
            service: 满足 SessionServiceProtocol 的会话服务。
            config: 会话配置。不提供则使用默认配置。
        """
        self._service = service
        self._config = config or SessionConfig()

    async def __call__(self, data: Any, ctx: RuntimeContext) -> Any:
        """Transform 调用入口。

        流程：
        1. 读取会话记录；不存在则创建
        2. 恢复历史消息与 step 游标（set_messages / set_step_index）

        Args:
            data: Transform 数据（session_start 事件字典）。
            ctx: RuntimeContext 只读快照。

        Returns:
            原样返回 data。
        """
        if not self._config.enabled:
            return data
        try:
            record = await self._service.get(ctx.session_id)
            if record is None:
                title = ""
                if self._config.auto_title:
                    raw_input = data.get("input") if isinstance(data, dict) else None
                    title = str(raw_input or "").strip()[:30]
                record = await self._service.create(
                    ctx.session_id,
                    agent_id=ctx.agent_id,
                    user_id=ctx.services.get(self._config.user_id_key),
                    title=title,
                )

            messages = getattr(record, "messages", None) or []
            if messages and self._config.persist_messages:
                ctx.set_messages(messages)
                ctx.set_step_index(getattr(record, "step_index", 0))
        except Exception:
            logger.warning("SessionStartHook 异常", exc_info=True)
        return data
