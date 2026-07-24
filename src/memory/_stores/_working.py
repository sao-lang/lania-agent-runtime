"""
WorkingMemoryStore——工作记忆存储适配器。

基于 MemoryPersistence 实现，键名前缀 wm:{session_id}。
特性：
- 覆盖写（一个 session 只保留最新快照）
- TTL 自动过期
- 一次性：恢复后即刻删除
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.memory._persistence import MemoryPersistence
from src.memory._stores._base import BaseStore
from src.memory._types import (
    BudgetSnapshot,
    ErrorStateSnapshot,
    PauseState,
    WorkingMemorySnapshot,
)


class WorkingMemoryStore(BaseStore[WorkingMemorySnapshot]):
    """
    工作记忆存储适配器。

    将 WorkingMemorySnapshot 的读写转化为 MemoryPersistence 的键值操作。
    键名格式: wm:{session_id}
    """

    def __init__(self, persistence: MemoryPersistence) -> None:
        """初始化 WorkingMemoryStore。"""
        super().__init__(persistence)

    def _key(self, session_id: str) -> str:
        """构造存储键名。"""
        return f"wm:{session_id}"

    def _serialize(self, snapshot: WorkingMemorySnapshot) -> bytes:
        """将快照序列化为 bytes。"""
        return self._serialize_json(snapshot, self._to_dict)

    def _deserialize(self, data: bytes) -> WorkingMemorySnapshot | None:
        """将 bytes 反序列化为快照。"""
        return self._deserialize_json(data, self._from_dict)

    @staticmethod
    def _to_dict(snapshot: WorkingMemorySnapshot) -> dict[str, Any]:
        return {
            "session_id": snapshot.session_id,
            "step_index": snapshot.step_index,
            "messages": snapshot.messages,
            "message_count": snapshot.message_count,
            "total_tokens": snapshot.total_tokens,
            "context_payload": snapshot.context_payload,
            "status": snapshot.status,
            "plan": snapshot.plan,
            "budget": {
                "token_used": snapshot.budget.token_used,
                "token_limit": snapshot.budget.token_limit,
                "step_count": snapshot.budget.step_count,
                "step_limit": snapshot.budget.step_limit,
                "cost_in_cents": snapshot.budget.cost_in_cents,
            },
            "pause_state": {
                "is_paused": snapshot.pause_state.is_paused,
                "pending_approvals": snapshot.pause_state.pending_approvals,
                "resume_token": snapshot.pause_state.resume_token,
            },
            "error_state": {
                "consecutive_errors": snapshot.error_state.consecutive_errors,
                "max_retries": snapshot.error_state.max_retries,
                "last_error": snapshot.error_state.last_error,
            },
            "hook_states": snapshot.hook_states,
            "captured_at": snapshot.captured_at.isoformat() if snapshot.captured_at else None,
            "version": snapshot.version,
            "ttl": snapshot.ttl,
        }

    @staticmethod
    def _from_dict(raw: dict) -> WorkingMemorySnapshot:
        return WorkingMemorySnapshot(
            session_id=raw.get("session_id", ""),
            step_index=raw.get("step_index", 0),
            messages=raw.get("messages", []),
            message_count=raw.get("message_count", 0),
            total_tokens=raw.get("total_tokens", 0),
            context_payload=raw.get("context_payload", {}),
            status=raw.get("status", "running"),
            plan=raw.get("plan"),
            budget=BudgetSnapshot(**raw.get("budget", {})),
            pause_state=PauseState(**raw.get("pause_state", {})),
            error_state=ErrorStateSnapshot(**raw.get("error_state", {})),
            hook_states=raw.get("hook_states", {}),
            captured_at=(
                datetime.fromisoformat(raw["captured_at"])
                if raw.get("captured_at")
                else None
            ),
            version=raw.get("version", 1),
            ttl=raw.get("ttl", 3600),
        )

    async def save(self, snapshot: WorkingMemorySnapshot) -> None:
        """
        保存快照。覆盖 session_id 对应的现有快照。

        Args:
            snapshot: 工作记忆快照。
        """
        data = self._serialize(snapshot)
        await self._store.put(self._key(snapshot.session_id), data)

    async def load(self, session_id: str) -> WorkingMemorySnapshot | None:
        """
        加载快照。

        Args:
            session_id: 会话 ID。

        Returns:
            快照对象，如果不存在或已过期则返回 None。
        """
        data = await self._store.get(self._key(session_id))
        if data is None:
            return None
        return self._deserialize(data)

    async def delete(self, session_id: str) -> None:
        """
        删除快照。

        Args:
            session_id: 会话 ID。
        """
        await self._store.delete(self._key(session_id))

    async def exists(self, session_id: str) -> bool:
        """
        检查快照是否存在且未过期。

        Args:
            session_id: 会话 ID。

        Returns:
            快照是否存在。
        """
        data = await self._store.get(self._key(session_id))
        return data is not None
