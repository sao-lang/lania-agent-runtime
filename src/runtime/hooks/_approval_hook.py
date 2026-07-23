"""
HumanInTheLoop 审批钩子模块。

对应设计文档 §3.2 HumanInTheLoop → 通过 Intercept pause 实现。

提供：
  - ApprovalPolicy: 审批策略基类及内置实现
  - HumanApprovalInterceptor: 注册到 before_tool 的 Interceptor
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.runtime._types import AllowAction, PauseAction


class ApprovalPolicy(ABC):
    """
    审批策略抽象基类。

    判断某个工具调用是否需要审批。
    返回 (needs_approval, reason) 元组。
    """

    @abstractmethod
    async def needs_approval(self, ctx: Any, tool_name: str, arguments: dict) -> tuple[bool, str]:
        """
        判断是否需要审批。

        Args:
            ctx: RuntimeContext 实例。
            tool_name: 工具名称。
            arguments: 工具调用参数。

        Returns:
            (是否需要审批, 审批原因描述) 元组。
        """
        ...


class ToolNamePolicy(ApprovalPolicy):
    """
    按工具名称匹配的审批策略。

    工具名在白名单中时触发审批。
    """

    def __init__(self, tool_names: list[str]) -> None:
        """
        初始化。

        Args:
            tool_names: 需要审批的工具名称列表。
        """
        self._tool_names = set(tool_names)

    async def needs_approval(self, ctx: Any, tool_name: str, arguments: dict) -> tuple[bool, str]:
        """
        判断是否需要审批。

        Args:
            ctx: RuntimeContext 实例。
            tool_name: 工具名称。
            arguments: 工具调用参数。

        Returns:
            (是否需要审批, 审批原因描述) 元组。
        """
        if tool_name in self._tool_names:
            return True, f"工具 '{tool_name}' 需要审批"
        return False, ""


class BudgetThresholdPolicy(ApprovalPolicy):
    """
    按 token/step 阈值触发的审批策略。

    当 token 消耗或 step 数量超过阈值时触发审批。
    """

    def __init__(
        self,
        token_threshold: int = 0,
        step_threshold: int = 0,
    ) -> None:
        """
        初始化。

        Args:
            token_threshold: Token 消耗上限，0 表示不限制。
            step_threshold: Step 数量上限，0 表示不限制。
        """
        self._token_threshold = token_threshold
        self._step_threshold = step_threshold

    async def needs_approval(self, ctx: Any, tool_name: str, arguments: dict) -> tuple[bool, str]:
        """
        判断是否需要审批。

        Args:
            ctx: RuntimeContext 实例。
            tool_name: 工具名称。
            arguments: 工具调用参数。

        Returns:
            (是否需要审批, 审批原因描述) 元组。
        """
        reasons: list[str] = []

        if self._token_threshold > 0 and ctx.budget.token_used >= self._token_threshold:
            reasons.append(f"Token 消耗 {ctx.budget.token_used} 超过阈值 {self._token_threshold}")

        if self._step_threshold > 0 and ctx.budget.step_count >= self._step_threshold:
            reasons.append(f"Step 数量 {ctx.budget.step_count} 超过阈值 {self._step_threshold}")

        if reasons:
            return True, "; ".join(reasons)
        return False, ""


class RegexContentPolicy(ApprovalPolicy):
    """
    按工具参数内容匹配的审批策略。

    参数中匹配到正则表达式时触发审批。
    """

    def __init__(self, patterns: list[str]) -> None:
        """
        初始化。

        Args:
            patterns: 正则表达式模式列表。
        """
        import re

        self._patterns = [re.compile(p) for p in patterns]

    async def needs_approval(self, ctx: Any, tool_name: str, arguments: dict) -> tuple[bool, str]:
        """
        判断是否需要审批。

        Args:
            ctx: RuntimeContext 实例。
            tool_name: 工具名称。
            arguments: 工具调用参数。

        Returns:
            (是否需要审批, 审批原因描述) 元组。
        """
        arg_str = str(arguments)
        for pattern in self._patterns:
            if pattern.search(arg_str):
                return True, f"参数匹配审批规则: {pattern.pattern}"
        return False, ""


class CompoundPolicy(ApprovalPolicy):
    """
    组合策略——默认 ANY（任一策略触发即审批）。

    可通过 strategy="all" 切换为 ALL（全部触发才审批）。
    """

    def __init__(self, policies: list[ApprovalPolicy], strategy: str = "any") -> None:
        """
        初始化。

        Args:
            policies: 策略列表。
            strategy: 组合策略——"any"（任一触发）或 "all"（全部触发）。
        """
        self._policies = policies
        if strategy not in ("any", "all"):
            raise ValueError(f"strategy 必须是 'any' 或 'all'，收到 '{strategy}'")
        self._strategy = strategy

    async def needs_approval(self, ctx: Any, tool_name: str, arguments: dict) -> tuple[bool, str]:
        """
        判断是否需要审批。

        Args:
            ctx: RuntimeContext 实例。
            tool_name: 工具名称。
            arguments: 工具调用参数。

        Returns:
            (是否需要审批, 审批原因描述) 元组。
        """
        results = [await p.needs_approval(ctx, tool_name, arguments) for p in self._policies]
        approvals = [(need, reason) for need, reason in results if need]

        if self._strategy == "all":
            if len(approvals) == len(self._policies):
                reasons = [r for _, r in approvals]
                return True, "; ".join(reasons)
        else:
            if approvals:
                return True, approvals[0][1]

        return False, ""


class HumanApprovalInterceptor:
    """
    Human-in-the-loop Interceptor。

    注册到 before_tool 挂载点，根据 ApprovalPolicy 判断是否需要审批。
    需要审批时返回 PauseAction 挂起执行。

    支持三种模式：
      - sync_blocking: 同步阻塞等待审批（默认）
      - async_deferred: 异步审批，不阻塞执行
      - notify_only: 仅通知，不要求审批

    从 pause 恢复后自动识别已审批通过的请求，避免审批死循环。
    """

    def __init__(
        self,
        policy: ApprovalPolicy,
        mode: str = "sync_blocking",
    ) -> None:
        """
        初始化。

        Args:
            policy: 审批策略实例。
            mode: 审批模式——"sync_blocking" | "async_deferred" | "notify_only"。
        """
        self._policy = policy
        self._mode = mode
        # 已审批通过的 ID 集合（用于 resume 防护）
        self._approved_ids: set[str] = set()

    async def __call__(self, data: Any, ctx: Any) -> AllowAction | PauseAction:
        """
        Interceptor 调用入口。

        判断是否需要审批，如果需要则返回 PauseAction。

        Args:
            data: 工具调用请求数据。
            ctx: RuntimeContext 实例。

        Returns:
            AllowAction 或 PauseAction。
        """
        # 提取工具名和参数
        if isinstance(data, dict):
            tool_name = data.get("tool_name", "")
            arguments = data.get("arguments", {})
            approval_id = data.get("approval_id", "")
        else:
            tool_name = str(data)
            arguments = {}
            approval_id = ""

        # 如果已经审批通过，直接放行
        if approval_id and approval_id in self._approved_ids:
            return AllowAction()

        # 判断是否需要审批
        needs_approval, reason = await self._policy.needs_approval(ctx, tool_name, arguments)

        if not needs_approval:
            return AllowAction()

        if self._mode == "notify_only":
            # 仅通知模式：写入审批记录但不暂停
            return AllowAction()

        # 需要审批——返回 PauseAction
        import uuid

        pause_id = approval_id or f"approval_{uuid.uuid4().hex[:12]}"
        return PauseAction(
            approval_id=pause_id,
            context={
                "tool_name": tool_name,
                "arguments": arguments,
                "reason": reason,
                "mode": self._mode,
            },
        )

    def mark_approved(self, approval_id: str) -> None:
        """
        标记一个审批请求为已通过。

        从 pause 恢复时调用，后续同 ID 的请求直接放行。

        Args:
            approval_id: 审批请求 ID。
        """
        self._approved_ids.add(approval_id)
