"""记忆压缩管理器: 合并、摘要、Token 裁剪."""

from __future__ import annotations

import asyncio
from typing import Callable

from lania_agent_runtime.memory.base import EpisodicStore
from lania_agent_runtime.models import (
    EpisodicMemoryEntry,
    MergeCandidate,
)


class CompressionManager:
    """压缩管理器.

    负责:
    - 轮次摘要: 每轮对话压缩为 1-2 句话
    - 批量合并: 情景记忆满阈值后合并为摘要
    - 合并标记: 源记录标记 merged_to, 合并结果标记 merged_from
    """

    # 合并阈值: 超过此轮数触发一次合并
    MERGE_AFTER_TURNS = 50
    # 每次合并最近多少轮
    MERGE_WINDOW_SIZE = 20
    # 是否每轮都生成摘要
    SUMMARIZE_EVERY_TURN = True
    # 原始对话超过此 token 数才需要摘要
    SUMMARIZE_MIN_TOKENS = 200

    def __init__(
        self,
        store: EpisodicStore,
        llm_summarizer: Callable[[list[str]], str] | None = None,
    ) -> None:
        """初始化 CompressionManager.

        Args:
            store: 情景记忆存储
            llm_summarizer: LLM 摘要回调(可选), 输入多条文本, 返回压缩摘要
        """
        self._store = store
        self._llm_summarizer = llm_summarizer

    async def should_merge(self, session_id: str) -> bool:
        """检查是否触发合并.

        Args:
            session_id: 会话ID

        Returns:
            达到合并阈值返回 True
        """
        count = await self._store.count_session(session_id)
        return count > 0 and count % self.MERGE_AFTER_TURNS == 0

    async def merge_session(self, session_id: str) -> str | None:
        """执行一次合并: 将最旧的 N 条未合并记录合并为一条摘要.

        Args:
            session_id: 会话ID

        Returns:
            合并后的条目ID, 如果无需合并则返回 None
        """
        if not await self.should_merge(session_id):
            return None

        # 获取未合并的最旧记录
        entries = await self._store.get_unmerged_raw(
            session_id, limit=self.MERGE_WINDOW_SIZE
        )
        if len(entries) < 2:
            return None

        return await self._do_merge(entries)

    async def merge_specific(
        self, entries: list[EpisodicMemoryEntry]
    ) -> str | None:
        """合并指定的一组记忆条目.

        Args:
            entries: 待合并的条目列表

        Returns:
            合并后的条目ID
        """
        if len(entries) < 2:
            return None
        return await self._do_merge(entries)

    async def _do_merge(
        self, entries: list[EpisodicMemoryEntry]
    ) -> str:
        """执行合并逻辑."""
        # 提取所有摘要/内容用于生成合并摘要
        texts = []
        for e in entries:
            if e.raw_content:
                texts.append(e.raw_content)
            else:
                texts.append(e.summary)

        # 使用 LLM 生成摘要(如果有), 否则简单拼接
        if self._llm_summarizer:
            merged_summary = await asyncio.to_thread(self._llm_summarizer, texts)
        else:
            merged_summary = self._fallback_summarize(texts)

        # 计算最大重要性
        max_importance = max(e.importance for e in entries)

        # 写入合并结果
        merged_entry = EpisodicMemoryEntry(
            session_id=entries[0].session_id,
            user_id=entries[0].user_id,
            turn_index=entries[-1].turn_index,
            summary=merged_summary,
            raw_content="\n---\n".join(texts),
            content_type="summary",
            source={"merged_from": [e.id for e in entries]},
            entities=list(set(
                e for entry in entries for e in entry.entities
            )),
            topics=list(set(
                t for entry in entries for t in entry.topics
            )),
            importance=max_importance,
            token_count=sum(e.token_count for e in entries),
            merged_from=[e.id for e in entries],
        )
        merged_id = await self._store.write(merged_entry)

        # 标记源记录
        for entry in entries:
            await self._store.mark_merged(entry.id, merged_id)

        return merged_id

    @staticmethod
    def _fallback_summarize(texts: list[str]) -> str:
        """回退摘要策略: 取前2条 + 计数剩余条数."""
        if not texts:
            return ""
        if len(texts) <= 3:
            return " | ".join(t[:100] for t in texts)
        # 多于3条: 取第1条 + 计数
        first = texts[0][:100]
        rest_count = len(texts) - 1
        return f"{first} ... (以及其他 {rest_count} 条合并)"

    async def summarize_turn(
        self,
        user_message: str,
        assistant_message: str,
        *,
        force: bool = False,
    ) -> str | None:
        """为单轮对话生成摘要.

        Args:
            user_message: 用户消息
            assistant_message: 助手回复
            force: 是否强制生成(忽略最小 token 限制)

        Returns:
            摘要文本, 如果不需要摘要则返回 None
        """
        raw = f"{user_message} {assistant_message}"
        token_count = len(raw)

        if not force and token_count < self.SUMMARIZE_MIN_TOKENS:
            return None

        if self._llm_summarizer:
            return await asyncio.to_thread(
                self._llm_summarizer, [raw]
            )

        # 回退: 截取 assistant 前200字符
        return assistant_message[:200] if assistant_message else ""

    async def build_candidate(
        self, session_id: str, *, limit: int = 20
    ) -> MergeCandidate | None:
        """构建一个合并候选.

        用于外部调用方在决定合并前预览信息.

        Args:
            session_id: 会话ID
            limit: 最多考虑多少条

        Returns:
            MergeCandidate 或 None
        """
        entries = await self._store.get_unmerged_raw(
            session_id, limit=limit
        )
        if len(entries) < 2:
            return None

        return MergeCandidate(
            entry_ids=[e.id for e in entries],
            session_id=session_id,
            summaries=[e.summary for e in entries],
            min_importance=min(e.importance for e in entries),
            max_importance=max(e.importance for e in entries),
            token_total=sum(e.token_count for e in entries),
        )
