"""
上下文管理模块。

提供 RuntimeContext（只读快照 + 受限写接口）、
ContextPayload（上下文操作对象 + 脏标记）和
MessageSerializer（序列化接口）。
"""

from src.runtime.context._context import RuntimeContext
from src.runtime.context._payload import ContextPayload
from src.runtime.context._serializer import (
    DefaultSerializer,
    MessageSerializer,
)

__all__ = [
    "RuntimeContext",
    "ContextPayload",
    "MessageSerializer",
    "DefaultSerializer",
]
