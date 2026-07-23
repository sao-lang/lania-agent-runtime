"""
原语类型重导出模块。

将 _types 中定义的 Observer/Transformer/Interceptor Protocol 重导出
到 hooks 命名空间，方便用户从 hooks 模块导入。
"""

from src.runtime._types import Interceptor, Observer, Transformer

__all__ = [
    "Observer",
    "Transformer",
    "Interceptor",
]
