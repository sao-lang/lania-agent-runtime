"""向后兼容层: SQLiteStore → SQLiteStorageEngine.

v2.0 重构后, 各层 Store 不再继承 SQLiteStore.
SQLiteStore 现为 SQLiteStorageEngine 的别名, 保留用于向后兼容.
"""

from lania_agent_runtime.memory.stores.sqlite_engine import SQLiteStorageEngine as SQLiteStore

__all__ = ["SQLiteStore"]
