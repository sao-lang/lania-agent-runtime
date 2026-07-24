"""
运行时上下文模块——RuntimeContext 定义。

RuntimeContext 是 Hook 看到的只读快照 + 类型安全的受限写接口。
每次 hook 调用时构造新实例，所有字段均为只读——修改需通过受限 writer 方法。
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from src.runtime._types import BudgetSnapshot


@dataclass(frozen=True)
class RuntimeContext:
    """
    Hook 看到的只读快照。每次 hook 调用时构造新实例。
    所有字段均为只读——修改需通过受限的 writer 方法。

    Attributes:
        session_id: 当前会话唯一标识。
        agent_id: 当前 Agent 唯一标识。
        step_index: 当前 step 序号。
        messages: 不可变消息序列（tuple 保证不可变）。
        plan: 执行计划字典。
        budget: 预算快照（只读）。
        services: 外部服务引用字典。
    """

    session_id: str = ""
    """会话唯一标识。"""

    agent_id: str = ""
    """Agent 唯一标识。"""

    step_index: int = 0
    """当前 step 序号。"""

    messages: tuple[dict, ...] = field(default_factory=tuple)
    """不可变消息序列。"""

    plan: dict | None = None
    """执行计划。"""

    budget: BudgetSnapshot = field(default_factory=BudgetSnapshot)
    """预算快照。"""

    services: dict[str, Any] = field(default_factory=dict)
    """外部服务引用字典。"""

    # --- 以下字段由 Runtime 内部设置，不对外暴露 ---
    _set_plan_callback: Callable[[dict], None] | None = field(default=None, repr=False)
    _deduct_budget_callback: Callable[[int], None] | None = field(default=None, repr=False)
    _update_context_payload_callback: Callable[
        [Callable[["ContextPayload"], "ContextPayload"]], None
    ] | None = field(
        default=None, repr=False
    )

    def set_plan(self, plan: dict) -> None:
        """
        更新执行计划。

        仅 Planner / Replan 使用。

        Args:
            plan: 新的执行计划字典。

        Raises:
            RuntimeError: 如果未设置 _set_plan_callback。
        """
        if self._set_plan_callback is None:
            raise RuntimeError("set_plan 未在 Runtime 中初始化")
        self._set_plan_callback(plan)

    def deduct_budget(self, tokens: int) -> None:
        """
        扣减 token 预算。

        仅 after_tool / after_llm Transform 使用。

        Args:
            tokens: 要扣减的 token 数量。

        Raises:
            RuntimeError: 如果未设置 _deduct_budget_callback。
        """
        if self._deduct_budget_callback is None:
            raise RuntimeError("deduct_budget 未在 Runtime 中初始化")
        self._deduct_budget_callback(tokens)

    def update_context_payload(
        self, updater: Callable[["ContextPayload"], "ContextPayload"]
    ) -> None:
        """
        允许 Transform 修改 ContextPayload 内容。

        所有上下文注入应通过此方法操作 ContextPayload，
        而非直接修改 messages。

        Args:
            updater: 接收 ContextPayload 并返回修改后的 ContextPayload 的回调函数。

        Raises:
            RuntimeError: 如果未设置 _update_context_payload_callback。
        """
        if self._update_context_payload_callback is None:
            raise RuntimeError("update_context_payload 未在 Runtime 中初始化")
        self._update_context_payload_callback(updater)


# 延迟导入规避循环依赖
from src.runtime.context._payload import ContextPayload  # noqa: E402, F811
