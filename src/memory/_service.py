"""
MemoryService——记忆系统统一外观。

上层只感知这一个入口，不感知内部五层存储差异和序列化细节。
提供 recall/commit/checkpoint 三大核心方法。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.memory._persistence import MemoryPersistence
from src.memory._stores import (
    BehavioralPatternStore,
    EntityMemoryStore,
    EpisodicMemoryStore,
    SemanticKnowledgeStore,
    WorkingMemoryStore,
)
from src.memory._types import (
    EpisodicMemoryEntry,
    RecallResult,
    StepContext,
    WorkingMemorySnapshot,
)

logger = logging.getLogger(__name__)


class _BackgroundTaskGroup:
    """后台任务组——跟踪 fire-and-forget 任务的生命周期。"""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def start(self, coro: Any) -> asyncio.Task[Any]:
        """启动并跟踪一个后台任务。"""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        """等待所有后台任务完成（或取消）。

        Args:
            wait: True 等待完成，False 取消所有任务。
            timeout: 最大等待秒数，超时后强制取消剩余任务。
        """
        if not self._tasks:
            return
        if wait:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                for t in self._tasks:
                    t.cancel()
                await asyncio.gather(*self._tasks, return_exceptions=True)
        else:
            for t in self._tasks:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()


class MemoryService:
    """
    记忆系统统一外观。

    三层只感知这一个入口，MemoryService 在内部将 5 层记忆的读写
    转化为对 MemoryPersistence 的键值操作。

    使用方式：
        # 使用默认 SQLite 后端
        memory = MemoryService()

        # 或使用自定义后端（Redis / 文件系统等）
        memory = MemoryService(persistence=MyCustomBackend())
    """

    def __init__(
        self,
        persistence: MemoryPersistence | None = None,
    ) -> None:
        """
        初始化 MemoryService。

        Args:
            persistence: MemoryPersistence 实例。不提供则自动创建
                        SQLitePersistence("./memory.db")。
        """
        if persistence is None:
            from src.memory._backends._sqlite import SQLitePersistence

            persistence = SQLitePersistence("./memory.db")

        self._store = persistence

        # 内部 Store 适配器
        self._working = WorkingMemoryStore(self._store)
        self._episodic = EpisodicMemoryStore(self._store)
        self._entity = EntityMemoryStore(self._store)
        self._semantic = SemanticKnowledgeStore(self._store)
        self._pattern = BehavioralPatternStore(self._store)

        # 后台任务跟踪
        self._bg_tasks = _BackgroundTaskGroup()

    # ── 属性 ──

    @property
    def episodic(self) -> EpisodicMemoryStore:
        """获取情景记忆存储适配器。"""
        return self._episodic

    @property
    def entity(self) -> EntityMemoryStore:
        """获取实体记忆存储适配器。"""
        return self._entity

    @property
    def semantic(self) -> SemanticKnowledgeStore:
        """获取语义知识存储适配器。"""
        return self._semantic

    @property
    def pattern(self) -> BehavioralPatternStore:
        """获取行为模式存储适配器。"""
        return self._pattern

    # ── 读取管线 ──

    async def recall(
        self,
        session_id: str,
        user_id: str | None = None,
        query: str = "",
        *,
        max_tokens: int = 4096,
    ) -> Any:
        """
        五层组合读取（返回 ContextPayload 兼容结构）。

        保留向后兼容，计划在 ContextManager 就绪后废弃此方法。

        Args:
            session_id: 会话 ID。
            user_id: 用户 ID。
            query: 当前查询文本。
            max_tokens: token 预算。

        Returns:
            dict 格式的上下文数据。
        """
        recall_result = await self.recall_raw(
            session_id, user_id, query, max_memories=10,
        )

        # 组装为类似 ContextPayload 的 dict
        tone = recall_result.tone_instruction
        memories_text = []
        for m in recall_result.episodic_memories:
            label = "critical" if m.content_type == "critical_event" else "memory"
            memories_text.append(f"[{label}] {m.summary}")

        concepts_text = []
        for c in recall_result.concepts:
            concepts_text.append(f"- {c.get('name', '')}: {c.get('description', '')}")

        return {
            "tone_instruction": tone,
            "memories": memories_text,
            "concepts": concepts_text,
            "entity_profile": {
                k: v.value for k, v in recall_result.entity_profile.items()
            },
        }

    async def recall_raw(
        self,
        session_id: str,
        user_id: str | None = None,
        query: str = "",
        *,
        turn_ranges: list[tuple[int, int]] | None = None,
        max_memories: int = 20,
    ) -> RecallResult:
        """
        返回裸数据供 ContextManager 使用。

        Args:
            session_id: 会话 ID。
            user_id: 用户 ID。
            query: 当前查询文本（用于语义检索）。
            turn_ranges: 指定检索哪些 turn_index 范围的记忆。
            max_memories: 最大记忆条数。

        Returns:
            RecallResult 裸数据。
        """
        # Layer 2: 情景记忆
        episodic_memories: list[EpisodicMemoryEntry] = []
        if turn_ranges:
            for start, end in turn_ranges:
                memories = await self._episodic.recall_by_turn_range(
                    session_id, start, end,
                )
                episodic_memories.extend(memories)
        else:
            memories = await self._episodic.recall_session(
                session_id, limit=max_memories, min_importance=0.3,
            )
            episodic_memories.extend(memories)

        # Layer 3: 实体画像
        entity_profile: dict[str, Any] = {}
        if user_id:
            entity = await self._entity.read("user", user_id)
            if entity:
                entity_profile = dict(entity.attributes)

        # Layer 4: 语义知识
        concepts: list[dict[str, str]] = []
        if query:
            nodes = await self._semantic.search_nodes(query, top_k=3)
            for node in nodes:
                concepts.append({
                    "name": node.name,
                    "description": node.description,
                })

        # Layer 5: 行为模式 → tone 指令
        tone_instruction = ""
        if user_id:
            pattern = await self._pattern.read(user_id)
            if pattern and "communication_style" in pattern.patterns:
                style = pattern.patterns["communication_style"]
                tone_instruction = (
                    f"用户偏好的沟通风格: {style.get('value', '')}"
                )

        return RecallResult(
            episodic_memories=episodic_memories,
            entity_profile=entity_profile,
            concepts=concepts,
            tone_instruction=tone_instruction,
        )

    # ── 写入管线 ──

    async def commit(
        self,
        session_id: str,
        user_id: str | None,
        step_context: StepContext,
    ) -> None:
        """
        五层写入。

        Layer 2 同步写入，Layer 3-5 异步触发。

        Args:
            session_id: 会话 ID。
            user_id: 用户 ID（可为 None）。
            step_context: Step 上下文。
        """
        # Layer 2: 写情景记忆
        entry = EpisodicMemoryEntry(
            session_id=session_id,
            user_id=user_id or "",
            turn_index=step_context.turn_index,
            summary=step_context.summary,
            raw_content=step_context.raw,
            content_type=(
                "critical_event" if step_context.importance > 0.7 else "raw"
            ),
            entities=step_context.entities_detected,
            topics=step_context.topics_detected,
            importance=step_context.importance,
            token_count=len(step_context.raw) if step_context.raw else 0,
        )
        await self._episodic.write(entry)

        # Layer 3-5: 异步触发（不阻塞回复）
        if user_id:
            self._bg_tasks.start(
                self._safe_background_task(
                    self._entity_extraction_pipeline(user_id, session_id, step_context),
                    f"entity_extraction({user_id}, {session_id})",
                )
            )

    async def _entity_extraction_pipeline(
        self,
        user_id: str,
        session_id: str,
        step_context: StepContext,
    ) -> None:
        """
        实体提取管线——从对话中提取实体并写入。

        Args:
            user_id: 用户 ID。
            session_id: 会话 ID。
            step_context: Step 上下文。
        """
        # 提取实体属性
        extractions = await self._extract_entities(step_context)
        for entity_type, entity_key, attributes in extractions:
            for attr_name, attr_value in attributes.items():
                await self._entity.upsert_attribute(
                    entity_type,
                    entity_key,
                    attr_name,
                    attr_value,
                    confidence=0.7,
                    source_session=session_id,
                )

        # 检查是否需要更新语义知识
        if extractions:
            self._bg_tasks.start(
                self._safe_background_task(
                    self._semantic_pipeline(extractions),
                    f"semantic_pipeline({session_id})",
                )
            )

    async def _semantic_pipeline(
        self,
        extractions: list[tuple[str, str, dict]],
    ) -> None:
        """
        语义知识提炼管线。

        Args:
            extractions: [(entity_type, entity_key, attributes), ...]。
        """
        for entity_type, entity_key, attributes in extractions:
            for attr_name, attr_value in attributes.items():
                if isinstance(attr_value, str) and len(attr_value) > 3:
                    await self._semantic.merge_knowledge([
                        (entity_key, "has_attribute", attr_name),
                        (str(attr_value), "is_value_of", attr_name),
                    ])

    async def _extract_entities(
        self,
        step_context: StepContext,
    ) -> list[tuple[str, str, dict]]:
        """
        从 StepContext 中提取实体。

        当前实现从 entities_detected 构建简单实体。
        Phase 3 可接入 LLM extractor 增强。

        Args:
            step_context: Step 上下文。

        Returns:
            [(entity_type, entity_key, {attr: value}), ...]。
        """
        extractions: list[tuple[str, str, dict]] = []
        if step_context.user_id:
            for entity in step_context.entities_detected:
                extractions.append((
                    "user",
                    step_context.user_id,
                    {f"mentioned_{entity}": entity},
                ))
        return extractions

    @staticmethod
    async def _safe_background_task(coro: Any, name: str) -> None:
        """
        安全的后台任务执行器——捕获异常并记录，不吞没错误。

        Args:
            coro: 协程对象。
            name: 任务名称（用于日志）。
        """
        try:
            await coro
        except Exception as e:
            logger.error(
                "Background task '%s' failed: %s: %s",
                name,
                type(e).__name__,
                e,
                exc_info=True,
            )

    # ── 工作记忆快照 ──

    async def checkpoint(self, snapshot: WorkingMemorySnapshot) -> None:
        """
        保存工作记忆快照（覆盖写）。

        Args:
            snapshot: 工作记忆快照。
        """
        await self._working.save(snapshot)

    async def restore(self, session_id: str) -> WorkingMemorySnapshot | None:
        """
        恢复工作记忆快照。

        Args:
            session_id: 会话 ID。

        Returns:
            快照对象，不存在或已过期则返回 None。
        """
        return await self._working.load(session_id)

    async def discard_checkpoint(self, session_id: str) -> None:
        """
        丢弃工作记忆快照（正常完成后清理）。

        Args:
            session_id: 会话 ID。
        """
        await self._working.delete(session_id)

    # ── 资源管理 ──

    async def close(self) -> None:
        """
        关闭持久化后端，释放资源（如 SQLite 连接）。

        等待所有后台任务完成后关闭存储后端。

        使用方式：
            memory = MemoryService()
            try:
                ...
            finally:
                await memory.close()
        """
        await self._bg_tasks.shutdown(wait=True)
        await self._store.close()

    async def __aenter__(self) -> MemoryService:
        """异步上下文管理器入口。"""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """异步上下文管理器出口——自动关闭后端连接。"""
        await self.close()
