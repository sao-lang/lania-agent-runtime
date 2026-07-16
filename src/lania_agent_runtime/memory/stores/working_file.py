"""Layer 1: 工作记忆 - 文件系统实现.

每个 session 一个 JSON 文件, 覆盖写 + TTL 自动过期.
设计文档推荐实现: memory-system-design.md §4.4
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from lania_agent_runtime.memory.interfaces.working_memory import WorkingMemoryStore
from lania_agent_runtime.models import (
    BudgetSnapshot,
    ContextPayloadSnapshot,
    ErrorStateSnapshot,
    PauseStateSnapshot,
    PlanStep,
    WorkingMemorySnapshot,
)


class WorkingMemoryFileStore(WorkingMemoryStore):
    """文件系统实现的工作记忆存储.

    每个 session 一个 JSON 文件.
    TTL 默认 3600 秒, 写入时计算过期时间.
    """

    def __init__(self, base_path: str = ".runtime/working_memory") -> None:
        self._base_path = Path(base_path)

    async def initialize(self) -> None:
        """确保存储目录存在."""
        self._base_path.mkdir(parents=True, exist_ok=True)

    async def close(self) -> None:
        """无需操作."""
        pass

    async def save_working_memory(self, snapshot: WorkingMemorySnapshot) -> None:
        """保存工作记忆快照 (覆盖写)."""
        expires_at = datetime.now() + timedelta(seconds=snapshot.ttl)
        data = {
            "session_id": snapshot.session_id,
            "step_index": snapshot.step_index,
            "messages": snapshot.messages,
            "message_count": snapshot.message_count,
            "total_tokens": snapshot.total_tokens,
            "status": snapshot.status,
            # 扩展字段 (M5)
            "context_payload": {
                "system_prompt": snapshot.context_payload.system_prompt,
                "memories": snapshot.context_payload.memories,
                "rag_documents": snapshot.context_payload.rag_documents,
                "injected_context": snapshot.context_payload.injected_context,
                "history": snapshot.context_payload.history,
                "tone_instruction": snapshot.context_payload.tone_instruction,
                "concepts": snapshot.context_payload.concepts,
                "entity_profile": snapshot.context_payload.entity_profile,
            },
            "plan": {
                "id": snapshot.plan.id,
                "description": snapshot.plan.description,
                "tool": snapshot.plan.tool,
                "args": snapshot.plan.args,
            } if snapshot.plan else None,
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
            "captured_at": snapshot.captured_at,
            "version": snapshot.version,
            "expires_at": expires_at.isoformat(),
        }
        path = self._base_path / f"{snapshot.session_id}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")

    async def load_working_memory(self, session_id: str) -> WorkingMemorySnapshot | None:
        """加载工作记忆快照. 返回 None 表示已过期或不存在."""
        path = self._base_path / f"{session_id}.json"
        if not path.exists():
            return None

        data = json.loads(path.read_text(encoding="utf-8"))
        # 检查 TTL 过期
        expires_at = datetime.fromisoformat(data["expires_at"])
        if expires_at < datetime.now():
            path.unlink(missing_ok=True)
            return None

        cp = data.get("context_payload", {})
        plan_data = data.get("plan")
        budget_data = data.get("budget", {})
        pause_data = data.get("pause_state", {})
        error_data = data.get("error_state", {})

        return WorkingMemorySnapshot(
            session_id=data["session_id"],
            step_index=data.get("step_index", 0),
            messages=data.get("messages", []),
            message_count=data.get("message_count", 0),
            total_tokens=data.get("total_tokens", 0),
            status=data.get("status", "running"),
            context_payload=ContextPayloadSnapshot(
                system_prompt=cp.get("system_prompt", ""),
                memories=cp.get("memories", []),
                rag_documents=cp.get("rag_documents", []),
                injected_context=cp.get("injected_context", []),
                history=cp.get("history", []),
                tone_instruction=cp.get("tone_instruction", ""),
                concepts=cp.get("concepts", []),
                entity_profile=cp.get("entity_profile", {}),
            ),
            plan=PlanStep(
                id=plan_data.get("id", ""),
                description=plan_data.get("description", ""),
                tool=plan_data.get("tool", ""),
                args=plan_data.get("args", {}),
            ) if plan_data else None,
            budget=BudgetSnapshot(
                token_used=budget_data.get("token_used", 0),
                token_limit=budget_data.get("token_limit", 100000),
                step_count=budget_data.get("step_count", 0),
                step_limit=budget_data.get("step_limit", 100),
                cost_in_cents=budget_data.get("cost_in_cents", 0),
            ),
            pause_state=PauseStateSnapshot(
                is_paused=pause_data.get("is_paused", False),
                pending_approvals=pause_data.get("pending_approvals", []),
                resume_token=pause_data.get("resume_token"),
            ),
            error_state=ErrorStateSnapshot(
                consecutive_errors=error_data.get("consecutive_errors", 0),
                max_retries=error_data.get("max_retries", 3),
                last_error=error_data.get("last_error"),
            ),
            hook_states=data.get("hook_states", {}),
            captured_at=data.get("captured_at", ""),
            version=data.get("version", 1),
        )

    async def delete_working_memory(self, session_id: str) -> None:
        """删除工作记忆快照."""
        path = self._base_path / f"{session_id}.json"
        if path.exists():
            path.unlink()

    async def exists_working_memory(self, session_id: str) -> bool:
        """检查工作记忆快照是否存在且未过期."""
        path = self._base_path / f"{session_id}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(data["expires_at"])
            if expires_at < datetime.now():
                path.unlink(missing_ok=True)
                return False
            return True
        except (json.JSONDecodeError, KeyError, ValueError):
            return False
