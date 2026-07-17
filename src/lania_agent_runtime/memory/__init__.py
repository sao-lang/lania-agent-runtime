"""记忆系统包: 存储接口 + StorageBackend 架构.

设计: memory-system-design.md
"""

from lania_agent_runtime.memory.interfaces import (
    BehavioralStore,
    EntityStore,
    EpisodicStore,
    MemoryStore,
    SemanticStore,
    WorkingMemoryStore,
)
from lania_agent_runtime.memory.service import MemoryService
from lania_agent_runtime.memory.backends import SQLiteBackend
from lania_agent_runtime.memory.generic_store import GenericMemoryStore
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
    "MemoryStore",
    # 存储实现
    "GenericMemoryStore",
    "SQLiteBackend",
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
