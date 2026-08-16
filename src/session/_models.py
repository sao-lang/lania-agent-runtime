"""
会话组件数据类定义。

定义 SessionRecord（会话元数据 + 完整原始消息历史）与
SessionSummary（列表展示用的轻量摘要，不含 messages）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SessionRecord:
    """会话记录——会话元数据 + 完整原始消息历史（唯一事实源）。

    Attributes:
        session_id: 主键，与 Runtime.session_id 一致。
        agent_id: 所属 Agent。
        user_id: 关联用户。
        title: 会话标题。
        status: active | paused | ended | error | cancelled。
        created_at / updated_at / ended_at: 生命周期时间戳。
        turn_count / message_count / step_count / token_used: 统计。
        step_index: 已提交的 step 游标（续聊时用于 turn_index 对齐）。
        last_error: 最后错误信息。
        metadata: 外部扩展字段。
        messages: 完整对话消息历史（user/assistant/tool，不含 system；
            system prompt 属运行时配置，Session 不保存）。Session 独有，其它组件不存原文。
        version: 数据格式版本号。
        ttl: 过期秒数，0 = 永久。
    """

    session_id: str = ""
    agent_id: str = ""
    user_id: str | None = None
    title: str = ""
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    ended_at: datetime | None = None
    turn_count: int = 0
    message_count: int = 0
    step_count: int = 0
    step_index: int = 0
    token_used: int = 0
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)
    version: int = 1
    ttl: int = 0


@dataclass
class SessionSummary:
    """会话摘要——列表展示用，不含 messages。

    Attributes:
        session_id: 会话 ID。
        title: 会话标题。
        status: 会话状态。
        user_id: 关联用户。
        turn_count: 轮次数量。
        created_at / updated_at: 创建/更新时间。
    """

    session_id: str = ""
    title: str = ""
    status: str = ""
    user_id: str | None = None
    turn_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
