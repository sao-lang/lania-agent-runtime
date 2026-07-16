"""向后兼容层: 重导出新结构的所有内容.

设计文档要求的结构位于:
  - interfaces/   — 5层存储接口
  - stores/       — 存储引擎实现
  - pipeline/     — 读取/写入/裁剪管线
  - hooks/        — 治理 Hook
  - service.py    — MemoryService 统一门面
  - management/   — 管理组件 (gate/compression/eviction/conflict)
"""

from lania_agent_runtime.memory.interfaces import (
    BehavioralStore,
    EntityStore,
    EpisodicStore,
    SemanticStore,
    WorkingMemoryStore,
)
from lania_agent_runtime.memory.service import MemoryService
from lania_agent_runtime.memory.stores import (
    BehavioralPatternSQLiteStore,
    EntityMemorySQLiteStore,
    EpisodicMemorySQLiteStore,
    SemanticKnowledgeSQLiteStore,
    SQLiteStore,
    SQLiteMemoryStore,
    WorkingMemoryFileStore,
)

# 向后兼容: 旧名称 (SQLiteMemoryStore 已在 stores 中指向 CombinedSQLiteMemoryStore)
MemoryStore = SQLiteStore

__all__ = [
    "WorkingMemoryStore",
    "EpisodicStore",
    "EntityStore",
    "SemanticStore",
    "BehavioralStore",
    "MemoryStore",
    "MemoryService",
    "SQLiteStore",
    "SQLiteMemoryStore",
    "WorkingMemoryFileStore",
    "EpisodicMemorySQLiteStore",
    "EntityMemorySQLiteStore",
    "SemanticKnowledgeSQLiteStore",
    "BehavioralPatternSQLiteStore",
]
