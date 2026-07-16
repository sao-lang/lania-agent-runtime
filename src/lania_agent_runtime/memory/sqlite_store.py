"""SQLite implementation of memory stores."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from lania_agent_runtime.memory.base import (
    BehavioralStore,
    EntityStore,
    EpisodicStore,
    MemoryStore,
    SemanticStore,
)
from lania_agent_runtime.models import (
    BehavioralPattern,
    EntityMemoryEntry,
    EpisodicMemoryEntry,
    SemanticEdge,
    SemanticNode,
    WorkingMemorySnapshot,
)


class SQLiteMemoryStore(MemoryStore, EpisodicStore, EntityStore, SemanticStore, BehavioralStore):
    """SQLite implementation covering all memory layers."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        """Initialize database and create tables."""
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()

    async def _create_tables(self) -> None:
        """Create all memory tables."""
        if not self._conn:
            return

        self._conn.executescript("""
            -- Layer 1: Working Memory
            CREATE TABLE IF NOT EXISTS working_memory (
                session_id      TEXT PRIMARY KEY,
                snapshot        TEXT NOT NULL,
                captured_at     TEXT NOT NULL,
                expires_at      TEXT NOT NULL,
                version         INTEGER NOT NULL DEFAULT 1
            );

            -- Layer 2: Episodic Memory
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

            CREATE INDEX IF NOT EXISTS idx_ep_session_turn
                ON episodic_memory(session_id, turn_index DESC);
            CREATE INDEX IF NOT EXISTS idx_ep_user_time
                ON episodic_memory(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_ep_entities
                ON episodic_memory(entities);
            CREATE INDEX IF NOT EXISTS idx_ep_unmerged
                ON episodic_memory(merged_to) WHERE merged_to IS NULL;

            -- Layer 3: Entity Memory
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

            -- Layer 4: Semantic Knowledge
            CREATE TABLE IF NOT EXISTS semantic_node (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL UNIQUE,
                type            TEXT NOT NULL DEFAULT 'concept',
                description     TEXT NOT NULL DEFAULT '',
                aliases         TEXT NOT NULL DEFAULT '[]',
                mention_count   INTEGER NOT NULL DEFAULT 0,
                first_seen_at   TEXT NOT NULL,
                last_seen_at    TEXT NOT NULL,
                source          TEXT NOT NULL DEFAULT 'extracted_from_dialogue',
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS semantic_edge (
                id              TEXT PRIMARY KEY,
                source_node     TEXT NOT NULL REFERENCES semantic_node(id),
                target_node     TEXT NOT NULL REFERENCES semantic_node(id),
                relation        TEXT NOT NULL,
                confidence      REAL NOT NULL DEFAULT 1.0,
                source          TEXT NOT NULL DEFAULT 'extracted',
                created_at      TEXT NOT NULL,
                last_confirmed_at TEXT,
                UNIQUE(source_node, target_node, relation)
            );

            -- Layer 5: Behavioral Pattern
            CREATE TABLE IF NOT EXISTS behavioral_pattern (
                user_id             TEXT PRIMARY KEY,
                patterns            TEXT NOT NULL,
                total_interactions  INTEGER NOT NULL DEFAULT 0,
                version             INTEGER NOT NULL DEFAULT 1,
                last_converged_at   TEXT,
                last_interaction_at TEXT,
                created_at          TEXT NOT NULL
            );
        """)
        self._conn.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Working Memory ──

    async def save_working_memory(self, snapshot: WorkingMemorySnapshot) -> None:
        """Save a working memory checkpoint (overwrite)."""
        if not self._conn:
            return
        expires_at = (datetime.now() + timedelta(seconds=snapshot.ttl)).isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO working_memory
               (session_id, snapshot, captured_at, expires_at, version)
               VALUES (?, ?, ?, ?, ?)""",
            (
                snapshot.session_id,
                json.dumps(
                    {
                        "step_index": snapshot.step_index,
                        "messages": snapshot.messages,
                        "message_count": snapshot.message_count,
                        "total_tokens": snapshot.total_tokens,
                        "status": snapshot.status,
                    }
                ),
                snapshot.captured_at,
                expires_at,
                snapshot.version,
            ),
        )
        self._conn.commit()

    async def load_working_memory(
        self,
        session_id: str,
    ) -> WorkingMemorySnapshot | None:
        """Load a working memory checkpoint."""
        if not self._conn:
            return None
        row = self._conn.execute(
            "SELECT * FROM working_memory WHERE session_id = ? AND expires_at > datetime('now')",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["snapshot"])
        return WorkingMemorySnapshot(
            session_id=row["session_id"],
            step_index=data.get("step_index", 0),
            messages=data.get("messages", []),
            message_count=data.get("message_count", 0),
            total_tokens=data.get("total_tokens", 0),
            status=data.get("status", "running"),
            captured_at=row["captured_at"],
            version=row["version"],
        )

    async def delete_working_memory(self, session_id: str) -> None:
        """Delete a working memory checkpoint."""
        if not self._conn:
            return
        self._conn.execute(
            "DELETE FROM working_memory WHERE session_id = ?",
            (session_id,),
        )
        self._conn.commit()

    # ── Episodic Memory ──

    async def write(self, entry: EpisodicMemoryEntry) -> str:
        """Write an episodic memory entry."""
        if not self._conn:
            return entry.id
        self._conn.execute(
            """INSERT INTO episodic_memory
               (id, session_id, user_id, turn_index, created_at, summary,
                raw_content, content_type, source, entities, topics,
                keywords, importance, token_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.session_id,
                entry.user_id,
                entry.turn_index,
                entry.created_at,
                entry.summary,
                entry.raw_content,
                entry.content_type,
                json.dumps(entry.source) if entry.source else None,
                json.dumps(entry.entities) if entry.entities else None,
                json.dumps(entry.topics) if entry.topics else None,
                json.dumps(entry.keywords) if entry.keywords else None,
                entry.importance,
                entry.token_count,
            ),
        )
        self._conn.commit()
        return entry.id

    async def recall_session(
        self, session_id: str, *, limit: int = 20, offset: int = 0
    ) -> list[EpisodicMemoryEntry]:
        """Recall memories for a session."""
        if not self._conn:
            return []
        rows = self._conn.execute(
            """SELECT * FROM episodic_memory
               WHERE session_id = ?
               ORDER BY turn_index DESC
               LIMIT ? OFFSET ?""",
            (session_id, limit, offset),
        ).fetchall()
        return [self._row_to_episodic(r) for r in rows]

    async def recall_user(
        self, user_id: str, *, limit: int = 20, offset: int = 0
    ) -> list[EpisodicMemoryEntry]:
        """Recall memories across sessions for a user."""
        if not self._conn:
            return []
        rows = self._conn.execute(
            """SELECT * FROM episodic_memory
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        ).fetchall()
        return [self._row_to_episodic(r) for r in rows]

    async def search_by_entities(
        self, user_id: str, entities: list[str], *, limit: int = 10
    ) -> list[EpisodicMemoryEntry]:
        """Search memories by entity tags."""
        if not self._conn or not entities:
            return []
        # Simple LIKE-based search for entities
        rows = []
        for entity in entities:
            r = self._conn.execute(
                """SELECT * FROM episodic_memory
                   WHERE user_id = ? AND entities LIKE ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (user_id, f"%{entity}%", limit),
            ).fetchall()
            rows.extend(r)
        # Deduplicate by id
        seen = set()
        unique = []
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique.append(r)
        return [self._row_to_episodic(r) for r in unique[:limit]]

    async def count_session(self, session_id: str) -> int:
        """Count entries in a session."""
        if not self._conn:
            return 0
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM episodic_memory WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ── Entity Memory ──

    async def upsert_entity_attribute(
        self,
        entity_type: str,
        entity_key: str,
        attr_name: str,
        value: Any,  # noqa: ANN401
        *,
        confidence: float = 1.0,
        source_session: str = "",
    ) -> None:
        """Upsert an entity attribute."""
        if not self._conn:
            return
        now = datetime.now().isoformat()
        row = self._conn.execute(
            "SELECT * FROM entity_memory WHERE entity_type = ? AND entity_key = ?",
            (entity_type, entity_key),
        ).fetchone()

        if row:
            attributes = json.loads(row["attributes"])
            history = json.loads(row["history"])
        else:
            attributes = {}
            history = {}

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
        # Keep last 20 entries
        history[attr_name] = history[attr_name][-20:]

        created_at_val = row["created_at"] if row else now
        self._conn.execute(
            """INSERT OR REPLACE INTO entity_memory
               (entity_type, entity_key, attributes, history,
                created_at, last_updated_at, last_source_session)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                entity_type,
                entity_key,
                json.dumps(attributes),
                json.dumps(history),
                created_at_val,
                now,
                source_session,
            ),
        )
        self._conn.commit()

    # ── Semantic Knowledge ──

    async def create_semantic_node(
        self, name: str, node_type: str = "concept", description: str = ""
    ) -> str:
        """Create or get existing semantic node."""
        if not self._conn:
            return ""
        now = datetime.now().isoformat()
        existing = self._conn.execute(
            "SELECT id FROM semantic_node WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            return existing["id"]

        import uuid

        node_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO semantic_node
               (id, name, type, description, first_seen_at, last_seen_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (node_id, name, node_type, description, now, now, now),
        )
        self._conn.commit()
        return node_id

    # ── Behavioral Pattern ──

    async def upsert_behavioral_pattern(self, user_id: str, patterns: dict[str, Any]) -> None:
        """Upsert behavioral pattern for a user."""
        if not self._conn:
            return
        now = datetime.now().isoformat()
        existing = self._conn.execute(
            "SELECT * FROM behavioral_pattern WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if existing:
            version = existing["version"] + 1
            total = existing["total_interactions"] + 1
        else:
            version = 1
            total = 1

        created_at_val = existing["created_at"] if existing else now
        self._conn.execute(
            """INSERT OR REPLACE INTO behavioral_pattern
               (user_id, patterns, total_interactions, version,
                last_converged_at, last_interaction_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                json.dumps(patterns),
                total,
                version,
                now,
                now,
                created_at_val,
            ),
        )
        self._conn.commit()

    # ── Entity Memory (Layer 3) ──

    async def get_entity_profile(
        self, entity_type: str, entity_key: str
    ) -> EntityMemoryEntry | None:
        """Get the full profile for an entity."""
        if not self._conn:
            return None
        row = self._conn.execute(
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

    # ── Semantic Knowledge (Layer 4) ──

    async def search_semantic(
        self, query: str, *, type_filter: str | None = None, limit: int = 10
    ) -> list[SemanticNode]:
        """Search semantic nodes by name/description."""
        if not self._conn:
            return []
        like = f"%{query}%"
        if type_filter:
            rows = self._conn.execute(
                """SELECT * FROM semantic_node
                   WHERE (name LIKE ? OR description LIKE ?) AND type = ?
                   ORDER BY mention_count DESC, last_seen_at DESC
                   LIMIT ?""",
                (like, like, type_filter, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM semantic_node
                   WHERE name LIKE ? OR description LIKE ?
                   ORDER BY mention_count DESC, last_seen_at DESC
                   LIMIT ?""",
                (like, like, limit),
            ).fetchall()
        return [self._row_to_semantic_node(r) for r in rows]

    async def create_semantic_edge(
        self,
        source_node: str,
        target_node: str,
        relation: str,
        *,
        confidence: float = 1.0,
    ) -> str:
        """Create a semantic edge between two nodes."""
        if not self._conn:
            return ""
        import uuid

        now = datetime.now().isoformat()
        edge_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT OR IGNORE INTO semantic_edge
               (id, source_node, target_node, relation, confidence, created_at, last_confirmed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (edge_id, source_node, target_node, relation, confidence, now, now),
        )
        self._conn.commit()
        return edge_id

    async def get_semantic_edges(
        self, node_id: str, *, direction: str = "both", limit: int = 20
    ) -> list[SemanticEdge]:
        """Get edges connected to a node."""
        if not self._conn:
            return []
        if direction == "outgoing":
            rows = self._conn.execute(
                "SELECT * FROM semantic_edge WHERE source_node = ? LIMIT ?",
                (node_id, limit),
            ).fetchall()
        elif direction == "incoming":
            rows = self._conn.execute(
                "SELECT * FROM semantic_edge WHERE target_node = ? LIMIT ?",
                (node_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM semantic_edge
                   WHERE source_node = ? OR target_node = ?
                   LIMIT ?""",
                (node_id, node_id, limit),
            ).fetchall()
        return [self._row_to_semantic_edge(r) for r in rows]

    async def increment_semantic_mention(self, node_id: str) -> None:
        """Increment mention count for a semantic node."""
        if not self._conn:
            return
        now = datetime.now().isoformat()
        self._conn.execute(
            """UPDATE semantic_node
               SET mention_count = mention_count + 1, last_seen_at = ?
               WHERE id = ?""",
            (now, node_id),
        )
        self._conn.commit()

    # ── Behavioral Pattern (Layer 5) ──

    async def get_behavioral_pattern(self, user_id: str) -> BehavioralPattern | None:
        """Get behavioral pattern for a user."""
        if not self._conn:
            return None
        row = self._conn.execute(
            "SELECT * FROM behavioral_pattern WHERE user_id = ?",
            (user_id,),
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

    # ── Helpers ──

    def _row_to_episodic(self, row: sqlite3.Row) -> EpisodicMemoryEntry:
        """Convert a database row to an EpisodicMemoryEntry."""
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

    def _row_to_semantic_node(self, row: sqlite3.Row) -> SemanticNode:
        """Convert a database row to a SemanticNode."""
        return SemanticNode(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            description=row["description"],
            aliases=json.loads(row["aliases"]) if row["aliases"] else [],
            mention_count=row["mention_count"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            source=row["source"],
            created_at=row["created_at"],
        )

    def _row_to_semantic_edge(self, row: sqlite3.Row) -> SemanticEdge:
        """Convert a database row to a SemanticEdge."""
        return SemanticEdge(
            id=row["id"],
            source_node=row["source_node"],
            target_node=row["target_node"],
            relation=row["relation"],
            confidence=row["confidence"],
            source=row["source"],
            created_at=row["created_at"],
            last_confirmed_at=row["last_confirmed_at"],
        )
