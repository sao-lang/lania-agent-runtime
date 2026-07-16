"""AgentRuntime - Main runtime class implementing the step loop and hook system."""

from __future__ import annotations

import time
import uuid
from typing import Any, AsyncIterator

from lania_agent_runtime.context import RuntimeContext
from lania_agent_runtime.executor import LLMExecutor, LLMExecutorConfig
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
from lania_agent_runtime.models import (
    LLMResponse,
    LLMUsage,
    RunResult,
    RuntimeStatus,
    SessionSnapshot,
    StreamEvent,
    ToolCall,
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

        # Run the step loop
        await self._step_loop()

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

        # Run streaming step loop
        async for event in self._step_loop_stream():
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
        """Destroy the session, trigger session_end hooks."""
        session_data = {"session_id": self._session_id}
        session_data = await self._hooks.run_transformers(
            SESSION_END, session_data, self._ctx
        )
        await self._hooks.run_observers(SESSION_END, session_data, self._ctx)
        self._ctx.set_status(RuntimeStatus.ENDED)

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

    async def _step_loop(self) -> None:
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

            # ── Memory recall: populate ContextPayload ──
            last_content = self._ctx.messages[-1].get("content", "") if self._ctx.messages else ""
            recall_payload = await self._memory.recall(
                session_id=self._session_id,
                query=last_content,
            )
            if recall_payload.memories:
                self._ctx.context_payload.memories = recall_payload.memories
            if recall_payload.rag_documents:
                self._ctx.context_payload.rag_documents = recall_payload.rag_documents
            if recall_payload.concepts:
                self._ctx.context_payload.concepts = recall_payload.concepts
            if recall_payload.entity_profile:
                self._ctx.context_payload.entity_profile = recall_payload.entity_profile

            # ── before_llm: intercept → transform ──
            llm_data = {"messages": self._ctx.messages}
            intercept = await self._hooks.run_interceptors(BEFORE_LLM, llm_data, self._ctx)
            if intercept.action == "block":
                self._ctx.set_error_state(intercept.reason)
                break

            llm_data = await self._hooks.run_transformers(BEFORE_LLM, llm_data, self._ctx)

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
                await self._hooks.run_observers(
                    ON_ERROR, {"error": str(e), "step_index": self._ctx.step_index}, self._ctx
                )
                # Error Router: retry / skip / degrade
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
                        return

                    try:
                        result = await self._hooks.run_tool_executor(tool_data, self._ctx)
                    except Exception as e:
                        result = {"error": str(e)}

                    # after_tool: intercept → transform → observe
                    intercept = await self._hooks.run_interceptors(
                        AFTER_TOOL, {"result": result, "tool_call": tool_call}, self._ctx
                    )
                    if intercept.action == "block":
                        self._ctx.set_error_state(intercept.reason)
                        result = {"blocked": intercept.reason}

                    result = await self._hooks.run_transformers(
                        AFTER_TOOL, {"result": result, "tool_call": tool_call}, self._ctx
                    )

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

            # ── Commit to memory ──
            if len(self._ctx.messages) >= 2:
                last_user = None
                last_assistant = None
                for m in reversed(self._ctx.messages):
                    if m.get("role") == "assistant" and last_assistant is None:
                        last_assistant = m.get("content", "")
                    elif m.get("role") == "user" and last_user is None:
                        last_user = m.get("content", "")
                    if last_user and last_assistant:
                        break
                if last_user and last_assistant:
                    await self._memory.commit(self._session_id, None, last_user, last_assistant)

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

    async def _step_loop_stream(self) -> AsyncIterator[StreamEvent]:
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

            # ── Memory recall: populate ContextPayload ──
            last_content = self._ctx.messages[-1].get("content", "") if self._ctx.messages else ""
            recall_payload = await self._memory.recall(
                session_id=self._session_id,
                query=last_content,
            )
            if recall_payload.memories:
                self._ctx.context_payload.memories = recall_payload.memories
            if recall_payload.rag_documents:
                self._ctx.context_payload.rag_documents = recall_payload.rag_documents
            if recall_payload.concepts:
                self._ctx.context_payload.concepts = recall_payload.concepts
            if recall_payload.entity_profile:
                self._ctx.context_payload.entity_profile = recall_payload.entity_profile

            # ── before_llm: intercept → transform ──
            llm_data = {"messages": self._ctx.messages}
            intercept = await self._hooks.run_interceptors(BEFORE_LLM, llm_data, self._ctx)
            if intercept.action == "block":
                yield StreamEvent(type="error", content=intercept.reason)
                return

            llm_data = await self._hooks.run_transformers(BEFORE_LLM, llm_data, self._ctx)

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
                elif hasattr(self._llm_executor, "execute_stream_collected"):
                    # Collected streaming: yields text + assembles full response
                    collector, response = (
                        await self._llm_executor.execute_stream_collected(self._ctx)
                    )
                    full_content = collector.full_content
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
                elif self._llm_executor:
                    # Simple text streaming
                    async for chunk in self._llm_executor.execute_stream(self._ctx):
                        full_content += chunk
                        yield StreamEvent(type="text", content=chunk)
                else:
                    # Mock streaming
                    content = self._ctx.messages[-1].get("content", "")
                    chunks = [f"Echo: {content}"]
                    for chunk in chunks:
                        full_content += chunk
                        yield StreamEvent(type="text", content=chunk)
            except Exception as e:
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

            # ── Commit to memory ──
            if len(self._ctx.messages) >= 2:
                last_user = None
                last_assistant = None
                for m in reversed(self._ctx.messages):
                    if m.get("role") == "assistant" and last_assistant is None:
                        last_assistant = m.get("content", "")
                    elif m.get("role") == "user" and last_user is None:
                        last_user = m.get("content", "")
                    if last_user and last_assistant:
                        break
                if last_user and last_assistant:
                    await self._memory.commit(self._session_id, None, last_user, last_assistant)

            # ── Router: determine next step ──
            if self._hooks.has_router():
                next_step = await self._hooks.run_router(self._ctx)
                if next_step == "end":
                    break
            else:
                break  # Single step default for streaming

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
