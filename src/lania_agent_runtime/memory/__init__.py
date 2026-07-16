"""记忆系统包: 5层记忆 + 4个管理组件 + 存储/管线/Hook.

设计文档结构: memory-system-design.md 附录
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
    CombinedSQLiteMemoryStore,
    EntityMemorySQLiteStore,
    EpisodicMemorySQLiteStore,
    SemanticKnowledgeSQLiteStore,
    SQLiteStore,
    SQLiteMemoryStore,
    WorkingMemoryFileStore,
    WorkingMemorySQLiteStore,
)
from lania_agent_runtime.memory.compression import CompressionManager
from lania_agent_runtime.memory.conflict import ConflictResolver
from lania_agent_runtime.memory.eviction import EvictionManager
from lania_agent_runtime.memory.gate import MemoryCommitGate
from lania_agent_runtime.memory.hooks import (
    MemoryCommitHook,
    MemoryRecallHook,
    SessionCleanupHook,
)
from lania_agent_runtime.memory.pipeline import (
    CommitPipeline,
    RecallPipeline,
    TokenManager,
)

__all__ = [
    # 存储接口
    "WorkingMemoryStore",
    "EpisodicStore",
    "EntityStore",
    "SemanticStore",
    "BehavioralStore",
    # 存储实现
    "SQLiteStore",
    "WorkingMemoryFileStore",
    "WorkingMemorySQLiteStore",
    "EpisodicMemorySQLiteStore",
    "EntityMemorySQLiteStore",
    "SemanticKnowledgeSQLiteStore",
    "BehavioralPatternSQLiteStore",
    "CombinedSQLiteMemoryStore",
    "SQLiteMemoryStore",
    # 门面服务
    "MemoryService",
    # 管线
    "TokenManager",
    "RecallPipeline",
    "CommitPipeline",
    # Hook
    "MemoryRecallHook",
    "MemoryCommitHook",
    "SessionCleanupHook",
    # 管理组件
    "MemoryCommitGate",
    "CompressionManager",
    "EvictionManager",
    "ConflictResolver",
]
