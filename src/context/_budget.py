"""
TokenManager 与 BudgetController——预算执行模块。

TokenManager：估算 token 数，按优先级裁剪 ContextPayload 字段。
BudgetController：动态配额分配 + 强制裁剪 + 保底预留。
"""

from __future__ import annotations

from src.context._config import ContextConfig
from src.runtime.context._payload import ContextPayload


class TokenManager:
    """
    Token 管理器：估算 + 按语义优先级裁剪 ContextPayload。

    裁剪优先级（从低到高）：
    1. tool_results（最先裁）
    2. rag_documents
    3. injected_context
    4. memories
    5. history
    6. system_prompt（最后裁）
    """

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        粗略估算文本的 token 数量。

        基于中英混合估算：平均每个字符约 0.4 token。

        Args:
            text: 输入文本。

        Returns:
            估算的 token 数。
        """
        return int(len(text) * 0.4) + 1

    def _sum_payload_tokens(self, payload: ContextPayload) -> int:
        """估算 payload 各字段的 token 总数。"""
        total = self.estimate_tokens(payload.system_prompt)
        for m in payload.memories:
            total += self.estimate_tokens(str(m))
        for d in payload.rag_documents:
            total += self.estimate_tokens(str(d))
        for c in payload.injected_context:
            total += self.estimate_tokens(str(c))
        for h in payload.history:
            total += self.estimate_tokens(str(h.get("content", "")))
        for r in payload.tool_results:
            total += self.estimate_tokens(str(r))
        return total

    def apply_budget(
        self,
        payload: ContextPayload,
        raw_messages: list[dict],
        max_tokens: int,
    ) -> ContextPayload:
        """
        强制裁剪，算总账（payload 各字段 + 原始消息）。

        裁剪顺序（从最不重要的开始）：
        1. tool_results → 2. rag_documents → 3. injected_context
        → 4. memories → 5. history → 6. system_prompt

        Args:
            payload: 待裁剪的 ContextPayload。
            raw_messages: 保留的原始消息列表。
            max_tokens: 总 token 上限。

        Returns:
            裁剪后的 ContextPayload。
        """
        reserve = payload.reserve_for_response or 1024
        budget = max_tokens - reserve

        # 估算原始消息 token
        message_tokens = sum(
            self.estimate_tokens(str(m.get("content", "")))
            for m in raw_messages
        )
        remaining = budget - message_tokens

        if remaining <= 0:
            # token 全部被原始消息占满，清空所有附加字段
            payload.memories = []
            payload.rag_documents = []
            payload.injected_context = []
            payload.tool_results = []
            payload.history = []
            return payload

        # 按优先级裁剪
        payload = self._trim_field(payload, "tool_results", remaining)
        remaining -= self.estimate_tokens(
            "\n".join(str(x) for x in payload.tool_results)
        )

        payload = self._trim_field(payload, "rag_documents", remaining)
        remaining -= self.estimate_tokens(
            "\n".join(str(x) for x in payload.rag_documents)
        )

        payload = self._trim_field(payload, "injected_context", remaining)
        remaining -= self.estimate_tokens(
            "\n".join(str(x) for x in payload.injected_context)
        )

        payload = self._trim_field(payload, "memories", remaining)
        remaining -= self.estimate_tokens(
            "\n".join(str(x) for x in payload.memories)
        )

        return payload

    def _trim_field(
        self,
        payload: ContextPayload,
        field_name: str,
        budget: int,
    ) -> ContextPayload:
        """
        裁剪指定字段直到其 token 数不超过预算。

        Args:
            payload: ContextPayload。
            field_name: 字段名（"memories" / "rag_documents" 等）。
            budget: 可用 token 预算。

        Returns:
            裁剪后的 ContextPayload。
        """
        items: list = getattr(payload, field_name, [])
        if not items:
            return payload

        current = self.estimate_tokens("\n".join(str(x) for x in items))
        if current <= budget:
            return payload

        # 从末尾开始裁剪（末尾是最旧的/最不重要的）
        while items and current > budget:
            removed = items.pop()
            current -= self.estimate_tokens(str(removed))

        setattr(payload, field_name, items)
        payload.mark_dirty()
        return payload


class BudgetController:
    """
    预算执行：动态分配 + 强制裁剪 + 保底预留。

    接替原 memory/pipeline/token_manager.py 的 TokenManager
    （当前 memory 侧不存在 TokenManager，此为全新的统一实现）。
    """

    def __init__(self, token_manager: TokenManager | None = None) -> None:
        """
        初始化 BudgetController。

        Args:
            token_manager: TokenManager 实例。不提供则创建默认实例。
        """
        self._token_manager = token_manager or TokenManager()

    async def apply(
        self,
        payload: ContextPayload,
        raw_messages: list[dict],
        config: ContextConfig,
    ) -> ContextPayload:
        """
        执行预算。

        计算总 token = payload 各字段 + 原始消息。
        超限时先裁 payload 字段，还不够则标记降级。

        Args:
            payload: 待裁剪的 ContextPayload。
            raw_messages: 保留的原始消息列表。
            config: 上下文管理配置。

        Returns:
            裁剪后的 ContextPayload。
        """
        # 1. 动态配额分配
        hints = self._allocate_budget(payload, config)
        payload.max_tokens = hints["max_tokens"]
        payload.preserve_last_n_history = hints["preserve_last_n_history"]
        payload.reserve_for_response = hints["reserve_for_response"]

        # 2. 强制裁剪
        payload = self._token_manager.apply_budget(
            payload,
            raw_messages,
            max_tokens=config.max_context_tokens,
        )

        # 3. 保底预留校验
        payload = self._ensure_reserve(payload, config)

        return payload

    def _allocate_budget(
        self,
        payload: ContextPayload,
        config: ContextConfig,
    ) -> dict:
        """
        按各来源预估占比动态分配 token 配额。

        分配比例（可配置）：
        - system prompt:         10%
        - entity profile:        10%
        - concepts:              10%
        - episodic memories:     30%
        - history (raw):         30%
        - reserve for response:  10%

        Args:
            payload: ContextPayload。
            config: 上下文管理配置。

        Returns:
            包含 max_tokens / preserve_last_n_history / reserve_for_response 的字典。
        """
        budget = config.max_context_tokens
        reserve = (
            config.reserve_for_response
            if config.reserve_for_response > 0
            else max(512, int(budget * 0.10))
        )
        preserve = max(
            config.min_preserve_turns,
            int((budget * 0.30) / config.avg_message_tokens),
        )

        return {
            "max_tokens": budget,
            "preserve_last_n_history": preserve,
            "reserve_for_response": reserve,
        }

    def _ensure_reserve(
        self,
        payload: ContextPayload,
        config: ContextConfig,
    ) -> ContextPayload:
        """
        确保保底预留满足要求。

        Args:
            payload: ContextPayload。
            config: 上下文管理配置。

        Returns:
            校验后的 ContextPayload。
        """
        if payload.reserve_for_response < 512:
            payload.reserve_for_response = 512
        return payload
