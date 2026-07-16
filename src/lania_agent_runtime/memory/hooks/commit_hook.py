"""MemoryCommitHook: after_step Transform.

设计文档: memory-system-design.md §7.3
在每次 step 后将记忆写入持久化存储.
"""

from __future__ import annotations

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.memory.gate import MemoryCommitGate
from lania_agent_runtime.memory.service import MemoryService


class MemoryCommitHook:
    """after_step Transform: 写入记忆到持久化存储."""

    def __init__(
        self,
        memory_service: MemoryService,
        gate: MemoryCommitGate | None = None,
    ) -> None:
        self._memory = memory_service
        self._gate = gate or MemoryCommitGate()

    async def __call__(self, data: dict, ctx: RuntimeContext) -> dict:
        """执行记忆提交."""
        if not isinstance(data, dict):
            return data

        # 提取最后一条 user + assistant 消息
        last_user = None
        last_assistant = None
        last_tool_calls: list[dict] | None = None
        for m in reversed(ctx.messages):
            if m.get("role") == "assistant" and last_assistant is None:
                last_assistant = m.get("content", "")
                raw_tcs = m.get("tool_calls", [])
                if raw_tcs:
                    last_tool_calls = [
                        {
                            "name": tc.get("name", tc.get("function", {}).get("name", "")),
                            "arguments": tc.get("arguments", {}),
                        }
                        for tc in raw_tcs
                    ]
            elif m.get("role") == "user" and last_user is None:
                last_user = m.get("content", "")
            if last_user and last_assistant:
                break

        if last_user and last_assistant:
            # 门控判断
            decision = await self._gate.evaluate(last_user, last_assistant)

            await self._memory.commit(
                ctx.session_id,
                ctx.services.get("user_id"),
                last_user,
                last_assistant,
                tool_calls=last_tool_calls,
                gate_decision=decision,
            )

        return data
