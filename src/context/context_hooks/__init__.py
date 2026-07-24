"""
Context Hook 实现包。

提供上下文管理相关的 Runtime Hook：
- ContextAssemblerHook: before_llm Transform，执行五阶段上下文编排
"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    """惰性导入，避免启动时循环依赖。"""
    import importlib

    if name == "ContextAssemblerHook":
        mod = importlib.import_module(
            "src.context.context_hooks._assembler_hook"
        )
        return getattr(mod, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)

