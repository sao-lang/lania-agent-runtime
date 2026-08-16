"""
SessionCommitHook——after_step Transform。

把本轮完整对话消息增量提交到会话历史（唯一事实源）。
system prompt 属运行时配置、不入历史（由 SessionService 在存储层过滤）。
与 MemoryCommitHook 并列注册（Builder 按优先级：Session 400 → Memory 500），
两者互不调用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.session._config import SessionConfig
from src.session._protocols import SessionServiceProtocol

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext

logger = logging.getLogger(__name__)


class SessionCommitHook:
    """after_step Transform：把本轮对话消息增量提交到会话历史（唯一事实源）。"""

    def __init__(
        self,
        service: SessionServiceProtocol,
        config: SessionConfig | None = None,
    ) -> None:
        """初始化 SessionCommitHook。

        Args:
            service: 满足 SessionServiceProtocol 的会话服务。
            config: 会话配置。不提供则使用默认配置。
        """
        self._service = service
        self._config = config or SessionConfig()

    async def __call__(self, data: Any, ctx: RuntimeContext) -> Any:
        """Transform 调用入口——增量提交本轮消息。

        Args:
            data: Transform 数据。
            ctx: RuntimeContext 只读快照。

        Returns:
            原样返回 data。
        """
        if not self._config.enabled or not self._config.persist_messages:
            return data
        try:
            await self._service.append_messages(
                ctx.session_id,
                list(ctx.messages),
                step_index=ctx.step_index,
            )
        except Exception:
            logger.warning("SessionCommitHook 写入失败", exc_info=True)
        return data
