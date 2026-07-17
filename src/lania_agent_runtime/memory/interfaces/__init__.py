"""记忆系统存储接口层 - 5层记忆抽象定义."""

from __future__ import annotations

from abc import ABC

from lania_agent_runtime.memory.interfaces.working_memory import WorkingMemoryStore
from lania_agent_runtime.memory.interfaces.episodic_memory import EpisodicStore
from lania_agent_runtime.memory.interfaces.entity_memory import EntityStore
from lania_agent_runtime.memory.interfaces.semantic_knowledge import SemanticStore
from lania_agent_runtime.memory.interfaces.behavioral_pattern import BehavioralStore


class MemoryStore(
    WorkingMemoryStore,
    EpisodicStore,
    EntityStore,
    SemanticStore,
    BehavioralStore,
    ABC,
):
    """统一存储接口: 实现此接口即可接入全部 5 层记忆.

    用户实现自定义存储 (Redis / Postgres / MongoDB 等) 只需:

        class RedisStore(MemoryStore):
            ...  # 实现 5 层全部抽象方法

        service = MemoryService(store=RedisStore())

    SQLiteStore 是内置实现, 直接用即可:

        service = MemoryService(store=SQLiteStore("memory.db"))
    """


__all__ = [
    "WorkingMemoryStore",
    "EpisodicStore",
    "EntityStore",
    "SemanticStore",
    "BehavioralStore",
    "MemoryStore",
]
