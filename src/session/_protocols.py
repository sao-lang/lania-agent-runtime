"""
会话组件协议接口定义。

Session hooks 只依赖 SessionServiceProtocol（方法签名与 SessionService 一致，
返回类型用 Any），运行期不 import 任何其它组件。
"""

from __future__ import annotations

from typing import Any, Protocol


class SessionServiceProtocol(Protocol):
    """Session hooks 需要的会话服务接口。"""

    async def get(self, session_id: str) -> Any:
        """读取会话记录。"""

    async def create(
        self,
        session_id: str,
        *,
        agent_id: str = "",
        user_id: str | None = None,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """创建会话记录（幂等）。"""

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict],
        *,
        step_index: int | None = None,
    ) -> Any:
        """增量提交消息。"""

    async def finalize(
        self,
        session_id: str,
        *,
        status: str = "ended",
        token_used: int = 0,
        step_count: int = 0,
        last_error: str | None = None,
    ) -> Any:
        """结束会话并归档统计。"""
