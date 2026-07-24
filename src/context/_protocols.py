"""
Context 与外部组件的协议接口定义。

定义 MemoryRecallProtocol 和 MemoryCommitProtocol，
允许 ContextManager 和 MemoryCommitHook 依赖协议而非具体实现。

设计原则：
  - 协议只声明方法签名，不引用外部的数据类型
  - 返回/参数类型用 Any，数据映射在调用方完成
  - MemoryService 天然满足这两个协议（duck typing，无需额外继承）

这样 src.context 和 src.memory 两个包之间零导入、零耦合。
"""

from __future__ import annotations

from typing import Any, Protocol


class MemoryRecallProtocol(Protocol):
    """ContextManager 需要的记忆召回接口。

    由 MemoryService 或其他实现此 Protocol 的类满足。
    返回值的字段在 ContextManager._load() 中解构使用。
    """

    async def recall_raw(
        self,
        session_id: str,
        user_id: str | None = None,
        query: str = "",
        *,
        turn_ranges: list[tuple[int, int]] | None = None,
        max_memories: int = 20,
    ) -> Any:
        """返回裸数据供 ContextManager 使用。

        Args:
            session_id: 会话 ID。
            user_id: 用户 ID。
            query: 当前查询文本（用于语义检索）。
            turn_ranges: 指定检索哪些 turn_index 范围的记忆。
            max_memories: 最大记忆条数。

        Returns:
            对象需包含 episodic_memories, entity_profile, concepts, tone_instruction 四个字段。
        """
        ...


class MemoryCommitProtocol(Protocol):
    """MemoryCommitHook 需要的记忆写入接口。

    由 MemoryService 或其他实现此 Protocol 的类满足。
    """

    async def commit(
        self,
        session_id: str,
        user_id: str | None = None,
        step_context: Any | None = None,
    ) -> None:
        """将本轮对话写入持久化记忆。

        Args:
            session_id: 会话 ID。
            user_id: 用户 ID。
            step_context: 步骤上下文（含用户消息/助理回复等）。
        """
        ...
