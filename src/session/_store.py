"""
SessionStore——key 约定 + JSON 序列化。

将 SessionRecord 的读写转化为 SessionPersistence 的键值操作。
键名格式（与 memory 的 wm:/ep: 前缀并列，互不冲突）：
  ss:{session_id}              → SessionRecord（JSON 序列化，含完整消息历史）
  ssi:{user_id}:{session_id}   → 用户 → 会话索引（值只存存在标记）
  ssh:{session_id}:{index}   → 历史消息分块（Phase 2，消息数超过 chunk_size 时启用）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.session._models import SessionRecord, SessionSummary
from src.session._persistence import SessionPersistence


class SessionStore:
    """会话存储适配器——key 约定 + JSON 序列化。

    Attributes:
        _store: 底层 SessionPersistence 实例。
    """

    def __init__(self, persistence: SessionPersistence) -> None:
        """初始化 SessionStore。

        Args:
            persistence: 满足 SessionPersistence 接口的持久化实例。
        """
        self._store = persistence

    @staticmethod
    def _record_key(session_id: str) -> str:
        """构造会话记录主键。"""
        return f"ss:{session_id}"

    @staticmethod
    def _user_index_key(user_id: str, session_id: str) -> str:
        """构造用户 → 会话索引键。"""
        return f"ssi:{user_id}:{session_id}"

    @staticmethod
    def parse_user_index_key(key: str) -> str | None:
        """从索引键解析 session_id。

        Args:
            key: ssi:{user_id}:{session_id} 格式的键。

        Returns:
            session_id；格式不合法时返回 None。
        """
        parts = key.split(":", 2)
        if len(parts) == 3 and parts[0] == "ssi":
            return parts[2]
        return None

    @staticmethod
    def _chunk_key(session_id: str, index: int) -> str:
        """构造历史分块键。"""
        return f"ssh:{session_id}:{index}"

    @staticmethod
    def _chunk_prefix(session_id: str) -> str:
        """构造历史分块键前缀。"""
        return f"ssh:{session_id}:"

    async def _delete_chunks(self, session_id: str) -> None:
        """删除指定会话的全部历史分块。"""
        keys = await self._store.list_keys(self._chunk_prefix(session_id))
        for key in keys:
            await self._store.delete(key)

    async def _load_chunks(self, record: SessionRecord) -> None:
        """从分块键重建完整消息历史（缺失/损坏的分块跳过）。"""
        messages: list[dict] = []
        for index in range(record.chunk_count):
            data = await self._store.get(self._chunk_key(record.session_id, index))
            if data is None:
                continue
            try:
                chunk = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(chunk, list):
                messages.extend(chunk)
        record.messages = messages

    async def save_record(self, record: SessionRecord, *, chunk_size: int = 0) -> None:
        """持久化会话记录（可选分块存储）。

        chunk_size > 0 且消息数超过阈值时，历史消息按 ssh:{session_id}:{index}
        分块存储，ss: 记录只保留元数据（messages 置空 + chunk_count）；
        否则保持内联存储。切换布局时会清理残留分块，保证同一会话
        不会同时存在两套布局。

        Args:
            record: 会话记录。
            chunk_size: 分块阈值，0 表示不启用分块。
        """
        chunks: list[list[dict]] = []
        if chunk_size > 0 and len(record.messages) > chunk_size:
            chunks = [
                record.messages[i : i + chunk_size]
                for i in range(0, len(record.messages), chunk_size)
            ]

        if chunks:
            await self._delete_chunks(record.session_id)
            for index, chunk in enumerate(chunks):
                await self._store.put(
                    self._chunk_key(record.session_id, index),
                    json.dumps(chunk, ensure_ascii=False).encode("utf-8"),
                )
            record.chunk_count = len(chunks)
            stored_messages = record.messages
            record.messages = []
            await self._store.put(self._record_key(record.session_id), self._serialize(record))
            # 恢复内存中的完整消息列表（缓存与后续增量提交依赖）
            record.messages = stored_messages
        else:
            await self._delete_chunks(record.session_id)
            record.chunk_count = 0
            await self._store.put(self._record_key(record.session_id), self._serialize(record))

    async def load_record(self, session_id: str) -> SessionRecord | None:
        """读取会话记录。

        Args:
            session_id: 会话 ID。

        Returns:
            会话记录；不存在或反序列化失败时返回 None。
        """
        data = await self._store.get(self._record_key(session_id))
        if data is None:
            return None
        record = self._deserialize(data)
        if record is not None and record.chunk_count > 0:
            await self._load_chunks(record)
        return record

    async def delete_record(self, session_id: str) -> None:
        """删除会话记录主键与历史分块。

        Args:
            session_id: 会话 ID。
        """
        await self._delete_chunks(session_id)
        await self._store.delete(self._record_key(session_id))

    async def save_user_index(self, user_id: str, session_id: str) -> None:
        """写入用户 → 会话索引（只存存在标记）。

        Args:
            user_id: 用户 ID。
            session_id: 会话 ID。
        """
        await self._store.put(self._user_index_key(user_id, session_id), b"1")

    async def delete_user_index(self, user_id: str, session_id: str) -> None:
        """删除用户 → 会话索引。

        Args:
            user_id: 用户 ID。
            session_id: 会话 ID。
        """
        await self._store.delete(self._user_index_key(user_id, session_id))

    async def list_user_index_keys(self, user_id: str) -> list[str]:
        """列出指定用户的会话索引键。

        Args:
            user_id: 用户 ID。

        Returns:
            索引键列表。
        """
        return await self._store.list_keys(f"ssi:{user_id}:")

    def _serialize(self, record: SessionRecord) -> bytes:
        """序列化会话记录为 bytes。"""
        return json.dumps(self._to_dict(record), ensure_ascii=False).encode("utf-8")

    def _deserialize(self, data: bytes) -> SessionRecord | None:
        """反序列化 bytes 为会话记录。"""
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        return self._from_dict(raw)

    @staticmethod
    def _to_dict(record: SessionRecord) -> dict[str, Any]:
        """将会话记录转为可 JSON 序列化的字典。"""
        return {
            "session_id": record.session_id,
            "agent_id": record.agent_id,
            "user_id": record.user_id,
            "title": record.title,
            "status": record.status,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "ended_at": record.ended_at.isoformat() if record.ended_at else None,
            "turn_count": record.turn_count,
            "message_count": record.message_count,
            "step_count": record.step_count,
            "step_index": record.step_index,
            "token_used": record.token_used,
            "last_error": record.last_error,
            "metadata": record.metadata,
            "messages": record.messages,
            "chunk_count": record.chunk_count,
            "version": record.version,
            "ttl": record.ttl,
        }

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> SessionRecord:
        """从字典构造会话记录。"""
        return SessionRecord(
            session_id=raw.get("session_id", ""),
            agent_id=raw.get("agent_id", ""),
            user_id=raw.get("user_id"),
            title=raw.get("title", ""),
            status=raw.get("status", "active"),
            created_at=cls._parse_datetime(raw.get("created_at")),
            updated_at=cls._parse_datetime(raw.get("updated_at")),
            ended_at=cls._parse_datetime(raw.get("ended_at")),
            turn_count=raw.get("turn_count", 0),
            message_count=raw.get("message_count", 0),
            step_count=raw.get("step_count", 0),
            step_index=raw.get("step_index", 0),
            token_used=raw.get("token_used", 0),
            last_error=raw.get("last_error"),
            metadata=raw.get("metadata", {}),
            messages=raw.get("messages", []),
            chunk_count=raw.get("chunk_count", 0),
            version=raw.get("version", 1),
            ttl=raw.get("ttl", 0),
        )

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        """解析 ISO 格式时间字符串。"""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def to_summary(record: SessionRecord) -> SessionSummary:
        """将会话记录转为轻量摘要（不含 messages）。

        Args:
            record: 会话记录。

        Returns:
            会话摘要。
        """
        return SessionSummary(
            session_id=record.session_id,
            title=record.title,
            status=record.status,
            user_id=record.user_id,
            turn_count=record.turn_count,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
