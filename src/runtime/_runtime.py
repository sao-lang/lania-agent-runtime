"""
AgentRuntime 核心类。

状态机 + Step Loop 实现。
持有执行必须的最小状态集，Hook 是无状态纯函数。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator, cast

from src.runtime._engine_mixin import EngineSettersMixin
from src.runtime._helper_mixin import RuntimeHelperMixin
from src.runtime._hook_mixin import HookRegistratorMixin
from src.runtime._steps import StepRunner
from src.runtime._types import (
    AllowAction,
    BlockAction,
    BudgetSnapshot,
    ExecutorFn,
    HookPoint,
    PauseAction,
    PrimitiveType,
    RouterFn,
    RunResult,
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

logger = logging.getLogger(__name__)

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
        loop_executor: ExecutorFn | None = None,
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
            loop_executor: Step Loop 执行器（旧接口）。
            loop_strategy: LoopStrategy 实例（新接口，优先使用）。
            loop_strategy_name: 策略名称（"react" | "plan_and_execute" |
                "workflow"，默认 "react"）。
            router: 路由函数。
            serializer: 消息序列化器。不提供则使用 DefaultSerializer。
            services: 外部服务引用字典。Builder 可在 build() 中注入
                memory_service / context_manager / tools_schema 等服务。
            agent_id: Agent 标识。
        """
        self.session_id: str = f"sess_{uuid.uuid4().hex[:12]}"
        self.agent_id: str = agent_id or f"agent_{uuid.uuid4().hex[:8]}"
        self.status: str = "idle"

        # 核心组件
        self._hooks: HookRegistry = hooks or HookRegistry()
        self._llm_executor: ExecutorFn | None = llm_executor
        self._tool_executor: ExecutorFn | None = tool_executor
        self._loop_executor: ExecutorFn | None = loop_executor
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
        from src.runtime._control import RuntimeController

        self._controller = RuntimeController(self)
        self._services["_controller"] = self._controller

        # StepRunner —— 被所有 LoopStrategy 共享
        self._step_runner = StepRunner(
            hooks=self._hooks,
            llm_executor=self._llm_executor,
            tool_executor=self._tool_executor,
            serializer=self._serializer,
        )

        # LoopStrategy —— 使用新接口或旧接口
        if loop_strategy is not None:
            self._loop = loop_strategy
        elif self._loop_executor is not None:
            # 旧接口：保留 loop_executor 行为
            self._loop: LoopStrategy | None = None
        else:
            # 通过工厂创建（传入 controller 替代 services["_runtime"] 后门）
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
        self.status = "running"

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
            if self._loop_executor is not None:
                # 旧接口：使用自定义 loop executor
                result = await self._loop_executor(self._build_context())
                return self._make_result(self._extract_response(result))

            if self._loop is not None:
                # 新接口：使用 LoopStrategy
                ctx = self._build_context()
                await self._loop.run(ctx)
                # LoopStrategy 完成后设置 ended 状态
                if self.status == "running":
                    self.status = "ended"
                return self._make_result()

            # 默认 loop：ReAct 风格（兜底）
            await self._default_loop(user_input)
            if self.status == "running":
                self.status = "ended"
            return self._make_result()

        except Exception as e:
            self.status = "error"
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
                status="error",
            )

        finally:
            if self.status not in ("error", "cancelled", "paused"):
                self.status = "ended"
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
        self.status = "running"

        try:
            # session_start hooks
            await self._hooks.run_observers(
                HookPoint.SESSION_START,
                {"type": "session_start", "input": user_input},
                self._build_context(),
            )

            # 添加用户消息
            self._messages.append({"role": "user", "content": user_input})

            if self._loop_executor is not None:
                # 自定义 loop executor 流式场景
                result = await self._loop_executor(self._build_context())
                content = self._extract_response(result)
                yield StreamEvent(type="text", content=content)
                yield StreamEvent(
                    type="done",
                    metadata={"result": self._make_result(content)},
                )
                return

            # 使用 LoopStrategy 流式执行
            if self._loop is not None:
                ctx = self._build_context()
                async for event in self._loop.run_stream(ctx):
                    yield StreamEvent(**event)
                yield StreamEvent(
                    type="done",
                    metadata={"result": self._make_result()},
                )
                return

            # 默认流式循环（兜底）
            max_steps = self._budget.step_limit or 10
            for _ in range(max_steps):
                if self.status != "running":
                    break

                ctx = self._build_context()

                await self._hooks.run_transformers(HookPoint.BEFORE_STEP, {}, ctx)

                next_step = await self._get_next_step(ctx)
                if next_step == "end":
                    break

                self._step_index += 1
                self._timeout["step_start_at"] = int(time.time() * 1000)

                if next_step == "llm" and hasattr(self._llm_executor, "execute_stream"):
                    # 流式 LLM 执行
                    executor = self._llm_executor
                    collector, response = await cast(Any, executor).execute_stream(ctx)
                    # 逐 chunk 产出 text 事件
                    if collector.full_content:
                        yield StreamEvent(type="text", content=collector.full_content)
                    # 如果有工具调用，产出 tool_start 事件
                    for tc in response.tool_calls:
                        yield StreamEvent(type="tool_start", name=tc.name)

                    # 写回 messages 和 budget
                    self._append_llm_response(response)
                    self._last_llm_response = response

                    # after_llm transformers
                    await self._hooks.run_transformers(
                        HookPoint.AFTER_LLM, response, ctx
                    )

                elif next_step == "llm":
                    # 非流式 LLM 执行
                    await self._execute_llm_step(ctx)

                elif next_step == "tool":
                    # Tool 执行
                    if self._tool_executor is not None:
                        # 查询对应的 tool name
                        tool_name = "tool"
                        if self._last_llm_response and self._last_llm_response.tool_calls:
                            tool_name = self._last_llm_response.tool_calls[0].name
                        yield StreamEvent(type="tool_start", name=tool_name)

                        tool_result = await self._tool_executor(ctx)
                        if isinstance(tool_result, dict):
                            self._messages.append(tool_result)
                        else:
                            self._messages.append(
                                {"role": "tool", "content": str(tool_result)}
                            )
                        result_content = str(tool_result)
                        yield StreamEvent(type="tool_end", name=tool_name, content=result_content)

                        await self._hooks.run_transformers(
                            HookPoint.AFTER_TOOL, tool_result, ctx
                        )
                        await self._hooks.run_observers(
                            HookPoint.AFTER_TOOL, {"type": "after_tool"}, ctx
                        )

                await self._hooks.run_transformers(HookPoint.AFTER_STEP, {}, ctx)
                self._budget.step_count += 1

            # 产出 done 事件
            yield StreamEvent(
                type="done",
                metadata={"result": self._make_result()},
            )

        except Exception as e:
            self.status = "error"
            self._error_state["last_error"] = e
            yield StreamEvent(type="error", error=str(e))
            yield StreamEvent(
                type="done",
                metadata={"result": RunResult(
                    content=f"发生错误: {e!s}",
                    session_id=self.session_id,
                    status="error",
                )},
            )
        finally:
            if self.status not in ("error", "cancelled", "paused"):
                self.status = "ended"

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

        # 如果上一步 LLM 请求了工具调用，走 tool 步骤
        if last_response is not None and last_response.finish_reason == FinishReason.TOOL_CALLS:
            return "tool"

        # 如果 LLM 回复停止了，或发生了错误/截断，结束循环
        if last_response is not None:
            return "end"

        # 首次进入，走 llm 步骤
        if self._llm_executor is not None:
            return "llm"
        return "end"

    async def _execute_step(self, step_id: str, ctx: RuntimeContext) -> None:
        """
        执行指定 step。

        Args:
            step_id: step 标识。
            ctx: RuntimeContext 快照。
        """
        if step_id == "llm" and self._llm_executor is not None:
            await self._execute_llm_step(ctx)
        elif step_id == "tool" and self._tool_executor is not None:
            await self._execute_tool_step(ctx)
        else:
            # plan 自定义 step_id（非 "llm"/"tool"）：默认走 LLM 步骤
            logger.info(
                "_execute_step: plan step_id '%s' 映射为 llm 步骤",
                step_id,
            )
            if self._llm_executor is not None:
                await self._execute_llm_step(ctx)

    async def _execute_llm_step(self, ctx: RuntimeContext) -> None:
        """
        执行 LLM step。

        触发 before_llm Transform → before_serialize Transform
        → before_llm Intercept → LLM → after_llm 流程。

        同时兼容两种 LLM executor 接口：
          - 新接口（LLMExecutor）：executor.execute(ctx) → LLMResponse
          - 旧接口（ExecutorFn）：executor(ctx) → dict | str
        """
        # before_llm transformers（Context assembly, RAG, Token mgmt）
        await self._hooks.run_transformers(HookPoint.BEFORE_LLM, self._context_payload, ctx)

        # 检查 ContextAssemblerHook 是否已组装好 messages
        if self._context_payload.assembled_messages is not None:
            self._messages = list(self._context_payload.assembled_messages)
            self._context_payload.assembled_messages = None  # 消费后重置
        else:
            # before_serialize transformers（仅在 dirty 时执行）
            if self._context_payload.is_dirty:
                await self._hooks.run_transformers(
                    HookPoint.BEFORE_SERIALIZE, self._context_payload, ctx
                )

            # before_llm interceptors
            intercept_result = await self._hooks.run_interceptors(
                HookPoint.BEFORE_LLM, self._context_payload, ctx
            )
            if isinstance(intercept_result, BlockAction):
                self.status = "error"
                error_msg = f"请求被拦截: {intercept_result.reason}"
                self._messages.append({"role": "assistant", "content": error_msg})
                self._error_state["last_error"] = RuntimeError(error_msg)
                self._error_state["consecutive_errors"] += 1
                return
            if isinstance(intercept_result, PauseAction):
                await self._handle_pause(intercept_result)
                return

            # 序列化 ContextPayload → messages
            if self._context_payload.is_dirty:
                serialized = await self._serializer.serialize(self._context_payload)
                if serialized:
                    self._messages = (
                        [serialized[0]] + self._messages[1:] if self._messages else serialized
                    )

        # LLM 调用（兼容新旧接口）
        executor = self._llm_executor
        if executor is None:
            return

        # 检测是否为 LLMExecutor 新接口（有 .execute 方法）
        if hasattr(executor, "execute"):
            llm_response: LLMResponse = await cast(Any, executor).execute(ctx)
        else:
            # 旧接口：ExecutorFn 直接调用
            raw = await cast(Any, executor)(ctx)
            llm_response = self._legacy_to_llm_response(raw)

        # 追加 LLM 回复到消息列表
        self._append_llm_response(llm_response)

        # 保存最后响应供 Transform / Interceptor / Router 使用
        self._last_llm_response = llm_response

        # 重建 ctx，使 after_llm hooks 能看到最新 messages
        ctx = self._build_context()

        # after_llm transformers（预算记账等，Transform 管线统一处理）
        after_data = await self._hooks.run_transformers(HookPoint.AFTER_LLM, llm_response, ctx)

        # after_llm interceptors（Output guardrails, Groundedness）
        intercept_result = await self._hooks.run_interceptors(
            HookPoint.AFTER_LLM, after_data, ctx
        )
        if isinstance(intercept_result, BlockAction):
            self.status = "error"
            return
        if isinstance(intercept_result, AllowAction) and (intercept_result.modified is not None):
            # 替换最后一条 assistant 消息
            modified = intercept_result.modified
            if self._messages and (self._messages[-1].get("role") == "assistant"):
                if isinstance(modified, LLMResponse):
                    self._messages[-1] = self._llm_response_to_dict(modified)
                elif isinstance(modified, dict):
                    self._messages[-1] = modified
                elif isinstance(modified, str):
                    self._messages[-1]["content"] = modified

        # after_llm observers
        await self._hooks.run_observers(
            HookPoint.AFTER_LLM,
            {"type": "after_llm", "response": llm_response},
            ctx,
        )

    async def _execute_tool_step(self, ctx: RuntimeContext) -> None:
        """
        执行 Tool step。

        触发 before_tool → Tool 调用 → after_tool 流程。
        """
        # 重建 ctx：确保 ctx.messages 包含上一步 LLM 回复（含 tool_calls）
        # 因为 _default_loop 在 LLM 调用后未重建上下文
        fresh_ctx = self._build_context()

        # before_tool interceptors
        intercept_result = await self._hooks.run_interceptors(
            HookPoint.BEFORE_TOOL,
            self._context_payload.tool_call_request or {},
            fresh_ctx,
        )
        if isinstance(intercept_result, BlockAction):
            self.status = "error"
            return
        if isinstance(intercept_result, PauseAction):
            await self._handle_pause(intercept_result)
            return

        # Tool 调用
        if self._tool_executor is not None:
            tool_result = await self._tool_executor(fresh_ctx)

            # 追加工具结果到消息列表
            if isinstance(tool_result, dict):
                self._messages.append(tool_result)
            else:
                self._messages.append({"role": "tool", "content": str(tool_result)})

            # after_tool transformers
            await self._hooks.run_transformers(HookPoint.AFTER_TOOL, tool_result, ctx)

        # after_tool observers
        await self._hooks.run_observers(
            HookPoint.AFTER_TOOL,
            {"type": "after_tool"},
            ctx,
        )

    async def _default_loop(self, user_input: str) -> None:
        """
        默认 step loop（ReAct 风格，向后兼容兜底）。

        当未配置 LoopStrategy 且未配置 loop_executor 时使用。
        正常 Builder 流程中不可达（Builder 始终设置 LoopStrategy），
        保留仅作为手动构造 AgentRuntime 时的向后兼容路径。

        Args:
            user_input: 用户输入（仅用于 loop 计数）。
        """
        logger.warning(
            "_default_loop 被调用——未配置 LoopStrategy，使用向后兼容的兜底路径"
        )
        max_steps = self._budget.step_limit or 10

        for _ in range(max_steps):
            if self.status != "running" or self._cancelled:
                break

            ctx = self._build_context()

            # before_step
            await self._hooks.run_transformers(HookPoint.BEFORE_STEP, {}, ctx)

            # Router
            next_step = await self._get_next_step(ctx)
            if next_step == "end":
                break

            # 执行 step
            self._step_index += 1
            self._timeout["step_start_at"] = int(time.time() * 1000)

            await self._execute_step(next_step, ctx)

            # after_step
            await self._hooks.run_transformers(HookPoint.AFTER_STEP, {}, ctx)
            self._budget.step_count += 1

            # 记录 step history
            self._step_history.append(
                {
                    "step_index": self._step_index,
                    "step_id": next_step,
                    "timestamp": time.time(),
                }
            )


