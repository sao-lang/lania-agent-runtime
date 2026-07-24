"""
CompressionManager——记忆压缩管理器。

决定何时压缩记忆、压缩到什么程度。
支持轮次摘要和批量合并。
"""

from __future__ import annotations

from src.memory._stores import EpisodicMemoryStore


class CompressionManager:
    """
    记忆压缩管理器。

    控制情景记忆的合并与摘要策略：
    - 每 MERGE_AFTER_TURNS 轮触发一次批量合并
    - 每次合并最近 MERGE_WINDOW_SIZE 条记录
    - 每轮是否生成摘要由 SUMMARIZE_EVERY_TURN 控制
    """

    MERGE_AFTER_TURNS = 50
    """合并阈值：多少轮后触发一次合并。"""

    MERGE_WINDOW_SIZE = 20
    """合并窗口：每次合并最近的多少条记录。"""

    SUMMARIZE_EVERY_TURN = True
    """是否每轮都生成摘要。"""

    SUMMARIZE_MIN_TOKENS = 200
    """原始对话超过此 token 数才需要摘要。"""

    def __init__(self, episodic_store: EpisodicMemoryStore) -> None:
        """
        初始化压缩管理器。

        Args:
            episodic_store: 情景记忆存储适配器。
        """
        self._episodic = episodic_store

    async def should_merge(self, session_id: str) -> bool:
        """
        检查是否需要触发合并。

        Args:
            session_id: 会话 ID。

        Returns:
            是否需要合并。
        """
        count = await self._episodic.count_session(session_id)
        return count > 0 and count % self.MERGE_AFTER_TURNS == 0

    async def merge_session(self, session_id: str) -> None:
        """
        将最旧的 N 条合并为一条摘要。

        当前实现将多条记录的 summary 拼接为目标摘要。
        Phase 3 可接入 LLM 生成更智能的摘要。

        Args:
            session_id: 会话 ID。
        """
        entries = await self._episodic.recall_session(
            session_id,
            limit=self.MERGE_WINDOW_SIZE,
            offset=0,
        )
        if not entries:
            return

        # 合并摘要
        summaries = [e.summary for e in entries if e.summary]
        merged_summary = " | ".join(summaries)
        if len(merged_summary) > 1000:
            merged_summary = merged_summary[:1000] + "..."

        # 创建合并条目
        from src.memory._types import EpisodicMemoryEntry

        merged_entry = EpisodicMemoryEntry(
            session_id=session_id,
            turn_index=entries[-1].turn_index,
            summary=merged_summary,
            content_type="summary",
            merged_from=[e.id for e in entries],
            importance=max(e.importance for e in entries),
        )
        merged_id = await self._episodic.write(merged_entry)

        # 标记源记录
        for entry in entries:
            await self._episodic.mark_merged(entry.id, merged_id)
