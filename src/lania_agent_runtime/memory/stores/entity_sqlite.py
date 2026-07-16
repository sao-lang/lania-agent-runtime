"""Layer 3: 实体记忆 - SQLite 实现."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from lania_agent_runtime.memory.interfaces.entity_memory import EntityStore
from lania_agent_runtime.memory.stores.sqlite_engine import SQLiteStorageEngine
from lania_agent_runtime.models import EntityMemoryEntry


class EntityMemorySQLiteStore(EntityStore):
    """实体记忆 SQLite 实现 (Layer 3).

    通过组合持有 SQLiteStorageEngine, 而非继承.
    """

    _DDL = """
        CREATE TABLE IF NOT EXISTS entity_memory (
            entity_type     TEXT NOT NULL,
            entity_key      TEXT NOT NULL,
            attributes      TEXT NOT NULL,
            history         TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            last_updated_at TEXT NOT NULL,
            last_source_session TEXT,
            ttl             TEXT,
            PRIMARY KEY (entity_type, entity_key)
        );
    """

    def __init__(self, engine: SQLiteStorageEngine) -> None:
        self._engine = engine

    async def initialize(self) -> None:
        """创建实体记忆表 (幂等)."""
        self._engine.execute_ddl(self._DDL)

    async def upsert_entity_attribute(
        self,
        entity_type: str,
        entity_key: str,
        attr_name: str,
        value: Any,
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> None:
        """更新实体单个属性."""
        conn = self._engine.conn
        if conn is None:
            return
        now = datetime.now().isoformat()
        row = conn.execute(
            "SELECT * FROM entity_memory WHERE entity_type = ? AND entity_key = ?",
            (entity_type, entity_key),
        ).fetchone()

        if row:
            attributes = json.loads(row["attributes"])
            history = json.loads(row["history"])
            created_at_val = row["created_at"]
        else:
            attributes = {}
            history = {}
            created_at_val = now

        attr_entry = {
            "value": value,
            "confidence": confidence,
            "recorded_at": now,
            "source_session": source_session,
        }
        attributes[attr_name] = attr_entry

        if attr_name not in history:
            history[attr_name] = []
        history[attr_name].append(attr_entry)
        history[attr_name] = history[attr_name][-20:]  # 保留最近20条

        conn.execute(
            """INSERT OR REPLACE INTO entity_memory
               (entity_type, entity_key, attributes, history,
                created_at, last_updated_at, last_source_session)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (entity_type, entity_key, json.dumps(attributes), json.dumps(history),
             created_at_val, now, source_session),
        )
        conn.commit()

    async def upsert_attributes(
        self,
        entity_type: str,
        entity_key: str,
        attributes: dict[str, Any],
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> None:
        """批量更新多个属性."""
        for attr_name, value in attributes.items():
            await self.upsert_entity_attribute(
                entity_type, entity_key, attr_name, value,
                confidence=confidence, source_session=source_session,
            )

    async def get_entity_profile(
        self, entity_type: str, entity_key: str
    ) -> EntityMemoryEntry | None:
        """读取完整实体画像."""
        conn = self._engine.conn
        if conn is None:
            return None
        row = conn.execute(
            "SELECT * FROM entity_memory WHERE entity_type = ? AND entity_key = ?",
            (entity_type, entity_key),
        ).fetchone()
        if not row:
            return None
        return EntityMemoryEntry(
            entity_type=row["entity_type"],
            entity_key=row["entity_key"],
            attributes=json.loads(row["attributes"]),
            history=json.loads(row["history"]),
            created_at=row["created_at"],
            last_updated_at=row["last_updated_at"],
            last_source_session=row["last_source_session"] or "",
            ttl=row["ttl"],
        )

    async def read_batch(
        self, keys: list[tuple[str, str]]
    ) -> list[EntityMemoryEntry | None]:
        """批量读取实体画像."""
        return [await self.get_entity_profile(et, ek) for et, ek in keys]

    async def delete_entity(self, entity_type: str, entity_key: str) -> None:
        """删除整个实体."""
        conn = self._engine.conn
        if conn is None:
            return
        conn.execute(
            "DELETE FROM entity_memory WHERE entity_type = ? AND entity_key = ?",
            (entity_type, entity_key),
        )
        conn.commit()

    async def list_by_type(
        self, entity_type: str, *, limit: int = 100
    ) -> list[EntityMemoryEntry]:
        """按类型列出所有实体."""
        conn = self._engine.conn
        if conn is None:
            return []
        rows = conn.execute(
            "SELECT * FROM entity_memory WHERE entity_type = ? LIMIT ?",
            (entity_type, limit),
        ).fetchall()
        return [
            EntityMemoryEntry(
                entity_type=r["entity_type"],
                entity_key=r["entity_key"],
                attributes=json.loads(r["attributes"]),
                history=json.loads(r["history"]),
                created_at=r["created_at"],
                last_updated_at=r["last_updated_at"],
                last_source_session=r["last_source_session"] or "",
                ttl=r["ttl"],
            )
            for r in rows
        ]
