"""
记忆系统包。

提供五层记忆的统一管理能力：
- Layer 1: Working Memory（工作记忆）
- Layer 2: Episodic Memory（情景记忆）
- Layer 3: Entity Memory（实体记忆）
- Layer 4: Semantic Knowledge（语义知识）
- Layer 5: Behavioral Pattern（行为模式）

使用方式：
    from src.memory import MemoryService, MemoryPersistence

    # 使用默认 SQLite 后端
    memory = MemoryService()

    # 或注入自定义后端
    memory = MemoryService(persistence=MyCustomBackend())
"""

from typing import Any

from src.memory._persistence import MemoryPersistence

# MemoryService 通过 __getattr__ 惰性导入

__all__ = [
    # 接口
    "MemoryPersistence",
    "MemoryService",
    # 数据类（_types）
    "WorkingMemorySnapshot",
    "PauseState",
    "ErrorStateSnapshot",
    "BudgetSnapshot",
    "EpisodicMemoryEntry",
    "EntityMemoryEntry",
    "EntityAttributeValue",
    "SemanticNode",
    "SemanticEdge",
    "BehavioralPattern",
    "StepContext",
    "GateDecision",
    "RecallResult",
    "MemorySource",
    "ToolCallRecord",
]


def __getattr__(name: str) -> Any:
    """惰性导入，避免启动时循环依赖。"""
    import importlib

    if name in __all__:
        if name == "MemoryService":
            mod = importlib.import_module("src.memory._service")
        else:
            mod = importlib.import_module("src.memory._types")
        return getattr(mod, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
