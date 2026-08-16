"""
会话组件包。

职责：会话身份、生命周期与完整原始消息历史的持久化（唯一事实源）。
完整原始消息历史只归 Session（`ss:` 前缀），Memory 不再存原文，
Context 保持纯编排、不持有数据。

零耦合约束：
- src.session 不 import src.memory / src.context（运行期与 TYPE_CHECKING 均禁止）
- 对 src.runtime 仅在 TYPE_CHECKING 下引用（RuntimeContext / Event）
- 唯一接线点在 RuntimeBuilder

使用方式：
    from src.session import SessionConfig, SessionService

    service = SessionService(persistence, config=SessionConfig())
"""

from src.session._config import SessionConfig
from src.session._hooks import (
    SessionCommitHook,
    SessionEndHook,
    SessionResumeHook,
    SessionStartHook,
)
from src.session._models import SessionRecord, SessionSummary
from src.session._persistence import SessionPersistence
from src.session._protocols import SessionServiceProtocol
from src.session._service import SessionService
from src.session._store import SessionStore

__all__ = [
    # 服务与配置
    "SessionService",
    "SessionConfig",
    # 数据模型
    "SessionRecord",
    "SessionSummary",
    # 接口
    "SessionPersistence",
    "SessionServiceProtocol",
    "SessionStore",
    # Hooks
    "SessionStartHook",
    "SessionResumeHook",
    "SessionCommitHook",
    "SessionEndHook",
]
