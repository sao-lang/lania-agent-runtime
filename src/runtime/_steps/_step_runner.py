"""
StepRunner 单步执行器。

封装 before_llm → LLM → after_llm → tool 的单步执行逻辑，
使用 Pipeline[T] 框架实现可配置的管线。
当前作为 AgentRuntime 的辅助组件，提供标准的单步执行流程。

被所有 LoopStrategy 共享使用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.runtime._types import (
    AllowAction,
    BlockAction,
    HookPoint,
    PauseAction,
)
from src.runtime.context._payload import ContextPayload
from src.runtime.context._serializer import DefaultSerializer, MessageSerializer
from src.runtime.hooks._registry import HookRegistry
from src.runtime.llm._models import FinishReason, LLMResponse
from src.runtime.loops._types import StepResult, StepStatus

if TYPE_CHECKING:
    from src.runtime._control import RuntimeController
    from src.runtime.context._context import RuntimeContext


class StepRunner:
    """
    单步执行器——封装一步完整的执行流程。

    负责 before_llm → LLM → after_llm → tool 的编排，
    通过 HookRegistry 在关键节点触发 hooks。

    设计上是一个无状态组件，接收 Runtime 的上下文执行逻辑，
    内部不持有 Runtime 状态。
    """

    def __init__(
        self,
        hooks: HookRegistry,
        llm_executor: Any | None = None,
        tool_executor: Any | None = None,
        serializer: MessageSerializer | None = None,
    ) -> None:
        """
        初始化 StepRunner。

        Args:
            hooks: HookRegistry 实例。
            llm_executor: LLM 执行器。
            tool_executor: 工具执行器。
            serializer: 消息序列化器。
        """
        self._hooks = hooks
        self._llm_executor = llm_executor
        self._tool_executor = tool_executor
        self._serializer = serializer or DefaultSerializer()

    async def run_llm_step(
        self,
        context_payload: ContextPayload,
        messages: list[dict],
        budget: Any,
        controller: RuntimeController,
    ) -> str | None:
        """
        执行 LLM step。

        流程：
          before_llm Transform（Context assembly, RAG, Token mgmt）
        → before_serialize Transform（最终格式调整，provider 适配）
        → 序列化 ContextPayload → messages
        → before_llm Intercept（Input guardrails, Threat scanning）
        → LLM 调用
        → after_llm Intercept（Output guardrails, Groundedness）
        → after_llm Observer

        Args:
            context_payload: 上下文负载。
            messages: 消息列表。
            budget: 预算快照。
            controller: RuntimeController 实例（受控 Runtime 接口）。

        Returns:
            阻断时的错误消息，或 None 表示正常执行。
        """
        ctx = controller.build_context()

        # before_llm transformers
        await self._hooks.run_transformers(HookPoint.BEFORE_LLM, context_payload, ctx)

        # before_serialize transformers（仅在 dirty 时执行）
        if context_payload.is_dirty:
            await self._hooks.run_transformers(HookPoint.BEFORE_SERIALIZE, context_payload, ctx)

        # before_llm interceptors
        intercept_result = await self._hooks.run_interceptors(
            HookPoint.BEFORE_LLM, context_payload, ctx
        )
        if isinstance(intercept_result, BlockAction):
            error_msg = f"请求被拦截: {intercept_result.reason}"
            messages.append({"role": "assistant", "content": error_msg})
            return error_msg
        if isinstance(intercept_result, PauseAction):
            await controller.handle_pause(intercept_result)
            return None

        # 序列化 ContextPayload → messages
        if context_payload.is_dirty:
            serialized = await self._serializer.serialize(context_payload)
            if serialized:
                # 原地修改 messages 列表（保持引用不变）
                if messages:
                    messages[:] = [serialized[0]] + messages[1:]
                else:
                    messages[:] = serialized

        # LLM 调用
        if self._llm_executor is None:
            return None
        llm_response = await self._llm_executor(ctx)

        # 追加 LLM 回复
        if isinstance(llm_response, dict):
            messages.append(llm_response)
        elif isinstance(llm_response, str):
            messages.append({"role": "assistant", "content": llm_response})

        # after_llm interceptors
        intercept_result = await self._hooks.run_interceptors(
            HookPoint.AFTER_LLM, llm_response, ctx
        )
        if isinstance(intercept_result, BlockAction):
            return "after_llm 拦截"
        if isinstance(intercept_result, AllowAction) and intercept_result.modified is not None:
            modified = intercept_result.modified
            if messages and messages[-1].get("role") == "assistant":
                if isinstance(modified, dict):
                    messages[-1] = modified
                elif isinstance(modified, str):
                    messages[-1]["content"] = modified

        # after_llm observers
        await self._hooks.run_observers(
            HookPoint.AFTER_LLM,
            {"type": "after_llm", "response": llm_response},
            ctx,
        )

        return None

    async def run_tool_step(
        self,
        tool_call_request: dict | None,
        messages: list[dict],
        controller: RuntimeController,
    ) -> None:
        """
        执行 Tool step。

        流程：
          before_tool Intercept
        → Tool 调用
        → after_tool Transform
        → after_tool Observer

        Args:
            tool_call_request: 工具调用请求。
            messages: 消息列表。
            controller: RuntimeController 实例。
        """
        ctx = controller.build_context()

        # before_tool interceptors
        intercept_result = await self._hooks.run_interceptors(
            HookPoint.BEFORE_TOOL, tool_call_request or {}, ctx
        )
        if isinstance(intercept_result, BlockAction):
            return
        if isinstance(intercept_result, PauseAction):
            await controller.handle_pause(intercept_result)
            return

        # Tool 调用
        if self._tool_executor is not None:
            tool_result = await self._tool_executor(ctx)
            if isinstance(tool_result, dict):
                messages.append(tool_result)
            else:
                messages.append({"role": "tool", "content": str(tool_result)})

            # after_tool transformers
            await self._hooks.run_transformers(HookPoint.AFTER_TOOL, tool_result, ctx)

        # after_tool observers
        await self._hooks.run_observers(
            HookPoint.AFTER_TOOL,
            {"type": "after_tool"},
            ctx,
        )

    async def run_llm_only(
        self,
        ctx: RuntimeContext,
        controller: RuntimeController,
        system_prompt_override: str = "",
    ) -> LLMResponse | None:
        """
        仅执行 LLM 调用（不执行工具），走完整的 before_llm/after_llm hook 管线。

        专供 PlanExecuteLoop 的 Planner / Replanner 使用，
        确保治理组件（Transform / Intercept / Observer）对规划环节可见。

        流程：
          before_llm Transform → before_llm Intercept
          → 序列化 → LLM 调用
          → after_llm Intercept → after_llm Observer

        Args:
            ctx: RuntimeContext 实例。
            controller: RuntimeController 实例。
            system_prompt_override: 可选的 system prompt 覆盖。

        Returns:
            LLMResponse 实例，或 None（被阻断时）。
        """
        # before_llm transformers
        context_payload = controller.context_payload
        await self._hooks.run_transformers(HookPoint.BEFORE_LLM, context_payload, ctx)

        # before_serialize transformers（仅在 dirty 时执行）
        if context_payload.is_dirty:
            await self._hooks.run_transformers(HookPoint.BEFORE_SERIALIZE, context_payload, ctx)

        # before_llm interceptors
        intercept_result = await self._hooks.run_interceptors(
            HookPoint.BEFORE_LLM, context_payload, ctx
        )
        if isinstance(intercept_result, BlockAction):
            return None
        if isinstance(intercept_result, PauseAction):
            await controller.handle_pause(intercept_result)
            return None

        # 序列化 ContextPayload → messages
        if context_payload.is_dirty:
            serialized = await self._serializer.serialize(context_payload)
            if serialized:
                controller.messages = (
                    [serialized[0]] + controller.messages[1:] if controller.messages else serialized
                )

        # LLM 调用（兼容新旧接口）
        executor = self._llm_executor
        if executor is None:
            return None

        if hasattr(executor, "execute"):
            llm_response: LLMResponse = await executor.execute(ctx)
        else:
            raw = await executor(ctx)
            llm_response = controller.legacy_to_llm_response(raw)

        # 追加 LLM 回复
        controller.append_llm_response(llm_response)
        controller.last_llm_response = llm_response

        # after_llm transformers
        await self._hooks.run_transformers(HookPoint.AFTER_LLM, llm_response, ctx)

        # after_llm interceptors
        intercept_result = await self._hooks.run_interceptors(
            HookPoint.AFTER_LLM, llm_response, ctx
        )
        if isinstance(intercept_result, BlockAction):
            controller.status = "error"
            return None

        # after_llm observers
        await self._hooks.run_observers(
            HookPoint.AFTER_LLM,
            {"type": "after_llm", "response": llm_response},
            ctx,
        )

        return llm_response

    async def run_step(
        self,
        ctx: RuntimeContext,
        controller: RuntimeController,
    ) -> StepResult:
        """
        执行一步完整的"LLM + 可能的工具调用"。

        这是 LoopStrategy 调用的单步入口——封装一次 LLM 调用 + 可选的工具执行。

        流程：
          before_llm Transform → before_llm Intercept → LLM
          → after_llm Intercept → after_llm Observer
          → 如果有 tool_calls → before_tool Intercept → Tool → after_tool Transform/Observer

        Args:
            ctx: RuntimeContext 实例。
            runtime: AgentRuntime 实例。

        Returns:
            StepResult 实例——包含 finish_reason、status、tool_calls 等。
        """
        # === Phase 1: LLM 调用 ===
        context_payload = controller.context_payload

        # before_llm transformers
        await self._hooks.run_transformers(HookPoint.BEFORE_LLM, context_payload, ctx)

        # before_serialize transformers（仅在 dirty 时执行）
        if context_payload.is_dirty:
            await self._hooks.run_transformers(HookPoint.BEFORE_SERIALIZE, context_payload, ctx)

        # before_llm interceptors
        intercept_result = await self._hooks.run_interceptors(
            HookPoint.BEFORE_LLM, context_payload, ctx
        )
        if isinstance(intercept_result, BlockAction):
            error_msg = f"请求被拦截: {intercept_result.reason}"
            controller.messages.append({"role": "assistant", "content": error_msg})
            controller.status = "error"
            return StepResult(
                finish_reason=FinishReason.ERROR,
                status=StepStatus.BLOCKED,
                error=error_msg,
            )
        if isinstance(intercept_result, PauseAction):
            await controller.handle_pause(intercept_result)
            return StepResult(
                finish_reason=FinishReason.STOP,
                status=StepStatus.PAUSED,
            )

        # 序列化 ContextPayload → messages
        if context_payload.is_dirty:
            serialized = await self._serializer.serialize(context_payload)
            if serialized:
                controller.messages = (
                    [serialized[0]] + controller.messages[1:] if controller.messages else serialized
                )

        # LLM 调用（兼容新旧接口）
        executor = self._llm_executor
        if executor is None:
            return StepResult(
                finish_reason=FinishReason.ERROR,
                status=StepStatus.ERROR,
                error="LLM executor 未设置",
            )

        if hasattr(executor, "execute"):
            llm_response: LLMResponse = await executor.execute(ctx)
        else:
            raw = await executor(ctx)
            llm_response = controller.legacy_to_llm_response(raw)

        # 追加 LLM 回复
        controller.append_llm_response(llm_response)
        controller.last_llm_response = llm_response

        # after_llm transformers
        await self._hooks.run_transformers(HookPoint.AFTER_LLM, llm_response, ctx)

        # after_llm interceptors
        intercept_result = await self._hooks.run_interceptors(
            HookPoint.AFTER_LLM, llm_response, ctx
        )
        if isinstance(intercept_result, BlockAction):
            controller.status = "error"
            return StepResult(
                finish_reason=FinishReason.ERROR,
                status=StepStatus.BLOCKED,
                error="after_llm 拦截",
            )
        if isinstance(intercept_result, AllowAction) and intercept_result.modified is not None:
            modified = intercept_result.modified
            if controller.messages and controller.messages[-1].get("role") == "assistant":
                if isinstance(modified, LLMResponse):
                    controller.messages[-1] = controller.llm_response_to_dict(modified)
                elif isinstance(modified, dict):
                    controller.messages[-1] = modified
                elif isinstance(modified, str):
                    controller.messages[-1]["content"] = modified

        # after_llm observers
        await self._hooks.run_observers(
            HookPoint.AFTER_LLM,
            {"type": "after_llm", "response": llm_response},
            ctx,
        )

        # === Phase 2: 工具调用（如果有） ===
        tool_calls = list(llm_response.tool_calls)
        for tc in tool_calls:
            # 重建 ctx：确保 ctx.messages 包含刚追加的 LLM 回复（含 tool_calls）
            fresh_ctx = controller.build_context()

            # before_tool interceptors
            tool_ctx = {"tool_name": tc.name, "arguments": tc.arguments}
            intercept_result = await self._hooks.run_interceptors(
                HookPoint.BEFORE_TOOL, tool_ctx, fresh_ctx
            )
            if isinstance(intercept_result, BlockAction):
                continue
            if isinstance(intercept_result, PauseAction):
                await controller.handle_pause(intercept_result)
                return StepResult(
                    finish_reason=FinishReason.TOOL_CALLS,
                    status=StepStatus.PAUSED,
                )

            # Tool 调用
            if self._tool_executor is not None:
                tool_result = await self._tool_executor(fresh_ctx)
                if isinstance(tool_result, dict):
                    controller.messages.append(tool_result)
                else:
                    controller.messages.append({"role": "tool", "content": str(tool_result)})

                # after_tool transformers（用最新 ctx）
                fresh_ctx2 = controller.build_context()
                await self._hooks.run_transformers(HookPoint.AFTER_TOOL, tool_result, fresh_ctx2)

            # after_tool observers（用最新 ctx）
            fresh_ctx3 = controller.build_context()
            await self._hooks.run_observers(
                HookPoint.AFTER_TOOL,
                {"type": "after_tool", "tool_name": tc.name},
                fresh_ctx3,
            )

        return StepResult(
            finish_reason=llm_response.finish_reason,
            status=StepStatus.SUCCESS,
            content=llm_response.content,
            tool_calls=tool_calls,
        )
