"""MemoryRecallHook: before_step Transform.

设计文档: memory-system-design.md §7.3
在每次 step 前将记忆注入 contextPayload.
"""

from __future__ import annotations

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.memory.service import MemoryService


class MemoryRecallHook:
    """before_step Transform: 注入记忆到 contextPayload."""

    def __init__(self, memory_service: MemoryService) -> None:
        self._memory = memory_service

    async def __call__(self, data: dict, ctx: RuntimeContext) -> dict:
        """执行记忆召回, 注入 ctx.contextPayload."""
        if not isinstance(data, dict):
            return data

        last_content = ctx.messages[-1].get("content", "") if ctx.messages else ""
        payload = await self._memory.recall(
            session_id=ctx.session_id,
            user_id=ctx.services.get("user_id"),
            query=last_content,
            max_tokens=ctx.budget.token_limit,
        )
        if payload.memories:
            ctx.context_payload.memories = payload.memories
        if payload.rag_documents:
            ctx.context_payload.rag_documents = payload.rag_documents
        if payload.concepts:
            ctx.context_payload.concepts = payload.concepts
        if payload.entity_profile:
            ctx.context_payload.entity_profile = payload.entity_profile
        if payload.tone_instruction:
            ctx.context_payload.tone_instruction = payload.tone_instruction

        return data
