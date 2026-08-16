"""
会话组件 Hook 包。

提供 Runtime 生命周期中的会话 Hook：
- SessionStartHook: session_start Transform，加载/创建会话并恢复历史
- SessionResumeHook: session_resume Transform（Phase 2），恢复历史与游标
- SessionCommitHook: after_step Transform，逐轮提交完整消息历史
- SessionEndHook: session_end Transform，归档元数据与统计
"""

from src.session._hooks._commit import SessionCommitHook
from src.session._hooks._end import SessionEndHook
from src.session._hooks._resume import SessionResumeHook
from src.session._hooks._start import SessionStartHook

__all__ = [
    "SessionStartHook",
    "SessionResumeHook",
    "SessionCommitHook",
    "SessionEndHook",
]
