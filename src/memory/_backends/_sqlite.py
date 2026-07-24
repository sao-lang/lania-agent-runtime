"""
SQLite 持久化后端实现——SQLitePersistence。

基于 aiosqlite 的单表 key-value 存储，支持：
- 按前缀扫描（LIKE 查询）
- TTL 自动过期（expires_at 列）
- 自动建表

建表 DDL：
    CREATE TABLE IF NOT EXISTS memory_store (
        key         TEXT PRIMARY KEY,
        value       BLOB NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at  TEXT
    );
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from src.memory._persistence import MemoryPersistence


class SQLitePersistence(MemoryPersistence):
    """
    SQLite 持久化后端——MemoryPersistence 的默认实现。

    使用单一 memory.db 文件 + memory_store 表，
    通过 key-value 模式存储全部 5 层记忆。

    特性：
    - 自动建表（首次使用时）
    - 支持 TTL 过期
    - 按前缀扫描

    使用方式：
        persistence = SQLitePersistence("./memory.db")
        memory = MemoryService(persistence=persistence)
    """

    def __init__(
        self,
        db_path: str = "./memory.db",
        *,
        default_ttl_seconds: int | None = None,
    ) -> None:
        """
        初始化 SQLite 持久化后端。

        Args:
            db_path: SQLite 数据库文件路径，默认为 "./memory.db"。
            default_ttl_seconds: 默认过期秒数。None 表示永不过期。
        """
        self._db_path = db_path if db_path == ":memory:" else str(Path(db_path).resolve())
        self._default_ttl = default_ttl_seconds
        self._conn: aiosqlite.Connection | None = None

    async def _ensure_connection(self) -> aiosqlite.Connection:
        """获取或创建数据库连接，确保表已存在。"""
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._ensure_table()
        return self._conn

    async def _ensure_table(self) -> None:
        """创建 memory_store 表（如果不存在）。"""
        conn = self._conn
        if conn is None:
            return
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_store (
                key         TEXT PRIMARY KEY,
                value       BLOB NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                expires_at  TEXT
            )
        """)
        # 清理过期条目
        await conn.execute(
            "DELETE FROM memory_store "
            "WHERE expires_at IS NOT NULL AND expires_at <= datetime('now')"
        )
        await conn.commit()

    def _compute_expires_at(self) -> str | None:
        """根据配置计算 SQLite 兼容的过期时间字符串。

        格式为 YYYY-MM-DD HH:MM:SS，与 SQLite 的 datetime('now') 输出格式一致。
        """
        if self._default_ttl is None:
            return None
        expires = datetime.now(timezone.utc) + timedelta(seconds=self._default_ttl)
        # SQLite datetime 格式：YYYY-MM-DD HH:MM:SS
        return expires.strftime("%Y-%m-%d %H:%M:%S")

    # ── MemoryPersistence 接口实现 ──

    async def get(self, key: str) -> bytes | None:
        """
        读取原始字节数据。

        Args:
            key: 存储键名。

        Returns:
            字节数据，如果键不存在或已过期则返回 None。
        """
        conn = await self._ensure_connection()
        cursor = await conn.execute(
            "SELECT value FROM memory_store WHERE key = ? "
            "AND (expires_at IS NULL OR expires_at > datetime('now'))",
            (key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return row["value"] if isinstance(row["value"], bytes) else row["value"].encode()

    async def put(self, key: str, value: bytes) -> None:
        """
        写入原始字节数据（覆盖写）。

        Args:
            key: 存储键名。
            value: 要写入的字节数据。
        """
        conn = await self._ensure_connection()
        expires_at = self._compute_expires_at()
        await conn.execute(
            "INSERT OR REPLACE INTO memory_store (key, value, created_at, expires_at) "
            "VALUES (?, ?, datetime('now'), ?)",
            (key, value, expires_at),
        )
        await conn.commit()

    async def delete(self, key: str) -> None:
        """
        删除单个键。

        Args:
            key: 要删除的存储键名。
        """
        conn = await self._ensure_connection()
        await conn.execute("DELETE FROM memory_store WHERE key = ?", (key,))
        await conn.commit()

    async def list_keys(self, prefix: str) -> list[str]:
        """
        按前缀列出所有匹配的键。

        Args:
            prefix: 键名前缀。

        Returns:
            匹配前缀的所有未过期键名列表。
        """
        conn = await self._ensure_connection()
        cursor = await conn.execute(
            "SELECT key FROM memory_store WHERE key LIKE ? "
            "AND (expires_at IS NULL OR expires_at > datetime('now')) "
            "ORDER BY key",
            (f"{prefix}%",),
        )
        rows = await cursor.fetchall()
        return [row["key"] for row in rows]

    async def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
