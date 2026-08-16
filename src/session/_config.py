"""
会话组件配置定义。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SessionConfig:
    """会话组件配置。

    Attributes:
        enabled: 总开关。
        persist_messages: 是否持久化完整消息历史（续聊/恢复依赖此开关）。
        max_history_messages: 历史消息上限（超出裁最旧）。
        max_message_chars: 单条消息截断长度。
        auto_title: 用首条用户消息生成标题。
        ttl_seconds: 0 = 永久；由 SessionService 内置过期检查。
        user_id_key: ctx.services 中取 user_id 的键名。
        chunk_size: 历史消息分块阈值（0 = 不启用；消息数超过阈值时以 ssh: 前缀分块存储）。
    """

    enabled: bool = True
    persist_messages: bool = True
    max_history_messages: int = 200
    max_message_chars: int = 16384
    auto_title: bool = True
    ttl_seconds: int = 0
    user_id_key: str = "user_id"
    chunk_size: int = 100
