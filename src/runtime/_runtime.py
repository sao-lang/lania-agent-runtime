"""
AgentRuntime 核心类。

状态机 + Step Loop 实现。
持有执行必须的最小状态集，Hook 是无状态纯函数。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator

from src.runtime._control import RuntimeController
from src.runtime._engine_mixin import EngineSettersMixin
from src.runtime._helper_mixin import RuntimeHelperMixin
from src.runtime._hook_mixin import HookRegistratorMixin
from src.runtime._steps import StepRunner
from src.runtime._types import (
    BudgetSnapshot,
    ExecutorFn,
    HookPoint,
    PrimitiveType,
    RouterFn,
    RunResult,
    RuntimeStatus,
    StreamEvent,
)
from src.runtime.context._context import RuntimeContext
from src.runtime.context._payload import ContextPayload
from src.runtime.context._serializer import (
    DefaultSerializer,
    MessageSerializer,
)
from src.runtime.hooks._registry import HookRegistry
from src.runtime.llm._models import FinishReason, LLMResponse
from src.runtime.loops import LoopStrategy, LoopStrategyFactory

if TYPE_CHECKING:
    from src.runtime.plugins._plugin import PluggableComponent


class AgentRuntime(HookRegistratorMixin, EngineSettersMixin, RuntimeHelperMixin):
    """
    Agent Runtime 核心类。

    状态机 + Step Loop，持有执行必须的最小状态集。
    Hook 是无状态纯函数，通过 RuntimeContext 只读访问运行时状态。

    Attributes:
        session_id: 会话标识。
        agent_id: Agent 标识。
        status: Runtime 状态。
    """

    def __init__(
        self,
        *,
        system_prompt: str,
        hooks: HookRegistry | None = None,
        llm_executor: ExecutorFn | None = None,
        tool_executor: ExecutorFn | None = None,
        loop_strategy: LoopStrategy | None = None,
        loop_strategy_name: str = "react",
        router: RouterFn | None = None,
        serializer: MessageSerializer | None = None,
        services: dict[str, Any] | None = None,
        agent_id: str = "",
    ) -> None:
        """
        初始化 AgentRuntime——纯壳，不感知任何外部组件。

        Args:
            system_prompt: 系统提示词。
            hooks: HookRegistry 实例。不提供则创建新的。
            llm_executor: LLM 执行器。
            tool_executor: 工具执行器。
            loop_strategy: LoopStrategy 实例。提供此参数时忽略 loop_strategy_name。
            loop_strategy_name: 策略名称（"react" | "plan_and_execute" |
                "workflow"，默认 "react"）。仅 loop_strategy 为 None 时生效。
            router: 路由函数。
            serializer: 消息序列化器。不提供则使用 DefaultSerializer。
            services: 外部服务引用字典。Builder 可在 build() 中注入
                memory_service / context_manager / tools_schema 等服务。
            agent_id: Agent 标识。
        """
        self.session_id: str = f"sess_{uuid.uuid4().hex[:12]}"
        self.agent_id: str = agent_id or f"agent_{uuid.uuid4().hex[:8]}"
        self.status: RuntimeStatus = RuntimeStatus.IDLE

        # 核心组件
        self._hooks: HookRegistry = hooks or HookRegistry()
        self._llm_executor: ExecutorFn | None = llm_executor
        self._tool_executor: ExecutorFn | None = tool_executor
        self._router: RouterFn | None = router
        self._serializer: MessageSerializer = serializer or DefaultSerializer()

        # 注册默认预算记账 Transform（after_llm），优先级 999 让用户 Transform 优先执行
        self._hooks.register(
            HookPoint.AFTER_LLM,
            self._budget_after_llm_transform,
            primitive=PrimitiveType.TRANSFORM,
            name="_default_budget",
            priority=999,
        )

        # 外部服务（仅用于 Hook 间共享数据）
        self._services: dict[str, Any] = dict(services or {})
        # 注入 controller 供 hook 使用（替代旧的 services["_runtime"] 后门）
        # 注意：services["_runtime"] 已移除——hook 如需访问 Runtime 状态，
        # 应通过 services["_controller"] 获取 RuntimeController 实例

        # RuntimeController —— StepRunner 和 LoopStrategy 的受控接口
        self._controller = RuntimeController(self)
        self._services["_controller"] = self._controller

        # StepRunner —— 被所有 LoopStrategy 共享
        self._step_runner = StepRunner(
            hooks=self._hooks,
            llm_executor=self._llm_executor,
            tool_executor=self._tool_executor,
            serializer=self._serializer,
        )

        # LoopStrategy —— 实例优先，否则按名创建
        if loop_strategy is not None:
            self._loop = loop_strategy
        else:
            self._register_default_strategies()
            self._loop = LoopStrategyFactory.create(
                loop_strategy_name,
                hooks=self._hooks,
                step_runner=self._step_runner,
                controller=self._controller,
                router=self._router,
            )

        # 上下文负载
        self._context_payload: ContextPayload = ContextPayload(
            system_prompt=system_prompt,
        )

        # 状态
        self._messages: list[dict] = []
        self._plan: dict | None = None
        self._step_index: int = 0
        self._step_history: list[dict] = []
        self._budget: BudgetSnapshot = BudgetSnapshot()
        self._pause_state: dict = {
            "is_paused": False,
            "pending_approvals": [],
            "resume_token": "",
        }
        self._error_state: dict = {
            "consecutive_errors": 0,
            "max_retries": 3,
            "last_error": None,
        }
        self._last_llm_response: LLMResponse | None = None
        self._timeout: dict = {
            "step_timeout_ms": 60_000,
            "total_timeout_ms": 600_000,
            "remaining_ms": 600_000,
            "step_start_at": 0,
        }
        self._cancelled: bool = False
        self._components: dict[str, "PluggableComponent"] = {}

    # ============ 核心执行 ============

    async def run(self, user_input: str) -> RunResult:
        """
        运行 Agent，处理用户输入并返回最终回复。

        Args:
            user_input: 用户输入文本。

        Returns:
            RunResult 实例（含助理回复、会话上下文、用量统计）。
        """
        self.status = RuntimeStatus.RUNNING

        try:
            # session_start hooks
            await self._hooks.run_observers(
                HookPoint.SESSION_START,
                {"type": "session_start", "input": user_input},
                self._build_context(),
            )

            # 添加用户消息
            self._messages.append({"role": "user", "content": user_input})

            # 执行 step loop
            ctx = self._build_context()
            await self._loop.run(ctx)
            # LoopStrategy 完成后设置 ended 状态
            if self.status == RuntimeStatus.RUNNING:
                self.status = RuntimeStatus.ENDED
            return self._make_result()

        except Exception as e:
            self.status = RuntimeStatus.ERROR
            self._error_state["last_error"] = e
            self._error_state["consecutive_errors"] += 1

            # on_error hooks
            await self._hooks.run_observers(
                HookPoint.ON_ERROR,
                {"type": "error", "error": str(e)},
                self._build_context(),
            )

            return RunResult(
                content=f"发生错误: {e!s}",
                session_id=self.session_id,
                messages=list(self._messages),
                status=RuntimeStatus.ERROR,
            )

        finally:
            if self.status not in (
                RuntimeStatus.ERROR,
                RuntimeStatus.CANCELLED,
                RuntimeStatus.PAUSED,
            ):
                self.status = RuntimeStatus.ENDED
            # session_end hooks
            await self._hooks.run_observers(
                HookPoint.SESSION_END,
                {"type": "session_end", "status": self.status},
                self._build_context(),
            )

    # ============ 流式执行 ============

    async def run_stream(
        self,
        user_input: str,
    ) -> "AsyncIterator[StreamEvent]":
        """
        流式入口：用户输入 → Runtime 处理 → 逐事件推送。

        产出 StreamEvent 序列：
          StreamEvent(type="text", content="文本片段")
          StreamEvent(type="tool_start", name="get_weather")
          StreamEvent(type="tool_end", name="get_weather", content="结果")
          StreamEvent(type="done", metadata={"result": RunResult(...)})

        Args:
            user_input: 用户输入文本。

        Yields:
            StreamEvent 事件流。
        """
        self.status = RuntimeStatus.RUNNING

        try:
            # session_start hooks
            await self._hooks.run_observers(
                HookPoint.SESSION_START,
                {"type": "session_start", "input": user_input},
                self._build_context(),
            )

            # 添加用户消息
            self._messages.append({"role": "user", "content": user_input})

            # 使用 LoopStrategy 流式执行
            ctx = self._build_context()
            async for event in self._loop.run_stream(ctx):
                yield StreamEvent(**event)
            yield StreamEvent(
                type="done",
                metadata={"result": self._make_result()},
            )

        except Exception as e:
            self.status = RuntimeStatus.ERROR
            self._error_state["last_error"] = e
            yield StreamEvent(type="error", error=str(e))
            yield StreamEvent(
                type="done",
                metadata={
                    "result": RunResult(
                        content=f"发生错误: {e!s}",
                        session_id=self.session_id,
                        status=RuntimeStatus.ERROR,
                    )
                },
            )
        finally:
            if self.status not in (
                RuntimeStatus.ERROR,
                RuntimeStatus.CANCELLED,
                RuntimeStatus.PAUSED,
            ):
                self.status = RuntimeStatus.ENDED

    # ============ 内部方法 ============

    async def _get_next_step(self, ctx: RuntimeContext) -> str:
        """
        获取下一步的 step_id。

        如果设置了自定义 router 则调用之，否则返回默认行为。
        默认行为：
          - 如果有 plan，按 plan 的 steps 顺序执行
          - 如果上一步 LLM 返回了 tool_calls，走 tool 步骤
          - 如果 LLM 返回了 stop/length/error，结束循环
          - 首次进入且无 plan，走 llm 步骤

        Args:
            ctx: RuntimeContext 快照。

        Returns:
            下一步的 step_id 或 "end"。
        """
        if self._router is not None:
            return await self._router(ctx)

        # 默认 router：如果 plan 存在，走 plan
        if self._plan is not None:
            steps = self._plan.get("steps", [])
            if self._step_index < len(steps):
                return steps[self._step_index]
            return "end"

        # 无 plan：基于上一步结果判断
        last_response = self._last_llm_response

        # 上一步 LLM 请求了工具调用：
        #  - 仍有未执行的工具调用 → 走 tool 步骤
        #  - 工具已执行完毕 → 继续 llm 步骤（避免同一批工具被重复执行）
        if last_response is not None and last_response.finish_reason == FinishReason.TOOL_CALLS:
            return "tool" if self._has_pending_tool_calls() else "llm"

        # 如果 LLM 回复停止了，或发生了错误/截断，结束循环
        if last_response is not None:
            return "end"

        # 首次进入，走 llm 步骤
        if self._llm_executor is not None:
            return "llm"
        return "end"

    def _has_pending_tool_calls(self) -> bool:
        """
        检查消息中是否存在尚未执行（无对应 tool 结果）的工具调用。

        Returns:
            存在待执行工具调用返回 True，否则 False。
        """
        messages = self._messages
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.get("role") != "assistant" or not msg.get("tool_calls"):
                continue
            call_ids = {tc.get("id") for tc in msg["tool_calls"]}
            executed_ids = {
                m.get("tool_call_id")
                for m in messages[i + 1 :]
                if m.get("role") == "tool" and m.get("tool_call_id") in call_ids
            }
            return not call_ids.issubset(executed_ids)
        return False

    async def _execute_step(self, step_id: str, ctx: RuntimeContext) -> None:
        """
        执行指定 step。

        统一委托给 StepRunner（唯一的单步执行实现），
        此方法仅为外部循环控制（run_step）保留的兼容入口。

        Args:
            step_id: step 标识。
            ctx: RuntimeContext 快照。
        """
        if step_id == "tool":
            await self._execute_tool_step(ctx)
        else:
            # "llm" 及 plan 自定义 step_id 均走 LLM 步骤
            await self._execute_llm_step(ctx)

    async def _execute_llm_step(self, ctx: RuntimeContext) -> None:
        """
        执行 LLM step（兼容入口）。

        统一委托给 StepRunner.run_llm_only —— 唯一的单步执行实现，
        此方法仅为外部循环控制（run_step）保留的薄包装。
        """
        await self._step_runner.run_llm_only(ctx, self._controller)

    async def _execute_tool_step(self, ctx: RuntimeContext) -> None:
        """
        执行 Tool step（兼容入口）。

        统一委托给 StepRunner.run_tool_step —— 唯一的单步执行实现，
        此方法仅为外部循环控制（run_step）保留的薄包装。
        """
        await self._step_runner.run_tool_step(
            self._context_payload.tool_call_request or {},
            self._messages,
            self._controller,
        )
