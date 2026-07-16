"""SQLite 存储引擎: 纯连接管理, 不含表 DDL.

职责:
  - 连接创建/关闭
  - PRAGMA 配置 (WAL, foreign_keys)
  - 行工厂设置

Store 实现通过组合持有 SQLiteStorageEngine, 而非继承.
每个 Store 自行管理自己的表 DDL.
"""

from __future__ import annotations

import sqlite3

from lania_agent_runtime.memory.stores.base import StorageEngine


class SQLiteStorageEngine(StorageEngine):
    """SQLite 连接管理引擎.

    可被多个 Store 共享 (共享同一连接/事务).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection | None:
        """获取当前连接. 未初始化或已关闭时返回 None."""
        return self._conn

    async def initialize(self) -> None:
        """初始化 SQLite 连接."""
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    async def close(self) -> None:
        """关闭 SQLite 连接."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def get_conn(self) -> sqlite3.Connection | None:
        """获取连接 (安全版本, 未初始化时返回 None)."""
        return self._conn

    def execute_ddl(self, ddl: str) -> None:
        """执行 DDL 语句 (供 Store 建表用)."""
        if self._conn is None:
            return
        self._conn.executescript(ddl)
        self._conn.commit()
