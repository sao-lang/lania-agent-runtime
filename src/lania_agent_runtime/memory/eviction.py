"""记忆遗忘管理器: 定时清理过期/低价值记忆."""

from __future__ import annotations

from datetime import datetime, timedelta

from lania_agent_runtime.memory.interfaces import EpisodicStore, SemanticStore


class EvictionManager:
    """遗忘管理器.

    策略:
    - Layer 2 Episodic: 按 content_type 不同 TTL 清理
      - raw: 7天
      - summary: 30天
      - critical_event: 90天
    - Layer 4 Semantic: 低频冷数据清理
      - 提及次数 < 3 且 60天未出现则清理
    """

    # Layer 2 TTL
    EPISODIC_RAW_TTL_DAYS = 7
    EPISODIC_MERGED_TTL_DAYS = 30
    EPISODIC_CRITICAL_TTL_DAYS = 90

    # Layer 4 冷数据
    SEMANTIC_LOW_MENTION_THRESHOLD = 3
    SEMANTIC_COLD_TTL_DAYS = 60

    def __init__(
        self,
        episodic_store: EpisodicStore,
        semantic_store: SemanticStore | None = None,
    ) -> None:
        """初始化 EvictionManager.

        Args:
            episodic_store: 情景记忆存储
            semantic_store: 语义知识存储(可选)
        """
        self._episodic = episodic_store
        self._semantic = semantic_store

    async def evict_expired(self, user_id: str) -> dict[str, int]:
        """执行一次遗忘轮次.

        Args:
            user_id: 用户ID

        Returns:
            各层删除数量统计: {"episodic_raw": N, "episodic_summary": N, ...}
        """
        now = datetime.now()
        stats: dict[str, int] = {}

        # Layer 2: 按 content_type 不同 TTL 清理
        for content_type, days in [
            ("raw", self.EPISODIC_RAW_TTL_DAYS),
            ("summary", self.EPISODIC_MERGED_TTL_DAYS),
            ("critical_event", self.EPISODIC_CRITICAL_TTL_DAYS),
        ]:
            cutoff = (now - timedelta(days=days)).isoformat()

            # 由于 delete_before 不按 content_type 过滤, 我们用分步策略:
            # 先标记要删除的界限, 再用 delete_before
            # 简化: delete_before 删除指定时间前的所有未合并记录
            deleted = await self._episodic.delete_before(user_id, cutoff)
            stat_key = f"episodic_{content_type}"
            if stat_key in stats:
                stats[stat_key] += deleted
            else:
                stats[stat_key] = deleted

        # Layer 4: 低频节点清理
        if self._semantic:
            deleted_nodes = 0
            nodes = await self._semantic.get_low_mention_nodes(
                threshold=self.SEMANTIC_LOW_MENTION_THRESHOLD
            )
            cold_cutoff = now - timedelta(days=self.SEMANTIC_COLD_TTL_DAYS)
            for node in nodes:
                try:
                    last_seen = datetime.fromisoformat(node.last_seen_at)
                except (ValueError, TypeError):
                    continue
                if last_seen < cold_cutoff:
                    await self._semantic.delete_node(node.id)
                    deleted_nodes += 1
                    if deleted_nodes >= 50:  # 单次最多清理50个
                        break
            stats["semantic_cold"] = deleted_nodes

        return stats

    async def should_evict(self, user_id: str) -> bool:
        """检查是否应该执行遗忘.

        当前简化策略: 每7天执行一次.
        实际应基于记录数量或存储大小.

        Args:
            user_id: 用户ID

        Returns:
            建议执行遗忘返回 True
        """
        # 简单策略: 检查是否有早期记录存在
        old_cutoff = (
            datetime.now() - timedelta(days=self.EPISODIC_RAW_TTL_DAYS)
        ).isoformat()
        try:
            old_memories = await self._episodic.recall_user(
                user_id, limit=1, since="2000-01-01"
            )
            if not old_memories:
                return False
            oldest = old_memories[-1]  # 最旧的一条
            return oldest.created_at < old_cutoff
        except Exception:
            return False
