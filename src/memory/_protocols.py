"""
记忆组件协议定义。

MemoryResumeProtocol 供 MemoryResumeHook 依赖——Hook 只依赖协议，
运行期不 import 具体服务实现，与 MemoryCommitProtocol 的用法一致。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.memory._types import WorkingMemorySnapshot


@runtime_checkable
class MemoryResumeProtocol(Protocol):
    """工作记忆断点恢复协议。"""

    async def restore(self, session_id: str) -> WorkingMemorySnapshot | None:
        """恢复指定会话的工作记忆快照。

        Args:
            session_id: 会话 ID。

        Returns:
            快照对象；不存在或已过期时返回 None。
        """
        ...
