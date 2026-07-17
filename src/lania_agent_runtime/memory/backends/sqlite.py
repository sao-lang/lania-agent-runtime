"""SQLite 存储后端: 实现 StorageBackend 全部原语."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from lania_agent_runtime.memory.backends.base import StorageBackend


class SQLiteBackend(StorageBackend):
    """SQLite 存储后端: 将 StorageBackend 原语映射为 SQL 操作.

    通过存储介质变化来证明: 用户只需实现 ~25 个原语, 即获得完整 5 层记忆.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ── 生命周期 ──

    async def initialize(self) -> None:
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()

    async def _create_tables(self) -> None:
        assert self._conn
        self._conn.executescript("""
            -- KV 存储 (working / entity / pattern)
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- 有序列表 (episodic)
            CREATE TABLE IF NOT EXISTS list_store (
                list_key TEXT NOT NULL,
                idx INTEGER NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (list_key, idx)
            );

            -- 集合索引 (episodic 标签 / entity 类型)
            CREATE TABLE IF NOT EXISTS set_store (
                set_key TEXT NOT NULL,
                member TEXT NOT NULL,
                PRIMARY KEY (set_key, member)
            );

            -- 图: 节点
            CREATE TABLE IF NOT EXISTS graph_node (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL DEFAULT 'concept',
                description TEXT DEFAULT '',
                mention_count INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- 图: 边
            CREATE TABLE IF NOT EXISTS graph_edge (
                id TEXT PRIMARY KEY,
                source_node TEXT NOT NULL REFERENCES graph_node(id) ON DELETE CASCADE,
                target_node TEXT NOT NULL REFERENCES graph_node(id) ON DELETE CASCADE,
                relation TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source_node, target_node, relation)
            );

            -- 锁
            CREATE TABLE IF NOT EXISTS lock_store (
                lock_id TEXT PRIMARY KEY,
                locked_at TEXT NOT NULL DEFAULT (datetime('now')),
                expires_at TEXT NOT NULL
            );

            -- 索引
            CREATE INDEX IF NOT EXISTS idx_list_key_created ON list_store(list_key, idx);
            CREATE INDEX IF NOT EXISTS idx_kv_expires ON kv_store(expires_at);
            CREATE INDEX IF NOT EXISTS idx_graph_edge_source ON graph_edge(source_node);
            CREATE INDEX IF NOT EXISTS idx_graph_edge_target ON graph_edge(target_node);
            CREATE INDEX IF NOT EXISTS idx_lock_expires ON lock_store(expires_at);
        """)
        self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _check_conn(self):
        """检查是否已初始化. 未初始化时返回 False, 调用方应返回对应空值."""
        return self._conn is not None

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    # ── KV 操作 ──

    async def kv_set(self, key: str, value: str, ttl: int | None = None) -> None:
        if not self._check_conn():
            return
        self._conn.execute(
            """INSERT OR REPLACE INTO kv_store (key, value, expires_at, created_at)
               VALUES (?, ?, datetime('now', ?), datetime('now'))""",
            (key, value, f"+{ttl} seconds" if ttl else None),
        )
        self._conn.commit()

    async def kv_get(self, key: str) -> str | None:
        if not self._check_conn():
            return
        cur = self._conn.execute(
            """SELECT value FROM kv_store
               WHERE key = ? AND (expires_at IS NULL OR expires_at > datetime('now'))""",
            (key,),
        )
        row = cur.fetchone()
        return row["value"] if row else None

    async def kv_delete(self, key: str) -> None:
        if not self._check_conn():
            return
        self._conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
        self._conn.commit()

    async def kv_exists(self, key: str) -> bool:
        if not self._check_conn():
            return False
        cur = self._conn.execute(
            """SELECT 1 FROM kv_store
               WHERE key = ? AND (expires_at IS NULL OR expires_at > datetime('now'))""",
            (key,),
        )
        return cur.fetchone() is not None

    # ── 列表操作 ──

    async def list_push(self, key: str, value: str) -> None:
        if not self._check_conn():
            return
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(idx), -1) + 1 AS next_idx FROM list_store WHERE list_key = ?",
            (key,),
        )
        next_idx = cur.fetchone()["next_idx"]
        self._conn.execute(
            "INSERT INTO list_store (list_key, idx, value) VALUES (?, ?, ?)",
            (key, next_idx, value),
        )
        self._conn.commit()

    async def list_range(self, key: str, start: int, stop: int) -> list[str]:
        if not self._check_conn():
            return []
        if stop == -1:
            cur = self._conn.execute(
                "SELECT value FROM list_store WHERE list_key = ? ORDER BY idx ASC",
                (key,),
            )
        else:
            cur = self._conn.execute(
                "SELECT value FROM list_store WHERE list_key = ? ORDER BY idx ASC LIMIT ? OFFSET ?",
                (key, stop - start + 1, start),
            )
        return [row["value"] for row in cur.fetchall()]

    async def list_len(self, key: str) -> int:
        if not self._check_conn():
            return 0
        cur = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM list_store WHERE list_key = ?", (key,)
        )
        return cur.fetchone()["cnt"]

    async def list_remove(self, key: str, value: str, count: int = 0) -> None:
        if not self._check_conn():
            return
        if count == 0:
            self._conn.execute(
                "DELETE FROM list_store WHERE list_key = ? AND value = ?",
                (key, value),
            )
        else:
            self._conn.execute(
                """DELETE FROM list_store WHERE rowid IN (
                    SELECT rowid FROM list_store
                    WHERE list_key = ? AND value = ?
                    LIMIT ?
                )""",
                (key, value, count),
            )
        self._conn.commit()

    # ── 集合操作 ──

    async def set_add(self, key: str, *values: str) -> None:
        if not self._check_conn():
            return
        for v in values:
            self._conn.execute(
                "INSERT OR IGNORE INTO set_store (set_key, member) VALUES (?, ?)",
                (key, v),
            )
        self._conn.commit()

    async def set_members(self, key: str) -> set[str]:
        if not self._check_conn():
            return set()
        cur = self._conn.execute(
            "SELECT member FROM set_store WHERE set_key = ?", (key,)
        )
        return {row["member"] for row in cur.fetchall()}

    async def set_intersect(self, keys: list[str]) -> set[str]:
        if not self._check_conn() or not keys:
            return set()
        if len(keys) == 1:
            return await self.set_members(keys[0])

        # Python 端求交集, SQL 子查询在数据量大时替换
        members = None
        for k in keys:
            m = await self.set_members(k)
            if members is None:
                members = m
            else:
                members &= m
        return members

    # ── 图操作 ──

    async def graph_node_create(
        self,
        node_id: str,
        name: str,
        type: str = "concept",
        description: str = "",
    ) -> bool:
        if not self._check_conn():
            return False
        try:
            self._conn.execute(
                """INSERT INTO graph_node (id, name, type, description)
                   VALUES (?, ?, ?, ?)""",
                (node_id, name, type, description),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    async def graph_node_get(self, node_id: str) -> dict[str, Any] | None:
        if not self._check_conn():
            return None
        cur = self._conn.execute("SELECT * FROM graph_node WHERE id = ?", (node_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    async def graph_node_find_by_name(self, name: str) -> dict[str, Any] | None:
        if not self._check_conn():
            return None
        cur = self._conn.execute("SELECT * FROM graph_node WHERE name = ?", (name,))
        row = cur.fetchone()
        return dict(row) if row else None

    async def graph_node_search(
        self,
        query: str,
        type_filter: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if not self._check_conn():
            return []
        like = f"%{query}%"
        if type_filter:
            cur = self._conn.execute(
                """SELECT * FROM graph_node
                   WHERE (name LIKE ? OR description LIKE ?) AND type = ?
                   LIMIT ?""",
                (like, like, type_filter, limit),
            )
        else:
            cur = self._conn.execute(
                """SELECT * FROM graph_node
                   WHERE name LIKE ? OR description LIKE ?
                   LIMIT ?""",
                (like, like, limit),
            )
        return [dict(row) for row in cur.fetchall()]

    async def graph_node_increment_mention(self, node_id: str) -> None:
        if not self._check_conn():
            return
        self._conn.execute(
            """UPDATE graph_node SET mention_count = mention_count + 1,
               last_seen_at = datetime('now') WHERE id = ?""",
            (node_id,),
        )
        self._conn.commit()

    async def graph_node_get_low_mention(
        self, threshold: int = 3, limit: int = 50
    ) -> list[dict[str, Any]]:
        if not self._check_conn():
            return []
        cur = self._conn.execute(
            """SELECT * FROM graph_node
               WHERE mention_count < ?
               ORDER BY last_seen_at ASC
               LIMIT ?""",
            (threshold, limit),
        )
        return [dict(row) for row in cur.fetchall()]

    async def graph_node_delete(self, node_id: str) -> None:
        if not self._check_conn():
            return
        self._conn.execute("DELETE FROM graph_edge WHERE source_node = ?", (node_id,))
        self._conn.execute("DELETE FROM graph_edge WHERE target_node = ?", (node_id,))
        self._conn.execute("DELETE FROM graph_node WHERE id = ?", (node_id,))
        self._conn.commit()

    async def graph_edge_create(
        self,
        source_node: str,
        target_node: str,
        relation: str,
        confidence: float = 1.0,
    ) -> bool:
        if not self._check_conn():
            return False
        try:
            self._conn.execute(
                """INSERT INTO graph_edge (id, source_node, target_node, relation, confidence)
                   VALUES (?, ?, ?, ?, ?)""",
                (uuid.uuid4().hex, source_node, target_node, relation, confidence),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    async def graph_edge_list(
        self,
        node_id: str,
        direction: str = "both",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not self._check_conn():
            return []
        if direction == "out":
            cur = self._conn.execute(
                """SELECT * FROM graph_edge WHERE source_node = ? LIMIT ?""",
                (node_id, limit),
            )
        elif direction == "in":
            cur = self._conn.execute(
                """SELECT * FROM graph_edge WHERE target_node = ? LIMIT ?""",
                (node_id, limit),
            )
        else:
            cur = self._conn.execute(
                """SELECT * FROM graph_edge WHERE source_node = ? OR target_node = ?
                   LIMIT ?""",
                (node_id, node_id, limit),
            )
        return [dict(row) for row in cur.fetchall()]

    async def graph_neighbors(
        self,
        node_id: str,
        relation: str | None = None,
        max_depth: int = 1,
        limit: int = 20,
    ) -> list[tuple[dict[str, Any], str]]:
        if not self._check_conn():
            return []
        if max_depth > 1:
            # 递归查询
            rel_filter = f"AND e.relation = '{relation}'" if relation else ""
            query = f"""
                WITH RECURSIVE walk(nid, depth) AS (
                    SELECT ?, 0
                    UNION
                    SELECT
                        CASE WHEN e.source_node = w.nid THEN e.target_node ELSE e.source_node END,
                        w.depth + 1
                    FROM walk w
                    JOIN graph_edge e ON e.source_node = w.nid OR e.target_node = w.nid
                    WHERE w.depth < ?
                    {rel_filter}
                )
                SELECT DISTINCT n.*, 'related' AS rel FROM walk w
                JOIN graph_node n ON n.id = w.nid
                WHERE w.nid != ?
                LIMIT ?
            """
            cur = self._conn.execute(query, (node_id, max_depth, node_id, limit))
        else:
            if relation:
                cur = self._conn.execute(
                    """SELECT n.*, e.relation AS rel FROM graph_edge e
                       JOIN graph_node n ON n.id = CASE WHEN e.source_node = ? THEN e.target_node ELSE e.source_node END
                       WHERE (e.source_node = ? OR e.target_node = ?) AND e.relation = ?
                       LIMIT ?""",
                    (node_id, node_id, node_id, relation, limit),
                )
            else:
                cur = self._conn.execute(
                    """SELECT n.*, e.relation AS rel FROM graph_edge e
                       JOIN graph_node n ON n.id = CASE WHEN e.source_node = ? THEN e.target_node ELSE e.source_node END
                       WHERE e.source_node = ? OR e.target_node = ?
                       LIMIT ?""",
                    (node_id, node_id, node_id, limit),
                )
        return [(dict(row), row["rel"]) for row in cur.fetchall()]

    async def graph_find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
    ) -> list[list[tuple[str, str]]]:
        if not self._check_conn():
            return []
        try:
            cur = self._conn.execute(
                """WITH RECURSIVE walk(node_id, path, relations, depth) AS (
                    SELECT ?, json_array(?), json_array('__start__'), 0
                    UNION ALL
                    SELECT
                        CASE WHEN e.source_node = w.node_id THEN e.target_node ELSE e.source_node END,
                        json_insert(w.path, '$[#]',
                            CASE WHEN e.source_node = w.node_id THEN e.target_node ELSE e.source_node END),
                        json_insert(w.relations, '$[#]', e.relation),
                        w.depth + 1
                    FROM walk w
                    JOIN graph_edge e ON e.source_node = w.node_id OR e.target_node = w.node_id
                    WHERE w.depth < ?
                      AND json_extract(w.path, '$[#-1]') !=
                          CASE WHEN e.source_node = w.node_id THEN e.target_node ELSE e.source_node END
                )
                SELECT path, relations FROM walk
                WHERE node_id = ? AND depth > 0
                ORDER BY depth ASC
                LIMIT 10""",
                (source_id, source_id, max_depth, target_id),
            )
            results = []
            for row in cur.fetchall():
                path_nodes = json.loads(row["path"])
                path_rels = json.loads(row["relations"])
                results.append(list(zip(path_nodes, path_rels[1:])))
            return results
        except Exception:
            return []

    # ── 锁操作 ──

    async def acquire_lock(self, lock_id: str, ttl: int = 30) -> bool:
        if not self._check_conn():
            return False
        # 清理过期锁
        self._conn.execute(
            "DELETE FROM lock_store WHERE expires_at <= datetime('now')",
        )
        try:
            self._conn.execute(
                """INSERT INTO lock_store (lock_id, expires_at)
                   VALUES (?, datetime('now', ?))""",
                (lock_id, f"+{ttl} seconds"),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
