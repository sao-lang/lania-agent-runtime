"""MemoryService: 5层记忆系统统一门面.

设计文档要求: memory-system-design.md §3.1
接收5个独立Store, 实现可插拔组合.
"""

from __future__ import annotations

from typing import Callable

from lania_agent_runtime.memory.interfaces import (
    BehavioralStore,
    EntityStore,
    EpisodicStore,
    SemanticStore,
    WorkingMemoryStore,
)
from lania_agent_runtime.memory.pipeline.commit import CommitPipeline
from lania_agent_runtime.memory.pipeline.recall import RecallPipeline
from lania_agent_runtime.models import (
    ContextPayload,
    EntityExtraction,
    GateDecision,
    WorkingMemorySnapshot,
)


class MemoryService:
    """5层记忆系统统一门面.

    接收5个独立Store, 实现可插拔组合.
    提供:
    - recall()  — 读取管线: 5层联合读取 + Token裁剪
    - commit()  — 写入管线: 5层联合写入 + 异步扇出
    - checkpoint/restore — 工作记忆快照
    """

    def __init__(
        self,
        working_store: WorkingMemoryStore | None = None,
        episodic_store: EpisodicStore | None = None,
        entity_store: EntityStore | None = None,
        semantic_store: SemanticStore | None = None,
        pattern_store: BehavioralStore | None = None,
        *,
        store: WorkingMemoryStore | None = None,
        llm_extractor: Callable[[str], list[EntityExtraction]] | None = None,
    ) -> None:
        """初始化 MemoryService.

        设计推荐传5个独立 Store. 也支持旧 API: MemoryService(store=...)
        当传入单 store 时, 使用 isinstance 检查自动分配到各层.

        Args:
            working_store: 工作记忆存储 (Layer 1)
            episodic_store: 情景记忆存储 (Layer 2)
            entity_store: 实体记忆存储 (Layer 3)
            semantic_store: 语义知识存储 (Layer 4)
            pattern_store: 行为模式存储 (Layer 5)
            store: (向后兼容) 单 Store 模式
            llm_extractor: LLM实体提取回调(可选)
        """
        # 向后兼容: 单 store 模式 → 自动分配到各层
        if store is not None:
            working_store = working_store or (
                store if isinstance(store, WorkingMemoryStore) else None
            )
            episodic_store = episodic_store or (
                store if isinstance(store, EpisodicStore) else None
            )
            entity_store = entity_store or (
                store if isinstance(store, EntityStore) else None
            )
            semantic_store = semantic_store or (
                store if isinstance(store, SemanticStore) else None
            )
            pattern_store = pattern_store or (
                store if isinstance(store, BehavioralStore) else None
            )

        self._working_store = working_store
        self._episodic_store = episodic_store
        self._entity_store = entity_store
        self._semantic_store = semantic_store
        self._pattern_store = pattern_store

        self._recall = RecallPipeline()
        self._commit = CommitPipeline(llm_extractor=llm_extractor)

    # ── 属性 ──

    @property
    def store(self) -> WorkingMemoryStore | None:
        """(向后兼容) 返回第一个可用的存储."""
        return self._working_store or self._episodic_store or self._entity_store or self._semantic_store or self._pattern_store

    @property
    def working_store(self) -> WorkingMemoryStore | None:
        return self._working_store

    @property
    def episodic_store(self) -> EpisodicStore | None:
        return self._episodic_store

    @property
    def entity_store(self) -> EntityStore | None:
        return self._entity_store

    @property
    def semantic_store(self) -> SemanticStore | None:
        return self._semantic_store

    @property
    def pattern_store(self) -> BehavioralStore | None:
        return self._pattern_store

    # ──── 读取管线 ────

    async def recall(
        self,
        session_id: str,
        user_id: str | None = None,
        query: str = "",
        *,
        max_tokens: int = 4096,
    ) -> ContextPayload:
        """5层组合读取, 返回已裁剪的 ContextPayload."""
        return await self._recall.run(
            session_id=session_id,
            user_id=user_id,
            query=query,
            pattern_store=self._pattern_store,
            semantic_store=self._semantic_store,
            entity_store=self._entity_store,
            episodic_store=self._episodic_store,
            max_tokens=max_tokens,
        )

    # ──── 写入管线 ────

    async def commit(
        self,
        session_id: str,
        user_id: str | None,
        user_message: str,
        assistant_message: str,
        *,
        tool_calls: list[dict] | None = None,
        gate_decision: GateDecision | None = None,
    ) -> None:
        """5层写入."""
        await self._commit.run(
            session_id=session_id,
            user_id=user_id,
            user_message=user_message,
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            gate_decision=gate_decision,
            episodic_store=self._episodic_store,
            entity_store=self._entity_store,
            semantic_store=self._semantic_store,
            pattern_store=self._pattern_store,
        )

    # ──── 工作记忆快照 ────

    async def checkpoint(self, snapshot: WorkingMemorySnapshot) -> None:
        """保存工作记忆快照 (覆盖写)."""
        if self._working_store:
            await self._working_store.save_working_memory(snapshot)

    async def restore(self, session_id: str) -> WorkingMemorySnapshot | None:
        """恢复工作记忆快照."""
        if self._working_store:
            return await self._working_store.load_working_memory(session_id)
        return None

    async def discard_checkpoint(self, session_id: str) -> None:
        """丢弃工作记忆快照."""
        if self._working_store:
            await self._working_store.delete_working_memory(session_id)

    async def has_checkpoint(self, session_id: str) -> bool:
        """检查工作记忆快照是否存在且未过期."""
        if self._working_store:
            return await self._working_store.exists_working_memory(session_id)
        return False
