"""
EvictionManager——遗忘管理器。

定时清理低价值/过期的记忆。
基于内容类型和 TTL 策略进行分层清理。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.memory._stores import EpisodicMemoryStore, SemanticKnowledgeStore


class EvictionManager:
    """
    遗忘管理器。

    定时清理低价值/过期的记忆。
    支持按内容类型设置不同的 TTL，以及对低频语义节点进行归档。
    """

    EPISODIC_RAW_TTL = timedelta(days=7)
    """原始记录保留天数。"""

    EPISODIC_MERGED_TTL = timedelta(days=30)
    """合并后摘要保留天数。"""

    EPISODIC_CRITICAL_TTL = timedelta(days=90)
    """关键事件保留天数。"""

    SEMANTIC_LOW_MENTION_THRESHOLD = 3
    """提及次数低于此值视为冷数据。"""

    SEMANTIC_COLD_TTL = timedelta(days=60)
    """冷数据清理天数。"""

    def __init__(
        self,
        episodic_store: EpisodicMemoryStore,
        semantic_store: SemanticKnowledgeStore,
    ) -> None:
        """
        初始化遗忘管理器。

        Args:
            episodic_store: 情景记忆存储适配器。
            semantic_store: 语义知识存储适配器。
        """
        self._episodic = episodic_store
        self._semantic = semantic_store

    async def evict_expired(self, user_id: str) -> None:
        """
        执行一次遗忘轮次。

        清理过期的情景记忆和低频语义节点。

        Args:
            user_id: 用户 ID。
        """
        now = datetime.now(timezone.utc)

        # Layer 2: 按 content_type 不同 TTL 清理
        for content_type, ttl in [
            ("raw", self.EPISODIC_RAW_TTL),
            ("summary", self.EPISODIC_MERGED_TTL),
            ("critical_event", self.EPISODIC_CRITICAL_TTL),
        ]:
            cutoff = now - ttl
            await self._episodic.delete_before(user_id, cutoff)

        # Layer 4: 低频节点归档
        await self._evict_low_mention_nodes(now)

    async def _evict_low_mention_nodes(self, now: datetime) -> None:
        """
        清理低频语义节点。

        Args:
            now: 当前时间。
        """
        nodes = await self._semantic.get_low_mention_nodes(
            threshold=self.SEMANTIC_LOW_MENTION_THRESHOLD,
        )
        for node in nodes:
            if node.last_seen_at and (now - node.last_seen_at) > self.SEMANTIC_COLD_TTL:
                await self._semantic.delete_node(node.id)
