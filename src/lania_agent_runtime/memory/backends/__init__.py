"""存储后端适配层: 用户只需实现 StorageBackend, 上层 5 层记忆逻辑由 GenericMemoryStore 自动完成."""

from lania_agent_runtime.memory.backends.base import StorageBackend
from lania_agent_runtime.memory.backends.sqlite import SQLiteBackend

__all__ = [
    "StorageBackend",
    "SQLiteBackend",
]
