"""Layer 4: 语义知识 - SQLite 实现."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime

from lania_agent_runtime.memory.interfaces.semantic_knowledge import SemanticStore
from lania_agent_runtime.memory.stores.sqlite_engine import SQLiteStorageEngine
from lania_agent_runtime.models import SemanticEdge, SemanticNode


class SemanticKnowledgeSQLiteStore(SemanticStore):
    """语义知识 SQLite 实现 (Layer 4).

    通过组合持有 SQLiteStorageEngine, 而非继承.
    """

    _DDL = """
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
        CREATE INDEX IF NOT EXISTS idx_edge_source ON semantic_edge(source_node);
        CREATE INDEX IF NOT EXISTS idx_edge_target ON semantic_edge(target_node);
        CREATE INDEX IF NOT EXISTS idx_edge_relation ON semantic_edge(relation);
    """

    def __init__(self, engine: SQLiteStorageEngine) -> None:
        self._engine = engine

    async def initialize(self) -> None:
        """创建语义知识表 (幂等)."""
        self._engine.execute_ddl(self._DDL)

    @staticmethod
    def _row_to_semantic_node(row: sqlite3.Row) -> SemanticNode:
        """将 SQLite 行转换为 SemanticNode."""
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

    # ── 节点操作 ──

    async def create_semantic_node(
        self, name: str, node_type: str = "concept", description: str = ""
    ) -> str:
        """创建节点. 如果 name 已存在则返回已有 ID (幂等)."""
        conn = self._engine.conn
        if conn is None:
            return ""
        now = datetime.now().isoformat()
        existing = conn.execute(
            "SELECT id FROM semantic_node WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            return existing["id"]
        node_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO semantic_node
               (id, name, type, description, first_seen_at, last_seen_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (node_id, name, node_type, description, now, now, now),
        )
        conn.commit()
        return node_id

    async def read_node(self, node_id: str) -> SemanticNode | None:
        """按 ID 读取节点."""
        conn = self._engine.conn
        if conn is None:
            return None
        row = conn.execute(
            "SELECT * FROM semantic_node WHERE id = ?", (node_id,)
        ).fetchone()
        return self._row_to_semantic_node(row) if row else None

    async def find_node_by_name(self, name: str) -> SemanticNode | None:
        """按名称精确查找节点."""
        conn = self._engine.conn
        if conn is None:
            return None
        row = conn.execute(
            "SELECT * FROM semantic_node WHERE name = ?", (name,)
        ).fetchone()
        return self._row_to_semantic_node(row) if row else None

    async def search_semantic(
        self, query: str, *, type_filter: str | None = None, limit: int = 10
    ) -> list[SemanticNode]:
        """按名称/描述模糊搜索节点."""
        conn = self._engine.conn
        if conn is None:
            return []
        like = f"%{query}%"
        if type_filter:
            rows = conn.execute(
                """SELECT * FROM semantic_node
                   WHERE (name LIKE ? OR description LIKE ?) AND type = ?
                   ORDER BY mention_count DESC, last_seen_at DESC LIMIT ?""",
                (like, like, type_filter, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM semantic_node
                   WHERE name LIKE ? OR description LIKE ?
                   ORDER BY mention_count DESC, last_seen_at DESC LIMIT ?""",
                (like, like, limit),
            ).fetchall()
        return [self._row_to_semantic_node(r) for r in rows]

    # ── 边操作 ──

    async def create_semantic_edge(
        self, source_node: str, target_node: str, relation: str,
        *, confidence: float = 1.0,
    ) -> str:
        """创建边. 相同(source, target, relation)视为重复, 返回已有 ID."""
        conn = self._engine.conn
        if conn is None:
            return ""
        now = datetime.now().isoformat()
        existing = conn.execute(
            """SELECT id FROM semantic_edge
               WHERE source_node = ? AND target_node = ? AND relation = ?""",
            (source_node, target_node, relation),
        ).fetchone()
        if existing:
            return existing["id"]
        edge_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO semantic_edge
               (id, source_node, target_node, relation, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (edge_id, source_node, target_node, relation, confidence, now),
        )
        conn.commit()
        return edge_id

    async def get_semantic_edges(
        self, node_id: str, *, direction: str = "both", limit: int = 20
    ) -> list[SemanticEdge]:
        """获取连接到某节点的边."""
        conn = self._engine.conn
        if conn is None:
            return []
        if direction == "out":
            rows = conn.execute(
                """SELECT * FROM semantic_edge WHERE source_node = ? LIMIT ?""",
                (node_id, limit),
            ).fetchall()
        elif direction == "in":
            rows = conn.execute(
                """SELECT * FROM semantic_edge WHERE target_node = ? LIMIT ?""",
                (node_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM semantic_edge
                   WHERE source_node = ? OR target_node = ? LIMIT ?""",
                (node_id, node_id, limit),
            ).fetchall()
        return [
            SemanticEdge(
                id=r["id"], source_node=r["source_node"],
                target_node=r["target_node"], relation=r["relation"],
                confidence=r["confidence"], source=r["source"],
                created_at=r["created_at"],
                last_confirmed_at=r["last_confirmed_at"],
            )
            for r in rows
        ]

    async def get_neighbors(
        self, node_id: str, *, relation: str | None = None,
        max_depth: int = 1, limit: int = 20,
    ) -> list[tuple[SemanticNode, str]]:
        """获取邻居节点."""
        conn = self._engine.conn
        if conn is None:
            return []
        if max_depth == 1:
            if relation:
                rows = conn.execute(
                    """SELECT n.*, e.relation FROM semantic_node n
                       JOIN semantic_edge e ON e.target_node = n.id OR e.source_node = n.id
                       WHERE (e.source_node = ? OR e.target_node = ?) AND n.id != ?
                         AND e.relation = ? LIMIT ?""",
                    (node_id, node_id, node_id, relation, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT n.*, e.relation FROM semantic_node n
                       JOIN semantic_edge e ON e.target_node = n.id OR e.source_node = n.id
                       WHERE (e.source_node = ? OR e.target_node = ?) AND n.id != ?
                       LIMIT ?""",
                    (node_id, node_id, node_id, limit),
                ).fetchall()
        else:
            if relation:
                rows = conn.execute(
                    """WITH RECURSIVE path AS (
                        SELECT source_node, target_node, e.relation, 1 AS depth
                        FROM semantic_edge e WHERE e.source_node = ? AND e.relation = ?
                        UNION ALL
                        SELECT e.source_node, e.target_node, e.relation, p.depth + 1
                        FROM semantic_edge e JOIN path p ON e.source_node = p.target_node
                        WHERE p.depth < ?
                    ) SELECT n.*, p.relation FROM semantic_node n
                      JOIN path p ON n.id = p.target_node LIMIT ?""",
                    (node_id, relation, max_depth, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """WITH RECURSIVE path AS (
                        SELECT source_node, target_node, e.relation, 1 AS depth
                        FROM semantic_edge e WHERE e.source_node = ?
                        UNION ALL
                        SELECT e.source_node, e.target_node, e.relation, p.depth + 1
                        FROM semantic_edge e JOIN path p ON e.source_node = p.target_node
                        WHERE p.depth < ?
                    ) SELECT n.*, p.relation FROM semantic_node n
                      JOIN path p ON n.id = p.target_node LIMIT ?""",
                    (node_id, max_depth, limit),
                ).fetchall()
        results: list[tuple[SemanticNode, str]] = []
        for row in rows:
            node = self._row_to_semantic_node(row)
            results.append((node, row["relation"]))
        return results

    async def find_path(
        self, source_id: str, target_id: str, *, max_depth: int = 5,
    ) -> list[list[tuple[str, str]]]:
        """查找两节点之间的路径."""
        conn = self._engine.conn
        if conn is None:
            return []
        rows = conn.execute(
            """WITH RECURSIVE search_path AS (
                SELECT e.source_node, e.target_node, e.relation,
                       json_array(e.source_node) || ',' || e.target_node AS path_nodes,
                       json_array(e.relation) AS path_relations, 1 AS depth
                FROM semantic_edge e WHERE e.source_node = ?
                UNION ALL
                SELECT e.source_node, e.target_node, e.relation,
                       sp.path_nodes || ',' || e.target_node,
                       sp.path_relations || ',' || e.relation, sp.depth + 1
                FROM semantic_edge e JOIN search_path sp ON e.source_node = sp.target_node
                WHERE sp.depth < ? AND instr(sp.path_nodes, e.target_node) = 0
            ) SELECT sp.path_nodes, sp.path_relations FROM search_path sp
              WHERE sp.target_node = ? LIMIT 10""",
            (source_id, max_depth, target_id),
        ).fetchall()
        paths: list[list[tuple[str, str]]] = []
        for row in rows:
            nodes = str(row["path_nodes"]).split(",")
            rels = str(row["path_relations"]).split(",")
            paths.append(list(zip(nodes, rels)))
        return paths

    # ── 批量操作 ──

    async def merge_knowledge(
        self, extractions: list[tuple[str, str, str]],
        *, source: str = "extracted_from_dialogue",
    ) -> None:
        """批量注入知识三元组."""
        for source_name, relation, target_name in extractions:
            source_id = await self.create_semantic_node(source_name, "concept")
            target_id = await self.create_semantic_node(target_name, "concept")
            if source_id and target_id:
                await self.create_semantic_edge(source_id, target_id, relation)

    async def increment_mention(self, node_id: str) -> None:
        """增加节点提及计数."""
        conn = self._engine.conn
        if conn is None:
            return
        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE semantic_node
               SET mention_count = mention_count + 1, last_seen_at = ?
               WHERE id = ?""",
            (now, node_id),
        )
        conn.commit()

    async def get_low_mention_nodes(
        self, threshold: int = 3, *, limit: int = 50
    ) -> list[SemanticNode]:
        """获取提及次数低于阈值的节点(冷数据)."""
        conn = self._engine.conn
        if conn is None:
            return []
        rows = conn.execute(
            """SELECT * FROM semantic_node
               WHERE mention_count < ? ORDER BY last_seen_at ASC LIMIT ?""",
            (threshold, limit),
        ).fetchall()
        return [self._row_to_semantic_node(r) for r in rows]

    async def delete_node(self, node_id: str) -> None:
        """删除节点及其所有边."""
        conn = self._engine.conn
        if conn is None:
            return
        conn.execute(
            "DELETE FROM semantic_edge WHERE source_node = ? OR target_node = ?",
            (node_id, node_id),
        )
        conn.execute("DELETE FROM semantic_node WHERE id = ?", (node_id,))
        conn.commit()
