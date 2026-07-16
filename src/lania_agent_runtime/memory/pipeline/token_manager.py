"""Token 裁剪管线: 按优先级裁剪 ContextPayload."""

from __future__ import annotations

from lania_agent_runtime.models import ContextPayload, PriorityHints


class TokenManager:
    """Token 管理器: 按语义优先级裁剪 ContextPayload.

    优先级(高→低):
    1. tone_instruction — 几乎不占, 不裁剪
    2. entity_profile   — 中等大小, 最后裁剪
    3. concepts         — 中等大小, 次于记忆裁剪
    4. memories         — 最大体积, 优先裁剪
    """

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """粗略估算 token 数(中英文混合按字符*0.4)."""
        return int(len(text) * 0.4)

    def apply_budget(
        self, payload: ContextPayload, max_tokens: int
    ) -> ContextPayload:
        """按预算上限裁剪 ContextPayload, 返回裁剪后的副本."""
        reserve = payload.priority_hints.reserve_for_response
        budget = max_tokens - reserve

        tone_tokens = self.estimate_tokens(payload.tone_instruction)
        profile_tokens = sum(
            self.estimate_tokens(str(v.get("value", v)))
            for v in payload.entity_profile.values()
        )
        concept_tokens = sum(
            self.estimate_tokens(f"{c.get('name', '')} {c.get('description', '')}")
            for c in payload.concepts
        )
        memory_tokens = sum(
            self.estimate_tokens(m.get("summary", ""))
            for m in payload.memories
        )
        total = tone_tokens + profile_tokens + concept_tokens + memory_tokens

        if total <= budget:
            return payload

        # 1) 裁剪情景记忆: 按 turn_index 升序移除(最旧的先移除)
        if memory_tokens > 0:
            payload.memories.sort(
                key=lambda m: (m.get("turn_index", 0), m.get("created_at", ""))
            )
            target_mem = int(budget * 0.5)
            while memory_tokens > target_mem and payload.memories:
                removed = payload.memories.pop(0)
                memory_tokens -= self.estimate_tokens(removed.get("summary", ""))

        # 2) 裁剪概念
        if total > budget and len(payload.concepts) > 1:
            payload.concepts = payload.concepts[:1]

        # 3) 裁剪画像
        if total > budget and len(payload.entity_profile) > 3:
            keys = list(payload.entity_profile.keys())
            for k in keys[3:]:
                del payload.entity_profile[k]

        return payload
