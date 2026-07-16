"""Memory service interfaces and unified facade."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import Counter
from typing import Any

from lania_agent_runtime.models import (
    BehavioralPattern,
    ConceptSummary,
    ContextPayload,
    EntityMemoryEntry,
    EntityProfileValue,
    EpisodicMemoryEntry,
    MemoryEntrySummary,
    PriorityHints,
    SemanticEdge,
    SemanticNode,
    WorkingMemorySnapshot,
)


class MemoryStore(ABC):
    """Abstract base class for memory stores."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the store (create tables, etc.)."""

    @abstractmethod
    async def close(self) -> None:
        """Close the store and release resources."""


class EpisodicStore(ABC):
    """Episodic memory store interface."""

    @abstractmethod
    async def write(self, entry: EpisodicMemoryEntry) -> str:
        """Write an episodic memory entry. Returns entry id."""

    @abstractmethod
    async def recall_session(
        self, session_id: str, *, limit: int = 20, offset: int = 0
    ) -> list[EpisodicMemoryEntry]:
        """Recall memories for a session, ordered by turn_index DESC."""

    @abstractmethod
    async def recall_user(
        self, user_id: str, *, limit: int = 20, offset: int = 0
    ) -> list[EpisodicMemoryEntry]:
        """Recall memories across sessions for a user."""

    @abstractmethod
    async def search_by_entities(
        self, user_id: str, entities: list[str], *, limit: int = 10
    ) -> list[EpisodicMemoryEntry]:
        """Search memories by entity tags."""

    @abstractmethod
    async def count_session(self, session_id: str) -> int:
        """Count entries in a session."""


