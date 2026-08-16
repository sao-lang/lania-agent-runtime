"""
SessionService——会话统一外观。

管理会话生命周期、元数据与完整原始消息历史。上层只感知这一个入口。
内部维护 session_id → SessionRecord 内存缓存，不依赖 ctx.services。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from src.session._config import SessionConfig
from src.session._models import SessionRecord, SessionSummary
from src.session._persistence import SessionPersistence
from src.session._store import SessionStore

logger = logging.getLogger(__name__)


class SessionService:
    """会话统一外观——管理会话生命周期、元数据与完整消息历史。"""

    def __init__(
        self,
        persistence: SessionPersistence,
        config: SessionConfig | None = None,
    ) -> None:
        """初始化 SessionService。

        Args:
            persistence: 满足 SessionPersistence 接口的持久化实例
                （可与 MemoryService 共享同一后端，按 key 前缀隔离，非耦合）。
            config: 会话配置。不提供则使用默认配置。
        """
        self._store = SessionStore(persistence)
        self._persistence = persistence
        self._config = config or SessionConfig()
        self._cache: dict[str, SessionRecord] = {}

    async def create(
        self,
        session_id: str,
        *,
        agent_id: str = "",
        user_id: str | None = None,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionRecord:
        """创建会话（幂等：已存在则返回现有记录，支持 resume 场景）。

        Args:
            session_id: 会话 ID。
            agent_id: 所属 Agent。
            user_id: 关联用户。
            title: 会话标题。
            metadata: 外部扩展字段。

        Returns:
            会话记录。
        """
        existing = await self.get(session_id)
        if existing is not None:
            return existing

        now = datetime.now()
        record = SessionRecord(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            title=title,
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
            ttl=self._config.ttl_seconds,
        )
        await self._store.save_record(record, chunk_size=self._config.chunk_size)
        if user_id:
            await self._store.save_user_index(user_id, session_id)
        self._cache[session_id] = record
        return record

    async def get(self, session_id: str) -> SessionRecord | None:
        """读取会话记录（内存缓存优先，含 TTL 过期检查）。

        Args:
            session_id: 会话 ID。

        Returns:
            会话记录；不存在或已过期时返回 None。
        """
        cached = self._cache.get(session_id)
        if cached is not None:
            if self._is_expired(cached):
                self._cache.pop(session_id, None)
                return None
            return cached

        record = await self._store.load_record(session_id)
        if record is None:
            return None
        if self._is_expired(record):
            await self._store.delete_record(session_id)
            return None
        self._cache[session_id] = record
        return record

    async def list_user_sessions(
        self,
        user_id: str,
        *,
        limit: int = 20,
        status: str | None = None,
        offset: int = 0,
    ) -> list[SessionSummary]:
        """列出用户的会话摘要（按 updated_at 倒序，回读 ss: 记录组装）。

        Args:
            user_id: 用户 ID。
            limit: 最大返回条数。
            status: 可选的状态过滤。
            offset: 分页偏移量（默认 0）。

        Returns:
            会话摘要列表。
        """
        keys = await self._store.list_user_index_keys(user_id)
        records: list[SessionRecord] = []
        for key in keys:
            session_id = SessionStore.parse_user_index_key(key)
            if session_id is None:
                continue
            record = await self.get(session_id)
            if record is not None:
                records.append(record)

        if status:
            records = [r for r in records if r.status == status]
        records.sort(key=lambda r: r.updated_at or datetime.min, reverse=True)
        return [SessionStore.to_summary(r) for r in records[offset : offset + limit]]

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict],
        *,
        step_index: int | None = None,
    ) -> SessionRecord | None:
        """增量提交消息：以 record.message_count 为基准只追加新消息（幂等）。

        超过 config.max_history_messages 时裁掉最旧消息；单条消息超过
        config.max_message_chars 时截断。step_index 用于续聊时对齐游标。

        存储约定：**不保存 system 消息**——system prompt 属于运行时配置
        （AgentRuntime / ContextPayload），会话历史只包含 user/assistant/tool。
        旧格式记录（v2 前首条为 system）会在提交时自动剥离自愈。

        Args:
            session_id: 会话 ID。
            messages: 当前完整消息列表（含历史 + 本轮新增）。
            step_index: 当前 step 游标（可选）。

        Returns:
            更新后的会话记录；会话不存在时返回 None。
        """
        record = await self.get(session_id)
        if record is None:
            return None

        # system 属于运行时配置，不入会话历史
        incoming = [m for m in self._truncate_messages(list(messages)) if m.get("role") != "system"]

        # 旧格式兼容：v2 前历史以 system 开头，剥离后作为新基准（自愈）
        if record.messages and record.messages[0].get("role") == "system":
            record.messages = record.messages[1:]
            record.message_count = len(record.messages)

        if record.message_count <= len(incoming):
            new_messages = incoming[record.message_count :]
            if new_messages:
                record.messages.extend(new_messages)
        else:
            # 历史消息已被外部裁剪（message_count 落后），整体重建
            record.messages = incoming

        # 超出上限时裁掉最旧消息
        if self._config.max_history_messages > 0:
            overflow = len(record.messages) - self._config.max_history_messages
            if overflow > 0:
                record.messages = record.messages[overflow:]

        record.message_count = len(record.messages)
        record.turn_count = sum(1 for m in record.messages if m.get("role") == "user")
        if step_index is not None:
            record.step_index = max(record.step_index, step_index)
        record.updated_at = datetime.now()

        await self._store.save_record(record, chunk_size=self._config.chunk_size)
        self._cache[session_id] = record
        return record

    async def update_status(
        self,
        session_id: str,
        status: str,
        *,
        last_error: str | None = None,
    ) -> SessionRecord | None:
        """更新会话状态（paused / error / cancelled 等）。

        Args:
            session_id: 会话 ID。
            status: 新状态。
            last_error: 最后错误信息（可选）。

        Returns:
            更新后的会话记录；会话不存在时返回 None。
        """
        record = await self.get(session_id)
        if record is None:
            return None
        record.status = status
        if last_error is not None:
            record.last_error = last_error
        record.updated_at = datetime.now()
        await self._store.save_record(record, chunk_size=self._config.chunk_size)
        self._cache[session_id] = record
        return record

    async def finalize(
        self,
        session_id: str,
        *,
        status: str = "ended",
        token_used: int = 0,
        step_count: int = 0,
        last_error: str | None = None,
    ) -> SessionRecord | None:
        """结束会话：更新状态/统计，标记 ended_at（消息已在 step 间提交）。

        Args:
            session_id: 会话 ID。
            status: 结束状态。
            token_used: 累计 token 用量（Runtime 实时计量的快照）。
            step_count: 累计 step 数。
            last_error: 最后错误信息。

        Returns:
            更新后的会话记录；会话不存在时返回 None。
        """
        record = await self.get(session_id)
        if record is None:
            return None
        now = datetime.now()
        record.status = status
        record.token_used = token_used
        record.step_count = step_count
        record.ended_at = now
        record.updated_at = now
        if last_error is not None:
            record.last_error = last_error
        await self._store.save_record(record, chunk_size=self._config.chunk_size)
        self._cache[session_id] = record
        return record

    async def delete(self, session_id: str) -> None:
        """删除会话记录（含用户索引）。

        Args:
            session_id: 会话 ID。
        """
        record = self._cache.pop(session_id, None)
        if record is None:
            record = await self._store.load_record(session_id)
        if record is not None and record.user_id:
            await self._store.delete_user_index(record.user_id, session_id)
        await self._store.delete_record(session_id)

    async def close(self) -> None:
        """关闭持久化后端。"""
        self._cache.clear()
        close = getattr(self._persistence, "close", None)
        if callable(close):
            await close()

    def _truncate_messages(self, messages: list[dict]) -> list[dict]:
        """按 max_message_chars 截断单条消息的 content。"""
        if self._config.max_message_chars <= 0:
            return messages
        result: list[dict] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str) and len(content) > self._config.max_message_chars:
                truncated = dict(msg)
                truncated["content"] = content[: self._config.max_message_chars]
                result.append(truncated)
            else:
                result.append(msg)
        return result

    def _is_expired(self, record: SessionRecord) -> bool:
        """TTL 过期检查（0 = 永久）。"""
        if record.ttl <= 0:
            return False
        updated = record.updated_at or record.created_at or datetime.min
        return (datetime.now() - updated).total_seconds() > record.ttl
