"""向后兼容层: 重导出 stores/ 目录下的 SQLite 实现.

迁移说明:
  - SQLiteStore       → memory.stores.base_sqlite
  - EpisodicMemorySQLiteStore  → memory.stores.episodic_sqlite
  - EntityMemorySQLiteStore    → memory.stores.entity_sqlite
  - SemanticKnowledgeSQLiteStore → memory.stores.semantic_sqlite
  - BehavioralPatternSQLiteStore → memory.stores.pattern_sqlite
"""

from lania_agent_runtime.memory.stores import (
    BehavioralPatternSQLiteStore,
    CombinedSQLiteMemoryStore,
    EntityMemorySQLiteStore,
    EpisodicMemorySQLiteStore,
    SemanticKnowledgeSQLiteStore,
    SQLiteStore,
)

# 向后兼容: SQLiteMemoryStore 指向组合类(全5层)
SQLiteMemoryStore = CombinedSQLiteMemoryStore

__all__ = [
    "SQLiteStore",
    "SQLiteMemoryStore",
    "EpisodicMemorySQLiteStore",
    "EntityMemorySQLiteStore",
    "SemanticKnowledgeSQLiteStore",
    "BehavioralPatternSQLiteStore",
]
