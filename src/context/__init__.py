"""
上下文管理包。

提供上下文编排的五阶段管线：SELECT → LOAD → COMPRESS → BUDGET → SERIALIZE。
ContextManager 是统一入口，被 ContextAssemblerHook 在 before_llm 时调用。

与 src.runtime.context 的区别：
- src.runtime.context：核心数据类型（RuntimeContext / ContextPayload / MessageSerializer）
- src.context：上下文编排管线（ContextManager / Selector / Compressor / BudgetController）
"""

from typing import Any

from src.context._config import ContextConfig
from src.context._models import (
    CompressResult,
    ConceptSummary,
    EntityProfileValue,
    RawContext,
    SelectionDecision,
)

__all__ = [
    "ContextConfig",
    "SelectionDecision",
    "RawContext",
    "ConceptSummary",
    "EntityProfileValue",
    "CompressResult",
]


def __getattr__(name: str) -> Any:
    """惰性导入，避免启动时循环依赖。"""
    import importlib

    extra = {
        "ContextManager",
        "Selector",
        "Compressor",
        "BudgetController",
        "TokenManager",
        "ContextAssemblerHook",
    }
    if name in extra:
        if name == "ContextAssemblerHook":
            mod = importlib.import_module("src.context.context_hooks")
            return getattr(mod, name)
        mod = importlib.import_module(f"src.context._{name.lower()}")
        return getattr(mod, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
