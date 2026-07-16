"""Layer 2: 情景记忆 - SQLite 实现."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from lania_agent_runtime.memory.interfaces.episodic_memory import EpisodicStore
from lania_agent_runtime.memory.stores.sqlite_engine import SQLiteStorageEngine
from lania_agent_runtime.models import EpisodicMemoryEntry


class EpisodicMemorySQLiteStore(EpisodicStore):
    """情景记忆 SQLite 实现 (Layer 2).

    通过组合持有 SQLiteStorageEngine, 而非继承.
    """

    _DDL = """
        CREATE TABLE IF NOT EXISTS episodic_memory (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL,
            user_id         TEXT,
            turn_index      INTEGER NOT NULL,
            created_at      TEXT NOT NULL,
            summary         TEXT NOT NULL,
            raw_content     TEXT,
            content_type    TEXT NOT NULL DEFAULT 'raw',
            source          TEXT,
            entities        TEXT,
            topics          TEXT,
            keywords        TEXT,
            importance      REAL NOT NULL DEFAULT 0.3,
            token_count     INTEGER NOT NULL DEFAULT 0,
            merged_to       TEXT,
            merged_from     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ep_session_turn ON episodic_memory(session_id, turn_index DESC);
        CREATE INDEX IF NOT EXISTS idx_ep_user_time ON episodic_memory(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ep_entities ON episodic_memory(entities);
        CREATE INDEX IF NOT EXISTS idx_ep_topics ON episodic_memory(topics);
        CREATE INDEX IF NOT EXISTS idx_ep_importance ON episodic_memory(user_id, importance DESC);
        CREATE INDEX IF NOT EXISTS idx_ep_unmerged ON episodic_memory(merged_to) WHERE merged_to IS NULL;
    """

    def __init__(self, engine: SQLiteStorageEngine) -> None:
        self._engine = engine

    async def initialize(self) -> None:
        """创建情景记忆表 (幂等)."""
        self._engine.execute_ddl(self._DDL)

    @staticmethod
    def _row_to_episodic(row: sqlite3.Row) -> EpisodicMemoryEntry:
        """将 SQLite 行转换为 EpisodicMemoryEntry."""
        return EpisodicMemoryEntry(
            id=row["id"],
            session_id=row["session_id"],
            user_id=row["user_id"] or "",
            turn_index=row["turn_index"],
            created_at=row["created_at"],
            summary=row["summary"],
            raw_content=row["raw_content"],
            content_type=row["content_type"],
            source=json.loads(row["source"]) if row["source"] else None,
            entities=json.loads(row["entities"]) if row["entities"] else [],
            topics=json.loads(row["topics"]) if row["topics"] else [],
            keywords=json.loads(row["keywords"]) if row["keywords"] else [],
            importance=row["importance"],
            token_count=row["token_count"],
            merged_to=row["merged_to"],
            merged_from=json.loads(row["merged_from"]) if row["merged_from"] else [],
        )

    async def write(self, entry: EpisodicMemoryEntry) -> str:
        """写入一条情景记忆, 返回 entry.id."""
        conn = self._engine.conn
        if conn is None:
            return entry.id
        conn.execute(
            """INSERT INTO episodic_memory
               (id, session_id, user_id, turn_index, created_at, summary,
                raw_content, content_type, source, entities, topics,
                keywords, importance, token_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id, entry.session_id, entry.user_id, entry.turn_index,
                entry.created_at, entry.summary, entry.raw_content,
                entry.content_type,
                json.dumps(entry.source) if entry.source else None,
                json.dumps(entry.entities) if entry.entities else None,
                json.dumps(entry.topics) if entry.topics else None,
                json.dumps(entry.keywords) if entry.keywords else None,
                entry.importance, entry.token_count,
            ),
        )
        conn.commit()
        return entry.id

    async def write_batch(self, entries: list[EpisodicMemoryEntry]) -> list[str]:
        """批量写入情景记忆, 返回 ID 列表."""
        return [await self.write(e) for e in entries]

    async def recall_session(
        self,
        session_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        min_importance: float = 0.0,
    ) -> list[EpisodicMemoryEntry]:
        """按 session 召回, 按 turn_index DESC 排序."""
        conn = self._engine.conn
        if conn is None:
            return []
        if min_importance > 0.0:
            rows = conn.execute(
                """SELECT * FROM episodic_memory
                   WHERE session_id = ? AND importance >= ?
                   ORDER BY turn_index DESC LIMIT ? OFFSET ?""",
                (session_id, min_importance, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM episodic_memory
                   WHERE session_id = ?
                   ORDER BY turn_index DESC LIMIT ? OFFSET ?""",
                (session_id, limit, offset),
            ).fetchall()
        return [self._row_to_episodic(r) for r in rows]

    async def recall_user(
        self,
        user_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        min_importance: float = 0.0,
        since: str | None = None,
    ) -> list[EpisodicMemoryEntry]:
        """按用户跨 session 召回."""
        conn = self._engine.conn
        if conn is None:
            return []
        conditions = ["user_id = ?"]
        params: list[Any] = [user_id]
        if min_importance > 0.0:
            conditions.append("importance >= ?")
            params.append(min_importance)
        if since:
            conditions.append("created_at >= ?")
            params.append(since)
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""SELECT * FROM episodic_memory
                WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
        return [self._row_to_episodic(r) for r in rows]

    async def search_by_entities(
        self, user_id: str, entities: list[str], *, limit: int = 10
    ) -> list[EpisodicMemoryEntry]:
        """按实体标签召回记忆."""
        conn = self._engine.conn
        if conn is None or not entities:
            return []
        rows: list[sqlite3.Row] = []
        for entity in entities:
            r = conn.execute(
                """SELECT * FROM episodic_memory
                   WHERE user_id = ? AND entities LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, f"%{entity}%", limit),
            ).fetchall()
            rows.extend(r)
        seen = set()
        unique = []
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique.append(r)
        return [self._row_to_episodic(r) for r in unique[:limit]]

    async def search_by_topics(
        self, user_id: str, topics: list[str], *, limit: int = 10
    ) -> list[EpisodicMemoryEntry]:
        """按话题标签召回记忆."""
        conn = self._engine.conn
        if conn is None or not topics:
            return []
        rows: list[sqlite3.Row] = []
        for topic in topics:
            r = conn.execute(
                """SELECT * FROM episodic_memory
                   WHERE user_id = ? AND topics LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, f"%{topic}%", limit),
            ).fetchall()
            rows.extend(r)
        seen = set()
        unique = []
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique.append(r)
        return [self._row_to_episodic(r) for r in unique[:limit]]

    async def count_session(self, session_id: str) -> int:
        """统计 session 中的记录数."""
        conn = self._engine.conn
        if conn is None:
            return 0
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM episodic_memory WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    async def mark_merged(self, entry_id: str, merged_to_id: str) -> None:
        """标记一条记录已被合并到另一条."""
        conn = self._engine.conn
        if conn is None:
            return
        conn.execute(
            "UPDATE episodic_memory SET merged_to = ? WHERE id = ?",
            (merged_to_id, entry_id),
        )
        conn.commit()

    async def delete_before(self, user_id: str, before: str) -> int:
        """删除指定时间之前的记录(遗忘)."""
        conn = self._engine.conn
        if conn is None:
            return 0
        cursor = conn.execute(
            """DELETE FROM episodic_memory
               WHERE user_id = ? AND created_at < ? AND merged_to IS NULL""",
            (user_id, before),
        )
        conn.commit()
        return cursor.rowcount

    async def get_unmerged_raw(
        self, session_id: str, *, limit: int = 50
    ) -> list[EpisodicMemoryEntry]:
        """获取未合并的原始记录."""
        conn = self._engine.conn
        if conn is None:
            return []
        rows = conn.execute(
            """SELECT * FROM episodic_memory
               WHERE session_id = ? AND merged_to IS NULL
               ORDER BY turn_index ASC LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        return [self._row_to_episodic(r) for r in rows]
