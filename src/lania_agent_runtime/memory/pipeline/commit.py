"""写入管线: 5层联合写入 + 异步扇出."""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Any, Callable

from lania_agent_runtime.memory.interfaces import (
    BehavioralStore,
    EntityStore,
    EpisodicStore,
    SemanticStore,
)
from lania_agent_runtime.models import (
    EntityExtraction,
    EpisodicMemoryEntry,
    GateDecision,
    StepContext,
)


class CommitPipeline:
    """写入管线: after_step 时被 MemoryCommitHook 调用.

    写入顺序:
    1. Layer 2: 写入情景记忆 (同步)
    2. Layer 3: 实体提取 + upsert (同步)
    3. Layer 4: 语义节点 (异步)
    4. Layer 5: 行为模式 (同步)
    """

    def __init__(
        self,
        *,
        llm_extractor: Callable[[str], list[EntityExtraction]] | None = None,
    ) -> None:
        self._llm_extractor = llm_extractor

    async def run(
        self,
        *,
        session_id: str,
        user_id: str | None,
        user_message: str,
        assistant_message: str,
        tool_calls: list[dict] | None = None,
        gate_decision: GateDecision | None = None,
        episodic_store: EpisodicStore | None = None,
        entity_store: EntityStore | None = None,
        semantic_store: SemanticStore | None = None,
        pattern_store: BehavioralStore | None = None,
    ) -> None:
        """5层写入."""
        if not episodic_store:
            return

        # 构建 StepContext
        all_text = f"{user_message} {assistant_message}"
        entities = self._extract_entities_regex(all_text)
        topics = self._extract_topics(all_text)
        count = await episodic_store.count_session(session_id)

        ctx = StepContext(
            user_message=user_message,
            assistant_message=assistant_message,
            turn_index=count,
            session_id=session_id,
            user_id=user_id,
            entities_detected=entities,
            topics_detected=topics,
            raw_content=f"User: {user_message}\nAssistant: {assistant_message}",
            importance=gate_decision.importance if gate_decision else 0.3,
        )

        if gate_decision and not gate_decision.should_record:
            if user_id and gate_decision.should_extract_entities and entity_store:
                await self._run_entity_pipeline(
                    user_id, session_id, ctx, entity_store, semantic_store,
                )
            return

        source: dict[str, Any] = {
            "user_message": user_message,
            "assistant_message": assistant_message,
        }
        if tool_calls:
            source["tool_calls"] = [
                {
                    "tool_name": tc.get("name", tc.get("tool_name", "")),
                    "arguments": tc.get("arguments", {}),
                    "result": tc.get("result", ""),
                }
                for tc in tool_calls
            ]

        # Layer 2: 写入情景记忆
        entry = EpisodicMemoryEntry(
            session_id=session_id,
            user_id=user_id or "",
            turn_index=ctx.turn_index,
            summary=ctx.summary,
            raw_content=ctx.raw_content,
            content_type="critical_event" if ctx.importance > 0.7 else "raw",
            source=source,
            token_count=self._estimate_tokens(ctx.raw_content),
            entities=entities,
            topics=topics,
            importance=ctx.importance,
        )
        await episodic_store.write(entry)

        # Layer 3: 实体提取
        if user_id and entity_store:
            await self._run_entity_pipeline(
                user_id, session_id, ctx, entity_store, semantic_store,
            )
            # Layer 5: 行为模式
            if pattern_store:
                await self._run_pattern_sampling(user_id, ctx, pattern_store)

        # Layer 4: 语义节点 (异步)
        if semantic_store:
            asyncio.ensure_future(
                self._run_semantic_pipeline(user_id or "", topics, semantic_store)
            )

    # ── 内部管线 ──

    async def _run_entity_pipeline(
        self, user_id: str, session_id: str, ctx: StepContext,
        entity_store: EntityStore, semantic_store: SemanticStore | None = None,
    ) -> None:
        """实体提取管线."""
        if self._llm_extractor:
            extractions = self._llm_extractor(ctx.raw_content)
        else:
            extractions = self._extract_entities_keyword(ctx)

        for ext in extractions:
            for attr_name, attr_value in ext.attributes.items():
                await entity_store.upsert_entity_attribute(
                    ext.entity_type, ext.entity_key, attr_name, attr_value,
                    confidence=ext.confidence, source_session=session_id,
                )
            if semantic_store:
                asyncio.ensure_future(
                    self._run_semantic_from_extractions(ext, semantic_store)
                )

    async def _run_semantic_pipeline(
        self, user_id: str, topics: list[str], semantic_store: SemanticStore,
    ) -> None:
        """语义知识提炼管线."""
        for topic in topics[:3]:
            await semantic_store.create_semantic_node(
                topic.capitalize(), "concept", "Discussed in session",
            )

    @staticmethod
    async def _run_semantic_from_extractions(
        ext: EntityExtraction, semantic_store: SemanticStore,
    ) -> None:
        """从实体提取结果创建语义关系."""
        triples: list[tuple[str, str, str]] = []
        for attr_name, attr_value in ext.attributes.items():
            if isinstance(attr_value, str) and len(attr_value) > 3:
                triples.append((ext.entity_key, f"has_{attr_name}", attr_name))
                triples.append((str(attr_value), f"is_value_of_{attr_name}", attr_name))
        if triples:
            await semantic_store.merge_knowledge(triples)

    @staticmethod
    async def _run_pattern_sampling(
        user_id: str, ctx: StepContext, pattern_store: BehavioralStore,
    ) -> None:
        """行为模式采样."""
        current_pattern = await pattern_store.get_behavioral_pattern(user_id)
        patterns = dict(current_pattern.patterns) if current_pattern else {}
        msg = ctx.assistant_message or ""
        if any(w in msg.lower() for w in ["in short", "briefly", "summary"]):
            patterns["style"] = "concise"
        elif any(w in msg.lower() for w in ["in detail", "here's how", "step by step"]):
            patterns["style"] = "detailed"
        else:
            patterns["style"] = patterns.get("style", "balanced")
        await pattern_store.upsert_behavioral_pattern(user_id, patterns)

    # ── 工具方法 ──

    @staticmethod
    def _extract_entities_regex(text: str) -> list[str]:
        """基于正则的实体提取."""
        phrases = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', text)
        single_words = re.findall(r'(?<![.!?]\s)[A-Z][a-z]{2,}', text)
        tech_terms = re.findall(r'\b[a-z]{4,}\b', text.lower())
        stopwords = {"this", "that", "with", "from", "have", "been", "what",
                     "when", "where", "which", "their", "there", "about", "would"}
        tech_terms = [t for t in tech_terms if t not in stopwords]
        entities = list(set(phrases + single_words))
        for t in tech_terms[:5]:
            if t not in [e.lower() for e in entities]:
                entities.append(t)
        return entities[:10]

    @staticmethod
    def _extract_topics(text: str) -> list[str]:
        """基于频率的话题提取."""
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text)
        stopwords = {"this", "that", "with", "from", "have", "been", "what",
                     "when", "where", "which", "their", "there", "about", "would",
                     "tell", "know", "think", "just", "like", "want", "need",
                     "help", "talk", "speak"}
        topics = [w.lower() for w in words if w.lower() not in stopwords]
        return [t for t, _ in Counter(topics).most_common(5)]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算 token 数."""
        return int(len(text) * 0.4)

    @staticmethod
    def _extract_entities_keyword(ctx: StepContext) -> list[EntityExtraction]:
        """基于关键词的实体提取."""
        extractions: list[EntityExtraction] = []
        user_msg = ctx.user_message or ""
        patterns: list[tuple[str, str, str]] = [
            ("name is ", "user", "name"), ("I am ", "user", "name"),
            ("I'm ", "user", "name"), ("my name is ", "user", "name"),
            ("I like ", "user", "preference"), ("I love ", "user", "preference"),
            ("I work as ", "user", "profession"), ("I am a ", "user", "profession"),
        ]
        attrs: dict[str, Any] = {}
        for keyword, entity_type, attr_name in patterns:
            idx = user_msg.lower().find(keyword)
            if idx >= 0:
                value = user_msg[idx + len(keyword):].split(".")[0].split(",")[0].strip()
                if value:
                    attrs[attr_name] = value
        if attrs:
            extractions.append(EntityExtraction(
                entity_type="user", entity_key=ctx.user_id or "unknown",
                attributes=attrs, confidence=0.7, source_session=ctx.session_id,
            ))
        return extractions
