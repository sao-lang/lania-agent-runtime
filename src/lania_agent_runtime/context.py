"""RuntimeContext - immutable snapshot + type-safe read/write interface for hooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lania_agent_runtime.models import (
    ContextPayload,
    LLMExecutorConfig,
    RuntimeStatus,
)


@dataclass
class Budget:
    """Budget tracking for token/step/cost limits."""

    token_used: int = 0
    token_limit: int = 100000
    step_count: int = 0
    step_limit: int = 100
    cost_in_cents: int = 0


@dataclass
class PauseState:
    """Pause/resume state for human approval."""

    is_paused: bool = False
    pending_approvals: list[dict] = field(default_factory=list)
    resume_token: str | None = None


@dataclass
class ErrorState:
    """Error tracking for retry/degradation decisions."""

    consecutive_errors: int = 0
    max_retries: int = 3
    last_error: str | None = None


class RuntimeContext:
    """Runtime context passed to hooks - immutable snapshot + restricted write API."""

    def __init__(
        self,
        session_id: str = "",
        agent_id: str = "",
    ) -> None:
        # Read-only identity
        self._session_id = session_id
        self._agent_id = agent_id

        # Runtime state
        self._status: RuntimeStatus = RuntimeStatus.IDLE
        self._messages: list[dict] = []
        self._context_payload: ContextPayload = ContextPayload()
        self._plan: dict | None = None
        self._step_index: int = 0
        self._step_history: list[dict] = []
        self._budget: Budget = Budget()
        self._pause_state: PauseState = PauseState()
        self._error_state: ErrorState = ErrorState()
        self._agent_identity: dict | None = None
        self._tools_schema: list[dict] | None = None

        # LLM executor 配置 (R3)
        self._llm_config: LLMExecutorConfig | None = None

        # 预序列化的 LLM 消息 (设计文档 §5.3 Runtime 负责 serialize)
        self._llm_messages: list[dict] | None = None

        # External service references
        self._services: dict[str, Any] = {}

    # ── Read-only properties ──

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def status(self) -> RuntimeStatus:
        return self._status

    @property
    def messages(self) -> list[dict]:
        return self._messages

    @property
    def context_payload(self) -> ContextPayload:
        return self._context_payload

    @property
    def plan(self) -> dict | None:
        return self._plan

    @property
    def step_index(self) -> int:
        return self._step_index

    @property
    def step_history(self) -> list[dict]:
        return self._step_history

    @property
    def budget(self) -> Budget:
        return self._budget

    @property
    def pause_state(self) -> PauseState:
        return self._pause_state

    @property
    def error_state(self) -> ErrorState:
        return self._error_state

    @property
    def agent_identity(self) -> dict | None:
        return self._agent_identity

    @property
    def tools_schema(self) -> list[dict] | None:
        return self._tools_schema

    @property
    def llm_config(self) -> LLMExecutorConfig | None:
        """LLM executor 配置 (R3).

        设计文档: llm-executor-design.md §5.2
        LLMExecutor._merge_params() 优先读取此字段覆盖默认配置.
        """
        return self._llm_config

    @property
    def services(self) -> dict[str, Any]:
        return self._services

    # ── Restricted write API for hooks ──

    def set_status(self, status: RuntimeStatus) -> None:
        """Set runtime status."""
        self._status = status

    def append_message(self, msg: dict) -> None:
        """Append a message to the message buffer."""
        self._messages.append(msg)

    def set_plan(self, plan: dict | None) -> None:
        """Set/replace the execution plan (Planner/Replan only)."""
        self._plan = plan

    def deduct_budget(self, tokens: int = 0, cost: int = 0) -> None:
        """Deduct from budget (after_llm/after_tool only).

        设计文档 §七: step_count 在 after_step 由 increment_step 更新.
        """
        self._budget.token_used += tokens
        self._budget.cost_in_cents += cost

    def set_agent_identity(self, identity: dict | None) -> None:
        """Set agent identity (session_start only)."""
        self._agent_identity = identity

    def set_tools_schema(self, schema: list[dict] | None) -> None:
        """Set the tool schemas for LLM function calling."""
        self._tools_schema = schema

    def set_error_state(self, error: str | None) -> None:
        """Set the last error message."""
        self._error_state.last_error = error
        if error:
            self._error_state.consecutive_errors += 1

    def increment_step(self) -> None:
        """Increment step index and record history.

        设计文档 §七: after_step 中 Runtime 更新 stepIndex 和 budget.stepCount.
        """
        self._step_index += 1
        self._budget.step_count += 1
        self._step_history.append(
            {
                "step_index": self._step_index,
                "message_count": len(self._messages),
                "status": self._status.value,
            }
        )

    def set_services(self, services: dict[str, Any]) -> None:
        """Set external service references."""
        self._services = services

    def set_llm_config(self, config: LLMExecutorConfig | None) -> None:
        """Set LLM executor configuration override (R3).

        设计文档: llm-executor-design.md §5.2
        允许 Hook 在 before_llm 阶段动态修改 LLM 调用参数.
        """
        self._llm_config = config

    @property
    def llm_messages(self) -> list[dict] | None:
        """预序列化的 LLM 消息 (由 Runtime 在 LLM Execute 前设置)."""
        return self._llm_messages

    def serialize_for_llm(self) -> list[dict]:
        """序列化 context_payload + history 为 LLM 最终消息数组.

        设计文档 §5.3: Runtime 在 before_llm Intercept 后调用此方法,
        将结果传递给 LLM Execute, 而非由 Executor 内部自行序列化.
        """
        system_content = self._context_payload.serialize_to_system_message()
        self._llm_messages = [{"role": "system", "content": system_content}]

        for msg in self._messages:
            if msg.get("role") == "system":
                continue
            self._llm_messages.append(dict(msg))

        return self._llm_messages

    def serialize_messages(self) -> list[dict]:
        """序列化 context_payload + history (兼容旧接口).

        如果已通过 serialize_for_llm() 预序列化, 优先返回缓存结果.
        """
        if self._llm_messages is not None:
            return self._llm_messages
        return self.serialize_for_llm()
