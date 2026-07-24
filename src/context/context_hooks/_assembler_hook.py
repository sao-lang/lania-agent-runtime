"""
ContextAssemblerHook——before_llm Transform 上下文编排入口。

挂载在 BEFORE_LLM，内部调用 ContextManager.assemble() 执行五阶段管线：
SELECT → LOAD → COMPRESS → BUDGET → SERIALIZE。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.context._manager import ContextManager
    from src.runtime.context._context import RuntimeContext


class ContextAssemblerHook:
    """
    before_llm Transform：上下文编排入口。

    替换原有的 MemoryRecallHook（BEFORE_STEP）。
    挂载在 BEFORE_LLM，因为需要拿到 user_message 作为 query。

    调用 ContextManager.assemble() 执行五阶段管线，
    将组装好的 messages 写回 data 供 Runtime 消费。
    """

    def __init__(self, manager: ContextManager) -> None:
        """
        初始化 ContextAssemblerHook。

        Args:
            manager: ContextManager 实例，负责五阶段编排。
        """
        self._manager = manager

    async def __call__(self, data: Any, ctx: RuntimeContext) -> Any:
        """
        Transform 调用入口。

        执行五阶段管线并将组装好的 messages 存入
        data.assembled_messages，供 Runtime 的 _execute_llm_step
        在序列化阶段直接使用。

        Args:
            data: ContextPayload 实例。
            ctx: RuntimeContext 只读快照。

        Returns:
            原样返回 data（不做修改）。
        """
        llm_messages = await self._manager.assemble(ctx)
        # 存入 data.assembled_messages，Runtime 会检查此字段
        data.assembled_messages = llm_messages
        return data
