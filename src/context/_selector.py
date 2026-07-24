"""
Selector——上下文选取策略。

实现滑动窗口选取和结构去重：
1. 从 ctx.messages 末尾解析完整轮次
2. 按 preserve_turns 保留最近 N 轮
3. 标记与保留消息重叠的记忆 ID，供 Compressor 去重
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.context._config import ContextConfig
from src.context._models import SelectionDecision

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext


class Selector:
    """
    上下文选取策略——滑动窗口 + 结构去重。

    负责决定 ctx.messages 中哪些原始消息应该保留，
    哪些记忆摘要需要去重。
    """

    async def select(
        self,
        ctx: RuntimeContext,
        config: ContextConfig,
    ) -> SelectionDecision:
        """
        执行选取策略，返回决策。

        Args:
            ctx: RuntimeContext 只读快照。
            config: 上下文管理配置。

        Returns:
            选取决策结果。
        """
        keep = self._apply_sliding_window(ctx, config)
        dedup = self._find_dedup_keys(ctx, keep, config)

        return SelectionDecision(
            preserve_message_count=keep["count"],
            cropped_ranges=keep["cropped_ranges"],
            keep_from_index=keep["from_index"],
            dedup_memory_ids=dedup["memory_ids"],
            dedup_turn_indices=dedup["turn_indices"],
        )

    def _apply_sliding_window(
        self,
        ctx: RuntimeContext,
        config: ContextConfig,
    ) -> dict:
        """
        滑动窗口裁剪 ctx.messages。

        规则：
        - 保留最后 N 轮完整对话（user + assistant ± tool_calls + tool results）
        - tool_call 与其 result 视为同一轮，不可分割
        - system message（index 0）始终保留

        Args:
            ctx: RuntimeContext 实例。
            config: 上下文管理配置。

        Returns:
            {"count": int, "cropped_ranges": list, "from_index": int}。
        """
        messages = list(ctx.messages)
        if not messages:
            return {"count": 0, "cropped_ranges": [], "from_index": 0}

        # System message 始终保留
        content_start = 1 if messages[0].get("role") == "system" else 0

        # 从末尾反向解析轮次
        # 一轮 = [user, assistant(±tool_calls), ±tool_results]
        turns: list[list[int]] = []  # 每轮包含的 message index 列表
        current_turn: list[int] = []
        i = len(messages) - 1

        while i >= content_start:
            msg = messages[i]
            role = msg.get("role", "")

            if role == "tool":
                # tool result → 附加到当前轮次
                current_turn.insert(0, i)
                i -= 1

            elif role == "assistant":
                # assistant → 开始/加入当前轮次
                current_turn.insert(0, i)
                has_tool_calls = bool(msg.get("tool_calls"))
                i -= 1

                if has_tool_calls and config.preserve_tool_context:
                    # 向前收集所有 tool result
                    while (
                        i >= content_start
                        and messages[i].get("role") == "tool"
                    ):
                        current_turn.insert(0, i)
                        i -= 1

                # 继续向前找对应的 user 消息
                while i >= content_start and messages[i].get("role") != "user":
                    # 跳过可能存在的中间消息
                    i -= 1

            elif role == "user":
                # user → 完成当前轮次
                current_turn.insert(0, i)
                turns.append(current_turn)
                current_turn = []
                i -= 1

            else:
                # 其他角色（非 system），不属于任何轮次，跳过
                if current_turn:
                    turns.append(current_turn)
                    current_turn = []
                i -= 1

        # 处理最后一轮（如果没有被 user 闭合）
        if current_turn:
            turns.append(current_turn)

        # turns 现在是 [最早轮次, ..., 最晚轮次]
        turns = list(reversed(turns))

        # 确定保留的轮次数
        preserve = max(config.min_preserve_turns, config.preserve_turns)
        preserve = min(preserve, len(turns))
        keep_turns = turns[-preserve:] if preserve > 0 else turns
        first_keep_index = keep_turns[0][0] if keep_turns else content_start

        # 计算被裁的轮次范围（turn_index）
        cropped_turns_count = len(turns) - preserve
        cropped_ranges: list[tuple[int, int]] = []
        if cropped_turns_count > 0:
            cropped_ranges.append((0, cropped_turns_count - 1))

        return {
            "count": preserve,
            "cropped_ranges": cropped_ranges,
            "from_index": first_keep_index,
        }

    def _find_dedup_keys(
        self,
        ctx: RuntimeContext,
        keep: dict,
        config: ContextConfig,
    ) -> dict:
        """
        找出与保留的原始消息重叠的记忆 ID。

        判断标准：
        - 根据 turn_index 去重：保留消息对应的 turn 已经在 messages 中，
          不需要重复注入对应的情景记忆摘要。

        Args:
            ctx: RuntimeContext 实例。
            keep: _apply_sliding_window 的返回值。
            config: 上下文管理配置。

        Returns:
            {"memory_ids": set, "turn_indices": set}。
        """
        # 当前实现基于 turn_index 去重
        # 保留的消息对应的 turn_index 集合
        kept_turn_indices: set[int] = set()
        messages = list(ctx.messages)
        from_idx = keep["from_index"]

        # 遍历保留的消息，计算它们对应的 turn_index
        turn_idx = -1
        for i, msg in enumerate(messages):
            role = msg.get("role", "")
            if role == "user":
                turn_idx += 1
            if i >= from_idx:
                kept_turn_indices.add(turn_idx)

        return {
            "memory_ids": set(),  # 由 Compressor._select_memories 在加载记忆后填充具体 ID
            "turn_indices": kept_turn_indices,
        }