class EntityStore(ABC):
    """Entity memory store interface (Layer 3)."""

    @abstractmethod
    async def upsert_entity_attribute(
        self,
        entity_type: str,
        entity_key: str,
        attr_name: str,
        value: Any,
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> None:
        """Upsert an entity attribute."""

    @abstractmethod
    async def get_entity_profile(
        self, entity_type: str, entity_key: str
    ) -> EntityMemoryEntry | None:
        """Get the full profile for an entity."""


class SemanticStore(ABC):
    """Semantic knowledge store interface (Layer 4)."""

    @abstractmethod
    async def create_semantic_node(
        self, name: str, node_type: str = "concept", description: str = ""
    ) -> str:
        """Create or get existing semantic node. Returns node id."""

    @abstractmethod
    async def search_semantic(
        self, query: str, *, type_filter: str | None = None, limit: int = 10
    ) -> list[SemanticNode]:
        """Search semantic nodes by name/description."""

    @abstractmethod
    async def create_semantic_edge(
        self,
        source_node: str,
        target_node: str,
        relation: str,
        *,
        confidence: float = 1.0,
    ) -> str:
        """Create a semantic edge between two nodes."""


class BehavioralStore(ABC):
    """Behavioral pattern store interface (Layer 5)."""

    @abstractmethod
    async def upsert_behavioral_pattern(
        self, user_id: str, patterns: dict[str, Any]
    ) -> None:
        """Upsert behavioral pattern for a user."""

    @abstractmethod
    async def get_behavioral_pattern(self, user_id: str) -> BehavioralPattern | None:
        """Get behavioral pattern for a user."""


class MemoryService:
    """Unified facade for the 5-layer memory system."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store

    @property
    def store(self) -> MemoryStore | None:
        return self._store

    # ── Helpers ──

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """Simple entity extraction: capitalized multi-word phrases."""
        # Find capitalized phrases (2+ words) as potential entities
        phrases = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', text)
        # Find single capitalized words that aren't at sentence start
        single_words = re.findall(r'(?<![.!?]\s)[A-Z][a-z]{2,}', text)
        # Find common technical terms (lowercase, >3 chars)
        tech_terms = re.findall(r'\b[a-z]{4,}\b', text.lower())
        # Filter stopwords
        stopwords = {"this", "that", "with", "from", "have", "been", "what",
                     "when", "where", "which", "their", "there", "about", "would"}
        tech_terms = [t for t in tech_terms if t not in stopwords]

        entities = list(set(phrases + single_words))
        # Add top 5 tech terms as lowercase entities
        for t in tech_terms[:5]:
            if t not in [e.lower() for e in entities]:
                entities.append(t)
        return entities[:10]

    @staticmethod
    def _extract_topics(text: str) -> list[str]:
        """Simple topic extraction: nouns and key phrases."""
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text)
        stopwords = {"this", "that", "with", "from", "have", "been", "what",
                     "when", "where", "which", "their", "there", "about", "would",
                     "tell", "know", "think", "just", "like", "want", "need",
                     "help", "talk", "speak"}
        topics = [w.lower() for w in words if w.lower() not in stopwords]
        # Return unique, frequency sorted
        from collections import Counter
        return [t for t, _ in Counter(topics).most_common(5)]

    # ── Read pipeline (called in before_step) ──

    async def recall(
        self,
        session_id: str,
        user_id: str | None = None,
        query: str = "",
        *,
        max_tokens: int = 4096,
    ) -> ContextPayload:
        """5-layer combined read, returns a trimmed ContextPayload."""
        payload = ContextPayload()
        payload.priority_hints = PriorityHints(
            max_tokens=max_tokens,
            preserve_last_n_history=3,
            reserve_for_response=1024,
        )

        if not self._store:
            return payload

        # Layer 2: Read episodic memories
        if isinstance(self._store, EpisodicStore):
            memories = await self._store.recall_session(session_id=session_id, limit=10)
            payload.memories = [
                MemoryEntrySummary(
                    id=m.id,
                    summary=m.summary,
                    created_at=m.created_at,
                    turn_index=m.turn_index,
                )
                for m in memories
            ]

        # Layer 3: Read entity profile (user)
        if user_id and isinstance(self._store, EntityStore):
            profile = await self._store.get_entity_profile("user", user_id)
            if profile and profile.attributes:
                for attr_name, attr_data in profile.attributes.items():
                    if isinstance(attr_data, dict) and "value" in attr_data:
                        payload.entity_profile[attr_name] = EntityProfileValue(
                            value=attr_data["value"],
                            source=attr_data.get("source_session", ""),
                        )

        # Layer 4: Read semantic knowledge (search by query terms)
        if query and isinstance(self._store, SemanticStore):
            # Extract key terms from query for semantic search
            query_terms = re.findall(r'\b[a-zA-Z]{4,}\b', query)
            seen_names: set[str] = set()
            for term in query_terms[:5]:
                nodes = await self._store.search_semantic(term, limit=3)
                for node in nodes:
                    if node.name not in seen_names:
                        seen_names.add(node.name)
                        payload.concepts.append(ConceptSummary(
                            name=node.name,
                            description=node.description,
                        ))

        # Layer 5: Read behavioral pattern
        if user_id and isinstance(self._store, BehavioralStore):
            pattern = await self._store.get_behavioral_pattern(user_id)
            if pattern and pattern.patterns:
                # Inject as a tone instruction if available
                style = pattern.patterns.get("style")
                if style:
                    payload.tone_instruction = (
                        f"User prefers {style} responses."
                    )

        return payload

    # ── Write pipeline (called in after_step) ──

    async def commit(
        self,
        session_id: str,
        user_id: str | None,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """5-layer write. Records episodic + entity + semantic + pattern."""
        if not self._store or not isinstance(self._store, EpisodicStore):
            return

        # Extract entities and topics
        all_text = f"{user_message} {assistant_message}"
        entities = self._extract_entities(all_text)
        topics = self._extract_topics(all_text)

        # Create episodic memory entry
        entry = EpisodicMemoryEntry(
            session_id=session_id,
            user_id=user_id or "",
            turn_index=0,
            summary=assistant_message[:200] if assistant_message else "",
            raw_content=f"User: {user_message}\nAssistant: {assistant_message}",
            source={
                "user_message": user_message,
                "assistant_message": assistant_message,
            },
            token_count=len(user_message) + len(assistant_message),
            entities=entities,
            topics=topics,
        )

        # Get current turn count
        count = await self._store.count_session(session_id)
        entry.turn_index = count

        await self._store.write(entry)

        # Layer 3: Upsert entity profile (user)
        if user_id and isinstance(self._store, EntityStore):
            # Simple attribute extraction from user message
            for keyword, attr_name in [("name is ", "name"), ("I am ", "name"),
                                       ("I'm ", "name"), ("my name is ", "name"),
                                       ("I like ", "preference"),
                                       ("I love ", "preference"),
                                       ("I work as ", "profession"),
                                       ("I am a ", "profession")]:
                idx = user_message.lower().find(keyword)
                if idx >= 0:
                    value = user_message[idx + len(keyword):].split(".")[0].split(",")[0].strip()
                    if value:
                        await self._store.upsert_entity_attribute(
                            "user", user_id, attr_name, value,
                            source_session=session_id,
                        )

        # Layer 4: Create semantic nodes for key topics
        if isinstance(self._store, SemanticStore):
            for topic in topics[:3]:
                node_id = await self._store.create_semantic_node(
                    topic.capitalize(), "concept", f"Discussed in session {session_id}"
                )

        # Layer 5: Update behavioral pattern
        if user_id and isinstance(self._store, BehavioralStore):
            current_pattern = await self._store.get_behavioral_pattern(user_id)
            patterns = dict(current_pattern.patterns) if current_pattern else {}
            # Detect style preference
            if any(w in assistant_message.lower() for w in ["in short", "briefly", "summary"]):
                patterns["style"] = "concise"
            elif any(w in assistant_message.lower() for w in ["in detail", "here's how", "step by step"]):
                patterns["style"] = "detailed"
            else:
                patterns["style"] = patterns.get("style", "balanced")
            await self._store.upsert_behavioral_pattern(user_id, patterns)

    # ── Working memory snapshots ──

    async def checkpoint(self, snapshot: WorkingMemorySnapshot) -> None:
        """Save a working memory checkpoint."""
        if self._store and hasattr(self._store, "save_working_memory"):
            await self._store.save_working_memory(snapshot)  # type: ignore

    async def restore(self, session_id: str) -> WorkingMemorySnapshot | None:
        """Restore a working memory checkpoint."""
        if self._store and hasattr(self._store, "load_working_memory"):
            return await self._store.load_working_memory(session_id)  # type: ignore
        return None

    async def discard_checkpoint(self, session_id: str) -> None:
        """Discard a working memory checkpoint."""
        if self._store and hasattr(self._store, "delete_working_memory"):
            await self._store.delete_working_memory(session_id)  # type: ignore
