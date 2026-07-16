"""Layer 5: 行为模式 - SQLite 实现."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from lania_agent_runtime.memory.interfaces.behavioral_pattern import BehavioralStore
from lania_agent_runtime.memory.stores.sqlite_engine import SQLiteStorageEngine
from lania_agent_runtime.models import BehavioralPattern


class BehavioralPatternSQLiteStore(BehavioralStore):
    """行为模式 SQLite 实现 (Layer 5).

    通过组合持有 SQLiteStorageEngine, 而非继承.
    """

    _DDL = """
        CREATE TABLE IF NOT EXISTS behavioral_pattern (
            user_id             TEXT PRIMARY KEY,
            patterns            TEXT NOT NULL,
            total_interactions  INTEGER NOT NULL DEFAULT 0,
            version             INTEGER NOT NULL DEFAULT 1,
            last_converged_at   TEXT,
            last_interaction_at TEXT,
            created_at          TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS behavioral_lock (
            user_id         TEXT PRIMARY KEY,
            locked_at       TEXT NOT NULL,
            expires_at      TEXT NOT NULL,
            lock_token      TEXT NOT NULL
        );
    """

    def __init__(self, engine: SQLiteStorageEngine) -> None:
        self._engine = engine

    async def initialize(self) -> None:
        """创建行为模式表 (幂等)."""
        self._engine.execute_ddl(self._DDL)

    async def upsert_behavioral_pattern(
        self, user_id: str, patterns: dict[str, Any]
    ) -> None:
        """写入/覆盖用户行为模式. version 自增."""
        conn = self._engine.conn
        if conn is None:
            return
        now = datetime.now().isoformat()
        existing = conn.execute(
            "SELECT * FROM behavioral_pattern WHERE user_id = ?", (user_id,),
        ).fetchone()

        if existing:
            version = existing["version"] + 1
            total = existing["total_interactions"] + 1
            created_at_val = existing["created_at"]
        else:
            version = 1
            total = 1
            created_at_val = now

        conn.execute(
            """INSERT OR REPLACE INTO behavioral_pattern
               (user_id, patterns, total_interactions, version,
                last_converged_at, last_interaction_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, json.dumps(patterns), total, version,
             now, now, created_at_val),
        )
        conn.commit()

    async def get_behavioral_pattern(self, user_id: str) -> BehavioralPattern | None:
        """读取用户行为模式."""
        conn = self._engine.conn
        if conn is None:
            return None
        row = conn.execute(
            "SELECT * FROM behavioral_pattern WHERE user_id = ?", (user_id,),
        ).fetchone()
        if not row:
            return None
        return BehavioralPattern(
            user_id=row["user_id"],
            patterns=json.loads(row["patterns"]),
            total_interactions=row["total_interactions"],
            version=row["version"],
            last_converged_at=row["last_converged_at"] or "",
            last_interaction_at=row["last_interaction_at"] or "",
            created_at=row["created_at"],
        )

    async def delete_behavioral_pattern(self, user_id: str) -> None:
        """删除用户行为模式."""
        conn = self._engine.conn
        if conn is None:
            return
        conn.execute(
            "DELETE FROM behavioral_pattern WHERE user_id = ?", (user_id,),
        )
        conn.commit()

    async def acquire_lock(self, user_id: str, ttl: int = 30) -> bool:
        """获取用户级锁(防止并发收敛冲突)."""
        conn = self._engine.conn
        if conn is None:
            return False
        now = datetime.now()
        expires_at = (now + timedelta(seconds=ttl)).isoformat()
        now_iso = now.isoformat()

        # 清理过期锁
        conn.execute(
            "DELETE FROM behavioral_lock WHERE expires_at < ?", (now_iso,),
        )

        # 尝试获取锁
        token = str(uuid.uuid4())
        try:
            conn.execute(
                """INSERT INTO behavioral_lock (user_id, locked_at, expires_at, lock_token)
                   VALUES (?, ?, ?, ?)""",
                (user_id, now_iso, expires_at, token),
            )
            conn.commit()
            return True
        except Exception:
            return False
