"""AgentRuntime - Main runtime class implementing the step loop and hook system."""

from __future__ import annotations

import time
import uuid
from typing import Any, AsyncIterator

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.executor import LLMExecutor
from lania_agent_runtime.models import LLMExecutorConfig
from lania_agent_runtime.hooks import (
    AFTER_LLM,
    AFTER_STEP,
    AFTER_TOOL,
    BEFORE_LLM,
    BEFORE_STEP,
    BEFORE_TOOL,
    ON_ERROR,
    SESSION_END,
    SESSION_START,
    HookRegistry,
)
from lania_agent_runtime.memory.base import MemoryService
from lania_agent_runtime.memory.hooks import MemoryCommitHook, MemoryRecallHook
from lania_agent_runtime.models import (
    BudgetSnapshot,
    ContextPayloadSnapshot,
    ErrorStateSnapshot,
    LLMResponse,
    LLMUsage,
    PauseStateSnapshot,
    PlanStep,
    RunResult,
    RuntimeStatus,
    SessionSnapshot,
    StreamEvent,
    ToolCall,
    WorkingMemorySnapshot,
)


class AgentRuntime:
    """
    Agent Runtime - Main execution engine.

    Implements the step loop with hook points for governance:
      1. User message → before_step → before_llm → LLM Execute
         → after_llm → [tool loop] → after_step → response
    """

    def __init__(
        self,
        session_id: str | None = None,
        agent_id: str | None = None,
        llm_executor: LLMExecutor | None = None,
        hooks: HookRegistry | None = None,
        memory: MemoryService | None = None,
        config: LLMExecutorConfig | None = None,
    ) -> None:
        self._session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self._agent_id = agent_id or "default-agent"
        self._llm_executor = llm_executor
        self._hooks = hooks or HookRegistry()
        self._memory = memory or MemoryService()

        # Runtime context
        self._ctx = RuntimeContext(
            session_id=self._session_id,
            agent_id=self._agent_id,
        )
        self._ctx.set_services({"memory": self._memory})
        if config:
            self._config = config
        else:
            self._config = LLMExecutorConfig()

        self._start_time: float | None = None

        # 自动注册记忆 Hook (如果 MemoryService 有存储后端)
        has_episodic = (
            self._memory.working_store is not None
            or self._memory.episodic_store is not None
        )
        if has_episodic:
            self._hooks.transform(
                BEFORE_STEP,
                MemoryRecallHook(self._memory),
                name="memory_recall",
            )
            self._hooks.transform(
                AFTER_STEP,
                MemoryCommitHook(self._memory),
                name="memory_commit",
            )

    # ── Properties ──

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def status(self) -> RuntimeStatus:
        return self._ctx.status

    @property
    def context(self) -> RuntimeContext:
        return self._ctx

    @property
    def hooks(self) -> HookRegistry:
        return self._hooks

    @property
    def memory(self) -> MemoryService:
        return self._memory

    # ── Core Entry Points ──

    async def run(
        self,
        user_input: str,
        *,
        user_id: str | None = None,
        system_prompt: str | None = None,
    ) -> RunResult:
        """Single-turn/multi-turn entry point: user input → full response."""
        self._start_time = time.time()

        # Session start hooks
        if self._ctx.step_index == 0 and self._ctx.status == RuntimeStatus.IDLE:
            session_data = {"session_id": self._session_id}
            session_data = await self._hooks.run_transformers(
                SESSION_START, session_data, self._ctx
            )
            intercept = await self._hooks.run_interceptors(
                SESSION_START, session_data, self._ctx
            )
            if intercept.action == "block":
                self._ctx.set_error_state(intercept.reason)
                return self._collect_result()
            await self._hooks.run_observers(
                SESSION_START, session_data, self._ctx
            )
            self._ctx.set_status(RuntimeStatus.RUNNING)

        # Set system prompt on first message
        if system_prompt and not any(m.get("role") == "system" for m in self._ctx.messages):
            self._ctx.append_message({"role": "system", "content": system_prompt})

        # Append user message
        self._ctx.append_message({"role": "user", "content": user_input})

        # 将 user_id 注入 services, 使 Hook 可访问
        if user_id:
            self._ctx.set_services({**self._ctx.services, "user_id": user_id})

        # Run the step loop
        await self._step_loop(user_id=user_id)

        # Collect result
        return self._collect_result()

    async def run_stream(
        self,
        user_input: str,
        *,
        user_id: str | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Streaming entry point: yields StreamEvent chunks."""
        self._start_time = time.time()

        # Session start hooks
        if self._ctx.step_index == 0 and self._ctx.status == RuntimeStatus.IDLE:
            session_data = {"session_id": self._session_id}
            session_data = await self._hooks.run_transformers(
                SESSION_START, session_data, self._ctx
            )
            intercept = await self._hooks.run_interceptors(
                SESSION_START, session_data, self._ctx
            )
            if intercept.action == "block":
                yield StreamEvent(type="error", content=intercept.reason)
                return
            await self._hooks.run_observers(
                SESSION_START, session_data, self._ctx
            )
            self._ctx.set_status(RuntimeStatus.RUNNING)

        if system_prompt and not any(m.get("role") == "system" for m in self._ctx.messages):
            self._ctx.append_message({"role": "system", "content": system_prompt})

        # Append user message
        self._ctx.append_message({"role": "user", "content": user_input})

        # 将 user_id 注入 services, 使 Hook 可访问
        if user_id:
            self._ctx.set_services({**self._ctx.services, "user_id": user_id})

        # Run streaming step loop
        async for event in self._step_loop_stream(user_id=user_id):
            yield event

        yield StreamEvent(
            type="done",
            metadata={
                "session_id": self._session_id,
                "content": self._get_last_content(),
            },
        )

    # ── Session Control ──

    async def destroy(self) -> None:
        """Destroy the session, trigger session_end hooks.

        设计文档 §七: session_end 顺序为 Observer → Transform.
        """
        session_data = {"session_id": self._session_id}
        # 1. Observer: Evaluation, Audit, Observability (只读)
        await self._hooks.run_observers(SESSION_END, session_data, self._ctx)
        # 2. Transform: Session cleanup, persistence (可修改)
        session_data = await self._hooks.run_transformers(
            SESSION_END, session_data, self._ctx
        )
        self._ctx.set_status(RuntimeStatus.ENDED)

    async def resume(self, user_id: str | None = None) -> RunResult:
        """Resume a paused session (R2).

        设计文档: agent-runtime-design.md §九-3
        Runtime 需支持 step 级别的暂停/恢复协议.
        恢复时清空 pause_state, 从上次断点继续 step loop.
        """
        if self._ctx.status != RuntimeStatus.PAUSED:
            msg = f"Cannot resume: session is {self._ctx.status.value}, not paused"
            raise RuntimeError(msg)

        # 清空暂停状态
        self._ctx.pause_state.is_paused = False
        self._ctx.pause_state.pending_approvals = []
        resume_token = self._ctx.pause_state.resume_token
        self._ctx.pause_state.resume_token = None

        # 丢弃工作记忆检查点 (暂停时保存的)
        await self._memory.discard_checkpoint(self._session_id)

        # 恢复运行状态
        self._ctx.set_status(RuntimeStatus.RUNNING)

        # 如果有 resume_token, 注入 services
        if resume_token:
            self._ctx.set_services({
                **self._ctx.services,
                "resume_token": resume_token,
            })

        # 继续 step loop (会重试被暂停的 tool call 等)
        await self._step_loop(user_id=user_id)

        return self._collect_result()

    async def resume_stream(
        self,
        user_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Resume a paused session with streaming.

        设计文档: agent-runtime-design.md §九-3
        """
        if self._ctx.status != RuntimeStatus.PAUSED:
            msg = f"Cannot resume: session is {self._ctx.status.value}, not paused"
            raise RuntimeError(msg)

        # 清空暂停状态
        self._ctx.pause_state.is_paused = False
        self._ctx.pause_state.pending_approvals = []
        resume_token = self._ctx.pause_state.resume_token
        self._ctx.pause_state.resume_token = None

        await self._memory.discard_checkpoint(self._session_id)
        self._ctx.set_status(RuntimeStatus.RUNNING)

        if resume_token:
            self._ctx.set_services({
                **self._ctx.services,
                "resume_token": resume_token,
            })

        async for event in self._step_loop_stream(user_id=user_id):
            yield event

        yield StreamEvent(
            type="done",
            metadata={
                "session_id": self._session_id,
                "content": self._get_last_content(),
            },
        )

    def get_session_state(self) -> SessionSnapshot:
        """Get current session snapshot for debugging."""
        duration = 0.0
        if self._start_time:
            duration = time.time() - self._start_time
        return SessionSnapshot(
            session_id=self._session_id,
            status=self._ctx.status,
            step_count=self._ctx.step_index,
            message_count=len(self._ctx.messages),
            total_tokens=self._ctx.budget.token_used,
            duration_seconds=duration,
            last_error=self._ctx.error_state.last_error,
        )

    # ── Internal Step Loop ──

    async def _step_loop(self, user_id: str | None = None) -> None:
        """Internal step loop (non-streaming)."""
        max_iterations = self._ctx.budget.step_limit or 10

        for _ in range(max_iterations):
            # ── before_step: intercept → transform ──
            step_data = {"step_index": self._ctx.step_index}
            intercept = await self._hooks.run_interceptors(BEFORE_STEP, step_data, self._ctx)
            if intercept.action == "block":
                self._ctx.set_error_state(intercept.reason)
                break

            step_data = await self._hooks.run_transformers(BEFORE_STEP, step_data, self._ctx)

            # ── Router: 决定下一步骤 (设计文档 §七) ──
            if self._hooks.has_router():
                next_step_id = await self._hooks.run_router(self._ctx)
                if next_step_id == "end":
                    break
                # 非 "end" 的 step_id 表示继续 LLM 或其他执行路径

            # ── before_llm: transform → intercept (设计文档 §七) ──
            llm_data = {"messages": self._ctx.messages}
            llm_data = await self._hooks.run_transformers(BEFORE_LLM, llm_data, self._ctx)

            intercept = await self._hooks.run_interceptors(BEFORE_LLM, llm_data, self._ctx)
            if intercept.action == "block":
                self._ctx.set_error_state(intercept.reason)
                break

            # ── Runtime: serialize context_payload → messages[0] (设计文档 §5.3) ──
            self._ctx.serialize_for_llm()

            # ── LLM Execute (via hook registry or direct executor) ──
            try:
                if self._hooks.has_llm_executor():
                    response = await self._hooks.run_llm_executor(self._ctx)
                elif self._llm_executor:
                    response = await self._llm_executor.execute(self._ctx)
                else:
                    # Fallback mock response for testing
                    content = self._ctx.messages[-1].get("content", "")
                    response = LLMResponse(
                        content=f"Echo: {content}",
                        usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
                        finish_reason="stop",
                        model="mock",
                    )
            except Exception as e:
                # ── on_error: Intercept → Router (设计文档 §八-#15) ──
                # Intercept 决定 retry / skip / degrade / escalate
                error_data = {"error": str(e), "step_index": self._ctx.step_index}
                intercept = await self._hooks.run_interceptors(
                    ON_ERROR, error_data, self._ctx
                )
                # ── 自动 checkpoint: 错误时保存工作记忆 ──
                await self._save_checkpoint(user_id)
                # Error Router: 决定下一步 stepId
                if intercept.action == "block":
                    self._ctx.set_error_state(intercept.reason or str(e))
                    break
                # 仍运行 observers 记录错误 (日志/审计)
                await self._hooks.run_observers(
                    ON_ERROR, {"error": str(e), "step_index": self._ctx.step_index}, self._ctx
                )
                try:
                    next_step = await self._hooks.run_router(self._ctx)
                    if next_step == "retry":
                        self._ctx.set_error_state(str(e))
                        continue
                    if next_step == "skip":
                        self._ctx.set_error_state(str(e))
                        break
                except Exception:
                    pass
                self._ctx.set_error_state(str(e))
                break

            # ── Store response in messages ──
            msg = {"role": "assistant", "content": response.content}
            if response.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "function": {
                            "name": tc.name,
                            "arguments": tc.raw_arguments,
                        },
                    }
                    for tc in response.tool_calls
                ]
            self._ctx.append_message(msg)

            # Update budget
            self._ctx.deduct_budget(tokens=response.usage.total_tokens)

            # ── after_llm: transform → intercept → observe ──
            response = await self._hooks.run_transformers(AFTER_LLM, response, self._ctx)

            intercept = await self._hooks.run_interceptors(AFTER_LLM, response, self._ctx)
            if intercept.action == "block":
                self._ctx.set_error_state(intercept.reason)
                break

            await self._hooks.run_observers(AFTER_LLM, {"response": response}, self._ctx)

            # ── Tool calls loop ──
            if response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_data = {
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    }

                    # before_tool: observe → transform → intercept
                    await self._hooks.run_observers(BEFORE_TOOL, tool_data, self._ctx)
                    tool_data = await self._hooks.run_transformers(BEFORE_TOOL, tool_data, self._ctx)
                    intercept = await self._hooks.run_interceptors(
                        BEFORE_TOOL, tool_data, self._ctx
                    )
                    if intercept.action == "block":
                        self._ctx.set_error_state(intercept.reason)
                        self._ctx.append_message({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": f"blocked: {intercept.reason}",
                        })
                        continue
                    if intercept.action == "pause":
                        # Human approval: pause runtime, exit step loop
                        self._ctx.pause_state.is_paused = True
                        self._ctx.pause_state.pending_approvals.append({
                            "tool_call_id": tool_call.id,
                            "tool_name": tool_call.name,
                            "approval_id": intercept.approval_id,
                        })
                        self._ctx.set_status(RuntimeStatus.PAUSED)
                        # ── 自动 checkpoint: 暂停时保存工作记忆 ──
                        await self._save_checkpoint(user_id)
                        return

                    try:
                        result = await self._hooks.run_tool_executor(tool_data, self._ctx)
                    except Exception as e:
                        result = {"error": str(e)}

                    # after_tool: transform → intercept → observe (设计文档 §七)
                    result = await self._hooks.run_transformers(
                        AFTER_TOOL, {"result": result, "tool_call": tool_call}, self._ctx
                    )

                    intercept = await self._hooks.run_interceptors(
                        AFTER_TOOL, {"result": result, "tool_call": tool_call}, self._ctx
                    )
                    if intercept.action == "block":
                        self._ctx.set_error_state(intercept.reason)
                        result = {"blocked": intercept.reason}

                    self._ctx.append_message({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result.get("result", result)),
                    })

                    await self._hooks.run_observers(
                        AFTER_TOOL, {"result": result, "tool_call": tool_call}, self._ctx
                    )

            # ── after_step: transform → observe ──
            step_result = {
                "step_index": self._ctx.step_index,
                "response": response,
            }
            step_result = await self._hooks.run_transformers(AFTER_STEP, step_result, self._ctx)
            await self._hooks.run_observers(AFTER_STEP, step_result, self._ctx)

            self._ctx.increment_step()

            # ── Router: determine next step ──
            if self._hooks.has_router():
                next_step = await self._hooks.run_router(self._ctx)
                if next_step == "end":
                    break
                # Otherwise continue loop
            else:
                # Default: based on finish_reason
                if response.finish_reason in ("stop", "length"):
                    break
                if response.finish_reason == "tool_calls":
                    continue

    async def _step_loop_stream(self, user_id: str | None = None) -> AsyncIterator[StreamEvent]:
        """Internal step loop with streaming."""
        max_iterations = self._ctx.budget.step_limit or 10

        for _ in range(max_iterations):
            # ── before_step: intercept → transform ──
            step_data = {"step_index": self._ctx.step_index}
            intercept = await self._hooks.run_interceptors(BEFORE_STEP, step_data, self._ctx)
            if intercept.action == "block":
                yield StreamEvent(type="error", content=intercept.reason)
                return

            step_data = await self._hooks.run_transformers(BEFORE_STEP, step_data, self._ctx)

            # ── Router: 决定下一步骤 (设计文档 §七) ──
            if self._hooks.has_router():
                next_step_id = await self._hooks.run_router(self._ctx)
                if next_step_id == "end":
                    break

            # ── before_llm: transform → intercept (设计文档 §七) ──
            llm_data = {"messages": self._ctx.messages}
            llm_data = await self._hooks.run_transformers(BEFORE_LLM, llm_data, self._ctx)

            intercept = await self._hooks.run_interceptors(BEFORE_LLM, llm_data, self._ctx)
            if intercept.action == "block":
                yield StreamEvent(type="error", content=intercept.reason)
                return

            # ── Runtime: serialize context_payload → messages[0] (设计文档 §5.3) ──
            self._ctx.serialize_for_llm()

            # ── LLM Execute with streaming ──
            full_content = ""
            response: LLMResponse | None = None
            collector = None

            try:
                if self._hooks.has_llm_executor():
                    # Fallback: stream text chunks from hook executor
                    async for chunk in self._hooks.run_llm_executor(self._ctx):
                        full_content += chunk
                        yield StreamEvent(type="text", content=chunk)
                elif self._llm_executor:
                    # Collected streaming: returns (collector, response)
                    collector, response = await self._llm_executor.execute_stream(self._ctx)
                    full_content = collector.full_content
                    # Stream text event
                    if full_content:
                        yield StreamEvent(type="text", content=full_content)
                    # Stream tool call events
                    for tc in collector.tool_calls:
                        yield StreamEvent(
                            type="tool_start",
                            name=tc["function"]["name"],
                            content=tc["function"]["arguments"],
                        )
                        yield StreamEvent(
                            type="tool_end",
                            name=tc["function"]["name"],
                            content=tc["function"]["arguments"],
                        )
                else:
                    # Mock streaming
                    content = self._ctx.messages[-1].get("content", "")
                    chunks = [f"Echo: {content}"]
                    for chunk in chunks:
                        full_content += chunk
                        yield StreamEvent(type="text", content=chunk)
            except Exception as e:
                # ── 自动 checkpoint: 错误时保存工作记忆 ──
                await self._save_checkpoint(user_id)
                yield StreamEvent(type="error", content=str(e))
                return

            # Build the assistant message
            if collector and collector.tool_calls:
                msg: dict[str, Any] = {"role": "assistant", "content": full_content}
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in collector.tool_calls
                ]
            else:
                msg = {"role": "assistant", "content": full_content}
            self._ctx.append_message(msg)

            self._ctx.deduct_budget(tokens=len(full_content) // 4)

            # ── after_llm: transform → intercept → observe ──
            if response is None:
                response = LLMResponse(
                    content=full_content,
                    finish_reason="tool_calls" if (collector and collector.tool_calls) else "stop",
                )
            response = await self._hooks.run_transformers(AFTER_LLM, response, self._ctx)
            intercept = await self._hooks.run_interceptors(AFTER_LLM, response, self._ctx)
            if intercept.action == "block":
                yield StreamEvent(type="error", content=intercept.reason)
                return
            await self._hooks.run_observers(AFTER_LLM, {"response": response}, self._ctx)

            # ── after_step: transform → observe ──
            step_result = {"step_index": self._ctx.step_index, "response": response}
            step_result = await self._hooks.run_transformers(AFTER_STEP, step_result, self._ctx)
            await self._hooks.run_observers(AFTER_STEP, step_result, self._ctx)

            self._ctx.increment_step()

            # ── Router: determine next step ──
            if self._hooks.has_router():
                next_step = await self._hooks.run_router(self._ctx)
                if next_step == "end":
                    break
            else:
                break  # Single step default for streaming

    # ── Checkpoint ──

    async def _save_checkpoint(self, user_id: str | None = None) -> None:
        """保存工作记忆检查点 (供错误恢复/暂停恢复使用)."""
        try:
            # 从 RuntimeContext 提取完整状态 (M5)
            cp = self._ctx.context_payload
            snapshot = WorkingMemorySnapshot(
                session_id=self._session_id,
                step_index=self._ctx.step_index,
                messages=list(self._ctx.messages),
                message_count=len(self._ctx.messages),
                total_tokens=self._ctx.budget.token_used,
                status=self._ctx.status.value,
                context_payload=ContextPayloadSnapshot(
                    system_prompt=cp.system_prompt,
                    memories=[dict(m) for m in cp.memories],
                    rag_documents=[dict(d) for d in cp.rag_documents],
                    injected_context=list(cp.injected_context),
                    history=[dict(h) for h in cp.history],
                    tone_instruction=cp.tone_instruction,
                    concepts=[dict(c) for c in cp.concepts],
                    entity_profile=dict(cp.entity_profile),
                ),
                budget=BudgetSnapshot(
                    token_used=self._ctx.budget.token_used,
                    token_limit=self._ctx.budget.token_limit,
                    step_count=self._ctx.budget.step_count,
                    step_limit=self._ctx.budget.step_limit,
                    cost_in_cents=self._ctx.budget.cost_in_cents,
                ),
                pause_state=PauseStateSnapshot(
                    is_paused=self._ctx.pause_state.is_paused,
                    pending_approvals=list(self._ctx.pause_state.pending_approvals),
                    resume_token=self._ctx.pause_state.resume_token,
                ),
                error_state=ErrorStateSnapshot(
                    consecutive_errors=self._ctx.error_state.consecutive_errors,
                    max_retries=self._ctx.error_state.max_retries,
                    last_error=(
                        {"type": "error", "message": self._ctx.error_state.last_error}
                        if self._ctx.error_state.last_error else None
                    ),
                ),
                plan=PlanStep(
                    id="",
                    description=str(self._ctx.plan) if self._ctx.plan else "",
                ) if self._ctx.plan else None,
                hook_states={},
            )
            await self._memory.checkpoint(snapshot)
        except Exception:
            pass  # checkpoint 失败不应影响主流程

    # ── Result Collection ──

    def _collect_result(self) -> RunResult:
        """Collect the final result from the current context."""
        last_msg = self._ctx.messages[-1] if self._ctx.messages else {}
        content = last_msg.get("content", "") if isinstance(last_msg, dict) else ""
        tool_calls = []
        if isinstance(last_msg, dict) and last_msg.get("tool_calls"):
            for tc in last_msg["tool_calls"]:
                if isinstance(tc, dict):
                    tool_calls.append(
                        ToolCall(
                            id=tc.get("id", ""),
                            name=tc.get("name", tc.get("function", {}).get("name", "")),
                            arguments=tc.get("arguments", {}),
                            raw_arguments=tc.get("function", {}).get("arguments", ""),
                        )
                    )

        return RunResult(
            content=str(content),
            session_id=self._session_id,
            messages=list(self._ctx.messages),
            tool_calls=tool_calls,
            usage=LLMUsage(
                prompt_tokens=self._ctx.budget.token_used,
                completion_tokens=0,
            ),
            finish_reason="stop",
        )

    def _get_last_content(self) -> str:
        """Get the content of the last assistant message."""
        for m in reversed(self._ctx.messages):
            if m.get("role") == "assistant":
                return m.get("content", "")
        return ""
