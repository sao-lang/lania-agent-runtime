"""读取管线: 5层组合读取 + Token裁剪."""

from __future__ import annotations

import re

from lania_agent_runtime.memory.interfaces import (
    BehavioralStore,
    EntityStore,
    EpisodicStore,
    SemanticStore,
)
from lania_agent_runtime.memory.pipeline.token_manager import TokenManager
from lania_agent_runtime.models import (
    ConceptSummary,
    ContextPayload,
    EntityProfileValue,
    MemoryEntrySummary,
    PriorityHints,
)


class RecallPipeline:
    """读取管线: before_step 时被 MemoryRecallHook 调用.

    5层组合读取顺序:
    1. Layer 5: 行为模式 → tone_instruction
    2. Layer 4: 语义知识 → concepts
    3. Layer 3: 实体画像 → entity_profile
    4. Layer 2: 情景记忆 → memories
    5. Token 裁剪
    """

    def __init__(self) -> None:
        self._token_manager = TokenManager()

    async def run(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        query: str = "",
        pattern_store: BehavioralStore | None = None,
        semantic_store: SemanticStore | None = None,
        entity_store: EntityStore | None = None,
        episodic_store: EpisodicStore | None = None,
        max_tokens: int = 4096,
    ) -> ContextPayload:
        """5层组合读取, 返回已裁剪的 ContextPayload."""
        payload = ContextPayload()
        payload.priority_hints = PriorityHints(
            max_tokens=max_tokens,
            preserve_last_n_history=3,
            reserve_for_response=1024,
        )

        # Layer 5: 行为模式 → 沟通风格提示
        if user_id and pattern_store:
            pattern = await pattern_store.get_behavioral_pattern(user_id)
            if pattern and pattern.patterns:
                style = pattern.patterns.get("communication_style", {}).get("value")
                if style:
                    payload.tone_instruction = f"用户偏好的沟通风格: {style}"
                else:
                    style = pattern.patterns.get("style")
                    if style:
                        payload.tone_instruction = f"User prefers {style} responses."

        # Layer 4: 语义知识 → 相关概念
        if query and semantic_store:
            query_terms = re.findall(r'\b[a-zA-Z]{4,}\b', query)
            seen_names: set[str] = set()
            for term in query_terms[:5]:
                nodes = await semantic_store.search_semantic(term, limit=3)
                for node in nodes:
                    if node.name not in seen_names:
                        seen_names.add(node.name)
                        payload.concepts.append(ConceptSummary(
                            name=node.name,
                            description=node.description,
                        ))

        # Layer 3: 实体画像
        if user_id and entity_store:
            profile = await entity_store.get_entity_profile("user", user_id)
            if profile and profile.attributes:
                for attr_name, attr_data in profile.attributes.items():
                    if isinstance(attr_data, dict) and "value" in attr_data:
                        payload.entity_profile[attr_name] = EntityProfileValue(
                            value=attr_data["value"],
                            source=attr_data.get("source_session", ""),
                        )

        # Layer 2: 情景记忆
        if episodic_store:
            memories = await episodic_store.recall_session(
                session_id=session_id, limit=10, min_importance=0.3
            )
            if len(memories) < 5 and user_id:
                extra = await episodic_store.recall_user(
                    user_id, limit=5, min_importance=0.7
                )
                memories.extend(extra)

            seen_ids = set()
            unique_memories = []
            for m in memories:
                if m.id not in seen_ids:
                    seen_ids.add(m.id)
                    unique_memories.append(m)

            payload.memories = [
                MemoryEntrySummary(
                    id=m.id, summary=m.summary,
                    created_at=m.created_at, turn_index=m.turn_index,
                )
                for m in unique_memories
            ]

        # Token 裁剪
        return self._token_manager.apply_budget(payload, max_tokens)
