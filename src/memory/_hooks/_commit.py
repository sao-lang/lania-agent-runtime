"""
MemoryCommitHook——after_step Transform 记忆写入 Hook。

将本轮对话写入持久化记忆（情景记忆 / 实体记忆 / 行为模式采样）。
通过 MemoryCommitGate 判断信息价值，仅写入有价值的对话。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.memory._management._gate import MemoryCommitGate
from src.memory._types import StepContext

if TYPE_CHECKING:
    from src.context._protocols import MemoryCommitProtocol
    from src.runtime.context._context import RuntimeContext

logger = logging.getLogger(__name__)


class MemoryCommitHook:
    """
    after_step Transform：写入本轮对话到持久化记忆。

    在每步执行完成后触发，将用户消息、助理回复和工具调用结果
    写入情景记忆（Layer 2），并异步触发实体提取和行为模式采样（Layer 3-5）。
    """

    def __init__(
        self,
        memory_service: MemoryCommitProtocol,
        gate: MemoryCommitGate | None = None,
    ) -> None:
        """
        初始化 MemoryCommitHook。

        Args:
            memory_service: MemoryService 实例。
            gate: 记忆写入门控。不提供则使用默认门控。
        """
        self._memory = memory_service
        self._gate = gate or MemoryCommitGate()

    async def __call__(self, data: Any, ctx: RuntimeContext) -> Any:
        """
        Transform 调用入口——将本轮对话提交到记忆系统。

        流程：
        1. 从 ctx.messages 提取本轮用户/助理消息
        2. Gate 判断是否值得记录
        3. 构建 StepContext 并写入

        Args:
            data: Transform 数据。
            ctx: RuntimeContext 只读快照。

        Returns:
            原样返回 data。
        """
        try:
            messages = list(ctx.messages)
            if not messages:
                return data

            # 找到最后一轮用户消息和助理消息
            # 从末尾开始查找，先找到最后一条 assistant 消息，
            # 再找它之前最近的一条 user 消息，确保来自同一轮次
            assistant_message = None
            user_message = None
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and assistant_message is None:
                    assistant_message = msg.get("content", "")
                if (assistant_message is not None
                        and msg.get("role") == "user"
                        and user_message is None):
                    user_message = msg.get("content", "")
                    break

            # Gate 判断
            decision = await self._gate.evaluate(user_message, assistant_message)
            if not decision.should_record:
                return data

            # 构建 StepContext
            _raw_content = str(user_message or "") + "\n" + str(assistant_message or "")
            step_ctx = StepContext(
                user_message=user_message,
                assistant_message=assistant_message,
                turn_index=ctx.step_index,
                session_id=ctx.session_id,
                user_id=ctx.services.get("user_id"),
                importance=decision.importance,
                summary=(
                    (user_message or "")[:200]
                    + (" | " + (assistant_message or "")[:200] if assistant_message else "")
                ),
                raw=_raw_content[:16384],  # 限制 16KB
            )

        except Exception:
            logger.warning("MemoryCommitHook 异常", exc_info=True)
            return data

        try:
            # 提交到记忆系统
            await self._memory.commit(
                session_id=ctx.session_id,
                user_id=ctx.services.get("user_id"),
                step_context=step_ctx,
            )

        except Exception as e:
            logger.warning(
                "MemoryCommitHook 写入失败: %s: %s", type(e).__name__, e,
                exc_info=True,
            )

        return data
