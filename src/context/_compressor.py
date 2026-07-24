"""
Compressor——上下文压缩机制。

实现分层降级策略：根据可用 token 预算决定注入哪几层记忆数据。
接收 RawContext + SelectionDecision，输出 ContextPayload。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.context._budget import TokenManager
from src.context._models import RawContext, SelectionDecision
from src.runtime.context._payload import ContextPayload

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext


class LEVEL:
    """分层降级级别常量。"""
    L1 = 1  # 原始消息 + 摘要 + 实体 + 行为
    L2 = 2  # 摘要 + 实体 + 行为
    L3 = 3  # 关键事实 + 行为
    L4 = 4  # 仅行为


class Compressor:
    """
    上下文压缩机制：分层降级 + 记忆选取 + 截断。

    根据可用 token 预算选择层级（L1-L4），
    按重要性选取记忆，排除已去重的条目。
    """

    def __init__(self, token_manager: TokenManager | None = None) -> None:
        """
        初始化 Compressor。

        Args:
            token_manager: TokenManager 实例。不提供则创建默认实例。
        """
        self._token_manager = token_manager or TokenManager()

    async def compress(
        self,
        raw: RawContext,
        decision: SelectionDecision,
        ctx: RuntimeContext,
        *,
        force_level: int = 0,
    ) -> ContextPayload:
        """
        根据可用 token 和选取决策，构建 ContextPayload。

        Args:
            raw: MemoryService.recall_raw 返回的裸数据。
            decision: Selector 的选取决策。
            ctx: RuntimeContext 只读快照。
            force_level: 强制指定压缩层级。0 表示自动选择。

        Returns:
            构建好的 ContextPayload（尚未经过 BudgetController 裁剪）。
        """
        available = self._estimate_available(ctx)
        level = force_level if force_level > 0 else self._select_level(available)

        # 构建 system_prompt
        system_prompt = self._get_system_prompt(ctx)

        payload = ContextPayload(
            system_prompt=system_prompt,
            max_tokens=available,
        )

        # 所有层级都注入行为模式（几乎不占 token）
        if raw.tone_instruction:
            payload.injected_context.append(raw.tone_instruction)

        # L1-L3: 注入实体画像 + 概念
        if level <= LEVEL.L3:
            if raw.entity_profile:
                profile_str = self._format_entity_profile(raw.entity_profile)
                if profile_str:
                    payload.injected_context.append(f"[用户画像]\n{profile_str}")

            if raw.concepts:
                concepts_str = "\n".join(
                    f"- {c.get('name', '')}: {c.get('description', '')}"
                    for c in raw.concepts
                )
                payload.injected_context.append(f"[相关概念]\n{concepts_str}")

        # L1-L2: 注入情景记忆摘要
        if level <= LEVEL.L2:
            selected_memories = self._select_memories(
                raw.episodic_memories,
                decision,
                available // 2,
            )
            payload.memories = selected_memories

        # L1: 原始消息已在 ctx.messages 中，由 Selector 保留
        # Serializer 阶段会处理 keep_from_index 之后的消息

        return payload

    def _estimate_available(self, ctx: RuntimeContext) -> int:
        """
        估算可用 token。

        Args:
            ctx: RuntimeContext。

        Returns:
            可用 token 数。
        """
        # 从 ctx.budget 获取 token 限制
        token_limit = ctx.budget.token_limit if ctx.budget else 0
        if token_limit > 0:
            return token_limit
        # 默认值
        return 4096

    def _select_level(self, available: int) -> int:
        """
        根据 token 预算选择层级。

        Args:
            available: 可用 token 数。

        Returns:
            层级（1-4）。
        """
        if available > 20000:
            return LEVEL.L1
        elif available > 8000:
            return LEVEL.L2
        elif available > 2000:
            return LEVEL.L3
        else:
            return LEVEL.L4

    def _select_memories(
        self,
        episodic_memories: list,
        decision: SelectionDecision,
        budget: int,
    ) -> list[Any]:
        """
        选择注入的记忆，排除被截断轮次的重复记忆。

        策略：
        1. 排除与保留原始消息重叠的记忆（按 turn_index）
        2. 优先选被裁轮次的记忆（补偿）
        3. 按重要性降序取前 N 条
        4. 按 token 预算截断

        Args:
            episodic_memories: 情景记忆条目列表。
            decision: 选取决策。
            budget: 记忆部分的 token 预算。

        Returns:
            选中的记忆条目列表。
        """
        if not episodic_memories:
            return []

        # 1. 排除与保留消息重叠的记忆
        candidates = [
            m for m in episodic_memories
            if m.turn_index not in decision.dedup_turn_indices
        ]

        if not candidates:
            return []

        # 2. 计算被裁轮次的范围
        cropped_indices: set[int] = set()
        for start, end in decision.cropped_ranges:
            cropped_indices.update(range(start, end + 1))

        # 被裁轮次的记忆优先
        cropped_memories = [
            m for m in candidates if m.turn_index in cropped_indices
        ]
        other_memories = [
            m for m in candidates if m.turn_index not in cropped_indices
        ]

        # 3. 按重要性排序
        cropped_memories.sort(key=lambda m: m.importance, reverse=True)
        other_memories.sort(key=lambda m: m.importance, reverse=True)
        ordered = cropped_memories + other_memories

        # 4. 按 token 预算截断
        result: list[Any] = []
        used = 0
        for memory in ordered:
            tokens = self._token_manager.estimate_tokens(
                getattr(memory, "summary", str(memory))
            )
            if used + tokens > budget and result:
                break
            result.append(memory)
            used += tokens

        return result

    def _get_system_prompt(self, ctx: RuntimeContext) -> str:
        """
        从 RuntimeContext 获取 system prompt。

        Args:
            ctx: RuntimeContext。

        Returns:
            system prompt 文本。
        """
        messages = list(ctx.messages)
        if messages and messages[0].get("role") == "system":
            return messages[0].get("content", "")
        return ""

    def _format_entity_profile(self, profile: dict) -> str:
        """
        格式化实体画像为文本。

        Args:
            profile: 实体画像字典。

        Returns:
            格式化的文本。
        """
        lines: list[str] = []
        for attr_name, attr_data in profile.items():
            value = attr_data
            if hasattr(attr_data, "value"):
                value = attr_data.value
            lines.append(f"  {attr_name}: {value}")
        return "\n".join(lines)
