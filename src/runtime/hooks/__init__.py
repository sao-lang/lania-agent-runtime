"""
Hook 模块。

提供 HookRegistry（分层编排引擎）和原语类型（Observer/Transformer/Interceptor）。
以及编排相关 Hook 实现：
  - HumanApprovalInterceptor + 审批策略
  - SelfCritiqueHook / DualModelCritiqueHook
  - ReplanHook
"""

from src.runtime.hooks._approval_hook import (
    ApprovalPolicy,
    BudgetThresholdPolicy,
    CompoundPolicy,
    HumanApprovalInterceptor,
    RegexContentPolicy,
    ToolNamePolicy,
)
from src.runtime.hooks._critique_hook import (
    DualModelCritiqueHook,
    SelfCritiqueHook,
)
from src.runtime.hooks._primitives import (
    Interceptor,
    Observer,
    Transformer,
)
from src.runtime.hooks._registry import HandlerInfo, HookRegistry
from src.runtime.hooks._replan_hook import ReplanHook

__all__ = [
    # 原语类型
    "Observer",
    "Transformer",
    "Interceptor",
    # 注册中心
    "HookRegistry",
    "HandlerInfo",
    # 审批
    "HumanApprovalInterceptor",
    "ApprovalPolicy",
    "ToolNamePolicy",
    "BudgetThresholdPolicy",
    "RegexContentPolicy",
    "CompoundPolicy",
    # 批评
    "SelfCritiqueHook",
    "DualModelCritiqueHook",
    # 重新规划
    "ReplanHook",
]
