"""
Context Hook 包。

提供上下文管理相关的 Runtime Hook 实现：
- ContextAssemblerHook: before_llm Transform，执行五阶段上下文编排
"""

from src.context.context_hooks._assembler_hook import ContextAssemblerHook

__all__ = [
    "ContextAssemblerHook",
]
