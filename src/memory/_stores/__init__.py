"""
内部存储适配器包。

5 个 Store 类将 MemoryPersistence 的键值操作转换为各层记忆的语义操作。
用户不需要直接使用这些类，MemoryService 在内部调用它们。
"""

from src.memory._stores._entity import EntityMemoryStore
from src.memory._stores._episodic import EpisodicMemoryStore
from src.memory._stores._pattern import BehavioralPatternStore
from src.memory._stores._semantic import SemanticKnowledgeStore
from src.memory._stores._working import WorkingMemoryStore

__all__ = [
    "WorkingMemoryStore",
    "EpisodicMemoryStore",
    "EntityMemoryStore",
    "SemanticKnowledgeStore",
    "BehavioralPatternStore",
]
