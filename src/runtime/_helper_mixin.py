"""
RuntimeHelperMixin——AgentRuntime 的内部辅助方法集。

提取自 AgentRuntime，职责：上下文构建、默认 Transform、LLMResponse 适配、
工具方法。不包含核心执行逻辑。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

from src.runtime._types import (
    BlockAction,
    BudgetSnapshot,
    HookPoint,
    PauseAction,
    RunResult,
    SessionSnapshot,
    ToolCallInfo,
)
from src.runtime.config._runtime_config import RuntimeConfig
from src.runtime.context._context import RuntimeContext
from src.runtime.context._payload import ContextPayload
from src.runtime.llm._models import FinishReason, LLMResponse, LLMUsage
from src.runtime.loops import LoopStrategyFactory

if TYPE_CHECKING:
    from src.runtime._builder import RuntimeBuilder
    from src.runtime._runtime import AgentRuntime


class RuntimeHelperMixin:
    """内部辅助方法集。"""

    # ============ 流式支持 ============

    async def emit_stream_chunk(self, chunk: str) -> None:
        """
        触发流式 chunk 的 Observer/Transform hooks。

        由流式 LLM Executor 在每收到一个 chunk 时调用。

        Args:
            chunk: 流式响应的文本片段。
        """
        ctx = self._build_context()
        # 先运行 Transform（允许修改 chunk）
        transformed = await self._hooks.run_transformers(HookPoint.ON_STREAM_CHUNK, chunk, ctx)
        # 再运行 Observer（只读）
        await self._hooks.run_observers(
            HookPoint.ON_STREAM_CHUNK,
            {"type": "on_stream_chunk", "chunk": transformed},
            ctx,
        )

    # ============ 内部方法 ============

    def _build_context(self) -> RuntimeContext:
        """构建当前 step 的 RuntimeContext 快照。"""
        return RuntimeContext(
            session_id=self.session_id,
            agent_id=self.agent_id,
            step_index=self._step_index,
            messages=tuple(self._messages),
            plan=self._plan,
            budget=BudgetSnapshot(
                token_used=self._budget.token_used,
                token_limit=self._budget.token_limit,
                step_count=self._budget.step_count,
                step_limit=self._budget.step_limit,
                cost_in_cents=self._budget.cost_in_cents,
            ),
            services=dict(self._services),
            _set_plan_callback=self._set_plan_impl,
            _deduct_budget_callback=self._deduct_budget_impl,
            _update_context_payload_callback=self._update_context_payload_impl,
        )

    def _set_plan_impl(self, plan: dict) -> None:
        """Runtime 内部：设置执行计划。"""
        self._plan = plan

    def _deduct_budget_impl(self, tokens: int) -> None:
        """Runtime 内部：扣减 token 预算。"""
        self._budget.token_used += tokens

    def _update_context_payload_impl(
        self, updater: Callable[[ContextPayload], ContextPayload]
    ) -> None:
        """Runtime 内部：更新 ContextPayload。"""
        self._context_payload = updater(self._context_payload)

    async def _handle_pause(self, pause_action: PauseAction) -> None:
        """处理暂停请求。"""
        self._pause_state["is_paused"] = True
        self._pause_state["pending_approvals"].append(
            {
                "id": pause_action.approval_id,
                "context": pause_action.context,
            }
        )
        self.status = "paused"

    def _register_default_strategies(self) -> None:
        """
        注册默认的 LoopStrategy 到工厂。

        不在模块级自动注册以避免循环导入。
        """
        from src.runtime.loops._plan_execute import PlanExecuteLoop
        from src.runtime.loops._react import ReActLoop
        from src.runtime.loops._workflow import WorkflowLoop

        if "react" not in LoopStrategyFactory._registry:
            LoopStrategyFactory.register("react", ReActLoop)
        if "plan_and_execute" not in LoopStrategyFactory._registry:
            LoopStrategyFactory.register("plan_and_execute", PlanExecuteLoop)
        if "workflow" not in LoopStrategyFactory._registry:
            LoopStrategyFactory.register("workflow", WorkflowLoop)

    # ============ 结果与响应处理 ============

    def _extract_response(self, result: Any) -> str:
        """从执行结果中提取字符串回复。"""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return result.get("content", "") or result.get("response", "") or str(result)
        return str(result)

    def _make_result(self, content: str = "") -> RunResult:
        """从当前 Runtime 状态构造 RunResult。

        Args:
            content: 可选的指定回复内容（为空时自动从 messages 提取）。

        Returns:
            RunResult 实例。
        """
        if not content:
            for msg in reversed(self._messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "") or ""
                    break

        # 提取工具调用信息
        tool_infos: list[ToolCallInfo] = []
        if self._last_llm_response:
            for tc in self._last_llm_response.tool_calls:
                tool_infos.append(
                    ToolCallInfo(
                        name=tc.name,
                        arguments=tc.arguments,
                    )
                )

        finish_reason = ""
        if self._last_llm_response:
            finish_reason = self._last_llm_response.finish_reason.value

        return RunResult(
            content=content,
            session_id=self.session_id,
            messages=list(self._messages),
            tool_calls=tool_infos,
            token_used=self._budget.token_used,
            finish_reason=finish_reason,
            status=self.status,
        )

    def _estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数量。"""
        return len(text) // 4 + 1

    # ============ 默认 Transform ============

    async def _budget_after_llm_transform(self, data: Any, ctx: Any) -> Any:
        """默认 after_llm Transform：从 LLMResponse 提取 token 用量并记账。

        注册为低优先级（999），用户可注册更高优先级的 Transform 覆盖或补充。

        Args:
            data: LLMResponse 实例或其他数据。
            ctx: RuntimeContext 实例。

        Returns:
            原样返回 data，不做修改。
        """
        if isinstance(data, LLMResponse):
            self._budget.token_used += data.usage.total_tokens
        return data

    # ============ LLMResponse 兼容适配 ============

    def _legacy_to_llm_response(self, raw: Any) -> LLMResponse:
        """将旧接口的返回值（dict/str）包装为 LLMResponse。

        Args:
            raw: 旧接口 executor 的返回值（dict 或 str）。

        Returns:
            包装后的 LLMResponse 实例。
        """
        if isinstance(raw, LLMResponse):
            return raw
        if isinstance(raw, dict):
            content = raw.get("content", "") or ""
            return LLMResponse(
                content=content,
                finish_reason=FinishReason.STOP,
                model=raw.get("model", ""),
                usage=LLMUsage(
                    prompt_tokens=raw.get("usage", {}).get("prompt_tokens", 0),
                    completion_tokens=raw.get("usage", {}).get("completion_tokens", 0),
                ),
            )
        # str 或其他类型
        text = str(raw)
        return LLMResponse(
            content=text,
            finish_reason=FinishReason.STOP,
            usage=LLMUsage(
                prompt_tokens=0,
                completion_tokens=self._estimate_tokens(text),
            ),
        )

    def _llm_response_to_dict(self, response: LLMResponse) -> dict:
        """将 LLMResponse 转换为 messages 可用的 dict 格式。

        Args:
            response: LLMResponse 实例。

        Returns:
            符合 messages 格式的 dict。
        """
        msg: dict = {"role": "assistant", "content": response.content}
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.raw_arguments,
                    },
                }
                for tc in response.tool_calls
            ]
        return msg

    def _append_llm_response(self, response: LLMResponse) -> None:
        """将 LLMResponse 追加到消息列表。

        Args:
            response: LLMResponse 实例。
        """
        self._messages.append(self._llm_response_to_dict(response))

    # ============ 工厂方法 ============

    @classmethod
    def builder(cls) -> "RuntimeBuilder":
        """
        返回构造器，支持链式调用。

        Returns:
            RuntimeBuilder 实例。
        """
        from src.runtime._builder import RuntimeBuilder

        return RuntimeBuilder()

    @classmethod
    def from_config(cls, path: str) -> "AgentRuntime":
        """
        从配置文件（YAML/TOML）加载并构造。

        Args:
            path: 配置文件路径。

        Returns:
            AgentRuntime 实例。
        """
        config = RuntimeConfig.from_yaml(path)
        return cls.builder().from_config(config).build()

    # ============ 状态管理 ============

    async def run_step(self) -> None:
        """
        执行单个 step。

        适用于外部循环控制场景。
        """
        if self.status != "running":
            return

        # before_step hooks
        self._step_index += 1
        self._timeout["step_start_at"] = int(time.time() * 1000)

        ctx = self._build_context()

        # 取消检查
        if self._cancelled:
            self.status = "ended"
            return

        # 超时检查
        if self._timeout["remaining_ms"] <= 0:
            self.status = "error"
            return

        # before_step interceptor
        intercept_result = await self._hooks.run_interceptors(HookPoint.BEFORE_STEP, {}, ctx)
        if isinstance(intercept_result, BlockAction):
            self.status = "error"
            return

        # before_step transformers
        await self._hooks.run_transformers(HookPoint.BEFORE_STEP, {}, ctx)

        # Router：决定下一步
        next_step = await self._get_next_step(ctx)

        if next_step == "end":
            self.status = "ended"
            return

        await self._execute_step(next_step, ctx)

        # after_step hooks
        await self._hooks.run_transformers(HookPoint.AFTER_STEP, {}, ctx)
        self._budget.step_count += 1

    async def resume(self, approval_id: str) -> None:
        """
        从暂停状态恢复执行。

        Args:
            approval_id: 审批请求 ID。
        """
        if self.status != "paused":
            return

        # 验证 approval_id
        pending = self._pause_state["pending_approvals"]
        self._pause_state["pending_approvals"] = [a for a in pending if a.get("id") != approval_id]

        if not self._pause_state["pending_approvals"]:
            self._pause_state["is_paused"] = False
            self.status = "running"

            # session_resume hooks
            ctx = self._build_context()
            await self._hooks.run_observers(
                HookPoint.SESSION_RESUME,
                {"type": "session_resume", "approval_id": approval_id},
                ctx,
            )

    async def cancel(self) -> None:
        """
        取消当前执行。

        设置取消标志，正在执行的 LLM 调用会在下一次循环迭代
        检查 _cancelled 标志时中断。如需强制中断正在执行的协程，
        请直接取消对应的 asyncio.Task。
        """
        self._cancelled = True
        self.status = "cancelled"

    async def destroy(self) -> None:
        """
        销毁会话。

        触发 session_end hooks（评估、审计、清理）。
        销毁后 Runtime 不可继续使用。
        """
        self.status = "ended"
        ctx = self._build_context()
        await self._hooks.run_observers(
            HookPoint.SESSION_END,
            {"type": "session_end", "status": "destroyed"},
            ctx,
        )
        # 清空内部状态
        self._messages.clear()
        self._step_history.clear()
        self._components.clear()

    def get_session_state(self) -> SessionSnapshot:
        """
        获取当前会话快照（调试/监控用）。

        Returns:
            SessionSnapshot 实例。
        """
        return SessionSnapshot(
            session_id=self.session_id,
            status=self.status,
            step_count=self._budget.step_count,
            message_count=len(self._messages),
            total_tokens=self._budget.token_used,
            last_error=str(self._error_state["last_error"]) if self._error_state[
                "last_error"
            ] else None,
        )
