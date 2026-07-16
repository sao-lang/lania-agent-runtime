"""Layer 1: 工作记忆 - SQLite 实现 (向后兼容).

设计文档推荐使用 WorkingMemoryFileStore(文件系统).
此 SQLite 实现保留用于向后兼容.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from lania_agent_runtime.memory.interfaces.working_memory import WorkingMemoryStore
from lania_agent_runtime.memory.stores.sqlite_engine import SQLiteStorageEngine
from lania_agent_runtime.models import (
    BudgetSnapshot,
    ContextPayloadSnapshot,
    ErrorStateSnapshot,
    PauseStateSnapshot,
    PlanStep,
    WorkingMemorySnapshot,
)


class WorkingMemorySQLiteStore(WorkingMemoryStore):
    """工作记忆 SQLite 实现 (Layer 1).

    覆盖写 + TTL 自动过期.
    通过组合持有 SQLiteStorageEngine, 而非继承.
    """

    _DDL = """
        CREATE TABLE IF NOT EXISTS working_memory (
            session_id      TEXT PRIMARY KEY,
            snapshot        TEXT NOT NULL,
            captured_at     TEXT NOT NULL,
            expires_at      TEXT NOT NULL,
            version         INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_wm_expires ON working_memory(expires_at);
    """

    def __init__(self, engine: SQLiteStorageEngine) -> None:
        self._engine = engine

    async def initialize(self) -> None:
        """创建工作记忆表 (幂等)."""
        self._engine.execute_ddl(self._DDL)

    @property
    def _conn(self):
        """向后兼容: 获取底层连接."""
        return self._engine.conn

    async def save_working_memory(self, snapshot: WorkingMemorySnapshot) -> None:
        """保存工作记忆快照 (覆盖写)."""
        conn = self._engine.conn
        if conn is None:
            return
        expires_at = (datetime.now() + timedelta(seconds=snapshot.ttl)).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO working_memory
               (session_id, snapshot, captured_at, expires_at, version)
               VALUES (?, ?, ?, ?, ?)""",
            (
                snapshot.session_id,
                json.dumps({
                    "step_index": snapshot.step_index,
                    "messages": snapshot.messages,
                    "message_count": snapshot.message_count,
                    "total_tokens": snapshot.total_tokens,
                    "status": snapshot.status,
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
                }),
                snapshot.captured_at,
                expires_at,
                snapshot.version,
            ),
        )
        conn.commit()

    async def load_working_memory(self, session_id: str) -> WorkingMemorySnapshot | None:
        """加载工作记忆快照."""
        conn = self._engine.conn
        if conn is None:
            return None
        row = conn.execute(
            "SELECT * FROM working_memory WHERE session_id = ? AND expires_at > datetime('now')",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["snapshot"])
        cp = data.get("context_payload", {})
        plan_data = data.get("plan")
        budget_data = data.get("budget", {})
        pause_data = data.get("pause_state", {})
        error_data = data.get("error_state", {})

        return WorkingMemorySnapshot(
            session_id=row["session_id"],
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
            captured_at=row["captured_at"],
            version=row["version"],
        )

    async def delete_working_memory(self, session_id: str) -> None:
        """删除工作记忆快照."""
        conn = self._engine.conn
        if conn is None:
            return
        conn.execute(
            "DELETE FROM working_memory WHERE session_id = ?", (session_id,),
        )
        conn.commit()

    async def exists_working_memory(self, session_id: str) -> bool:
        """检查工作记忆快照是否存在且未过期."""
        conn = self._engine.conn
        if conn is None:
            return False
        row = conn.execute(
            "SELECT 1 FROM working_memory WHERE session_id = ? AND expires_at > datetime('now')",
            (session_id,),
        ).fetchone()
        return row is not None
