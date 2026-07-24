"""
ContextManager——上下文管理统一入口。

编排五阶段管线：SELECT → LOAD → COMPRESS → BUDGET → SERIALIZE。
单一入口 assemble(ctx) 被 ContextAssemblerHook 调用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.context._budget import BudgetController, TokenManager
from src.context._compressor import Compressor
from src.context._config import ContextConfig
from src.context._models import RawContext, SelectionDecision
from src.context._selector import Selector
from src.runtime.context._serializer import DefaultSerializer, MessageSerializer

if TYPE_CHECKING:
    from src.memory._service import MemoryService
    from src.runtime.context._context import RuntimeContext


class ContextManager:
    """
    上下文管理统一入口。

    编排五阶段管线：SELECT → LOAD → COMPRESS → BUDGET → SERIALIZE。
    被 ContextAssemblerHook 在 before_llm 时调用。
    """

    def __init__(
        self,
        memory: MemoryService,
        selector: Selector | None = None,
        compressor: Compressor | None = None,
        budget_controller: BudgetController | None = None,
        serializer: MessageSerializer | None = None,
        config: ContextConfig | None = None,
    ) -> None:
        """
        初始化 ContextManager。

        Args:
            memory: MemoryService 实例（唯一的外部依赖）。
            selector: 选取策略。不提供则使用默认 Selector。
            compressor: 压缩机制。不提供则使用默认 Compressor。
            budget_controller: 预算执行器。不提供则使用默认 BudgetController。
            serializer: 消息序列化器。不提供则使用 DefaultSerializer。
            config: 上下文管理配置。不提供则使用默认配置。
        """
        self._memory = memory
        self._selector = selector or Selector()
        tm = TokenManager()
        self._compressor = compressor or Compressor(token_manager=tm)
        self._budget = budget_controller or BudgetController(token_manager=tm)
        self._serializer = serializer or DefaultSerializer()
        self._config = config or ContextConfig()

    async def assemble(self, ctx: RuntimeContext) -> list[dict]:
        """
        五阶段编排，返回 llm_messages。

        Args:
            ctx: RuntimeContext 只读快照。

        Returns:
            messages 列表，可直接传入 LLM API。
        """
        # Phase 1: SELECT——选取保留的原始消息
        decision = await self._selector.select(ctx, self._config)

        # Phase 2: LOAD——从 MemoryService 加载裸数据
        raw = await self._load(decision, ctx)

        # Phase 3: COMPRESS——构建 ContextPayload
        payload = await self._compressor.compress(raw, decision, ctx)

        # Phase 4: BUDGET——预算裁剪
        raw_messages = self._get_raw_messages(ctx, decision)
        payload = await self._budget.apply(payload, raw_messages, self._config)

        # Phase 5: SERIALIZE——转换为 messages
        return await self._serialize(payload, decision, ctx)

    async def _load(
        self,
        decision: SelectionDecision,
        ctx: RuntimeContext,
    ) -> RawContext:
        """
        Phase 2: 从 MemoryService 加载各层记忆数据。

        Args:
            decision: 选取决策。
            ctx: RuntimeContext。

        Returns:
            RawContext 裸数据。
        """
        # 从用户消息中提取查询文本（用于语义检索）
        messages = list(ctx.messages)
        query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                query = msg.get("content", "") or ""
                break

        # 从 decision 中获取被裁轮次的 turn 范围
        turn_ranges = decision.cropped_ranges if decision.cropped_ranges else None

        # 调用 MemoryService.recall_raw()
        result = await self._memory.recall_raw(
            session_id=ctx.session_id,
            user_id=ctx.services.get("user_id"),
            query=query,
            turn_ranges=turn_ranges,
            max_memories=self._config.max_memories,
        )

        return RawContext(
            episodic_memories=result.episodic_memories,
            entity_profile=result.entity_profile,
            concepts=result.concepts,
            tone_instruction=result.tone_instruction,
        )

    def _get_raw_messages(
        self,
        ctx: RuntimeContext,
        decision: SelectionDecision,
    ) -> list[dict]:
        """
        获取 Selector 决定保留的原始消息。

        Args:
            ctx: RuntimeContext。
            decision: 选取决策。

        Returns:
            保留的原始消息列表。
        """
        messages = list(ctx.messages)
        from_idx = decision.keep_from_index
        if from_idx < len(messages):
            return messages[from_idx:]
        return []

    async def _serialize(
        self,
        payload: Any,
        decision: SelectionDecision,
        ctx: RuntimeContext,
    ) -> list[dict]:
        """
        Phase 5: 将 ContextPayload + 保留的原始消息 → llm_messages。

        Args:
            payload: BudgetController 裁剪后的 ContextPayload。
            decision: 选取决策。
            ctx: RuntimeContext。

        Returns:
            最终 messages 列表。
        """
        # 使用 DefaultSerializer 处理 payload → system message + history
        llm_messages = await self._serializer.serialize(payload)

        # 追加 Selector 保留但 Serializer 未包含的原始消息
        raw_messages = self._get_raw_messages(ctx, decision)
        for msg in raw_messages:
            role = msg.get("role", "")
            if role == "system":
                continue  # system 已由 serializer 处理
            # 避免重复添加 serializer 已包含的 history
            if role == "user" or role == "assistant" or role == "tool":
                llm_messages.append(dict(msg))

        return llm_messages
