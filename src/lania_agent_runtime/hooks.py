"""Hook registry and primitive types for Agent Runtime."""

from __future__ import annotations

from enum import Enum
from typing import Any, Awaitable, Callable

from lania_agent_runtime.context import RuntimeContext


class PrimitiveType(str, Enum):
    """Five-level primitive types for hook control."""

    OBSERVE = "observe"  # Read-only observation
    TRANSFORM = "transform"  # Can modify data
    INTERCEPT = "intercept"  # Can block/pause
    ROUTER = "router"  # Can change execution flow
    EXECUTE = "execute"  # Replace execution


class InterceptAction(str, Enum):
    """Intercept result actions."""

    ALLOW = "allow"
    BLOCK = "block"
    PAUSE = "pause"


HookPoint = str
# Hook point constants
SESSION_START = "session_start"
SESSION_END = "session_end"
BEFORE_STEP = "before_step"
AFTER_STEP = "after_step"
BEFORE_LLM = "before_llm"
AFTER_LLM = "after_llm"
BEFORE_TOOL = "before_tool"
AFTER_TOOL = "after_tool"
ON_ERROR = "on_error"
ON_STREAM_CHUNK = "on_stream_chunk"

ALL_HOOK_POINTS = [
    SESSION_START,
    SESSION_END,
    BEFORE_STEP,
    AFTER_STEP,
    BEFORE_LLM,
    AFTER_LLM,
    BEFORE_TOOL,
    AFTER_TOOL,
    ON_ERROR,
    ON_STREAM_CHUNK,
]


# ── Hook type aliases ──

Observer = Callable[[dict, RuntimeContext], Awaitable[None]]
Transformer = Callable[[Any, RuntimeContext], Awaitable[Any]]


class InterceptResult:
    """Result of an interceptor hook."""

    def __init__(
        self,
        action: str = "allow",
        reason: str = "",
        modified: Any = None,  # noqa: ANN401
        approval_id: str = "",
    ) -> None:
        self.action = action
        self.reason = reason
        self.modified = modified
        self.approval_id = approval_id


Interceptor = Callable[[Any, RuntimeContext], Awaitable[InterceptResult]]
RouterFn = Callable[[RuntimeContext], Awaitable[str]]
ExecutorFn = Callable[..., Awaitable[Any]]


class HookRegistry:
    """
    Registry for all hook points.

    Supports registering Observer, Transformer, Interceptor at each hook point.
    Router and Execute are set via dedicated setters.
    """

    def __init__(self) -> None:
        self._hooks: dict[HookPoint, list[dict]] = {point: [] for point in ALL_HOOK_POINTS}
        self._router: RouterFn | None = None
        self._llm_executor: ExecutorFn | None = None
        self._tool_executor: ExecutorFn | None = None
        self._loop_executor: ExecutorFn | None = None

    # ── Registration ──

    def register(
        self,
        point: HookPoint,
        hook_type: str,
        handler: Observer | Transformer | Interceptor,
        name: str = "",
    ) -> None:
        """Register a hook at the given point."""
        if point not in self._hooks:
            msg = f"Unknown hook point: {point}"
            raise ValueError(msg)
        self._hooks[point].append(
            {
                "type": hook_type,
                "handler": handler,
                "name": name or f"{point}_{hook_type}_{len(self._hooks[point])}",
            }
        )

    def observe(self, point: HookPoint, handler: Observer, name: str = "") -> None:
        """Register an Observer hook."""
        self.register(point, "observe", handler, name)

    def transform(self, point: HookPoint, handler: Transformer, name: str = "") -> None:
        """Register a Transformer hook."""
        self.register(point, "transform", handler, name)

    def intercept(self, point: HookPoint, handler: Interceptor, name: str = "") -> None:
        """Register an Interceptor hook."""
        self.register(point, "intercept", handler, name)

    def set_router(self, router: RouterFn) -> None:
        """Set the Router function."""
        self._router = router

    def set_llm_executor(self, executor: ExecutorFn) -> None:
        """Set the LLM Execute function."""
        self._llm_executor = executor

    def set_tool_executor(self, executor: ExecutorFn) -> None:
        """Set the Tool Execute function."""
        self._tool_executor = executor

    def set_loop_executor(self, executor: ExecutorFn) -> None:
        """Set the Loop Execute function."""
        self._loop_executor = executor

    # ── Execution ──

    async def run_observers(self, point: HookPoint, event: dict, ctx: RuntimeContext) -> None:
        """Run all Observer hooks at a point."""
        for hook in self._hooks.get(point, []):
            if hook["type"] == "observe":
                await hook["handler"](event, ctx)

    async def run_transformers(self, point: HookPoint, data: Any, ctx: RuntimeContext) -> Any:  # noqa: ANN401
        """Run all Transformer hooks at a point (pipeline)."""
        result = data
        for hook in self._hooks.get(point, []):
            if hook["type"] == "transform":
                result = await hook["handler"](result, ctx)
        return result

    async def run_interceptors(
        self,
        point: HookPoint,
        data: Any,
        ctx: RuntimeContext,  # noqa: ANN401
    ) -> InterceptResult:
        """Run all Interceptor hooks at a point. Returns first block/pause or allow."""
        for hook in self._hooks.get(point, []):
            if hook["type"] == "intercept":
                result = await hook["handler"](data, ctx)
                if result.action != "allow":
                    return result
        return InterceptResult(action="allow")

    async def run_router(self, ctx: RuntimeContext) -> str:
        """Run the Router function."""
        if self._router is None:
            return "end"
        return await self._router(ctx)

    async def run_llm_executor(self, ctx: RuntimeContext) -> Any:  # noqa: ANN401
        """Run the LLM Execute function."""
        if self._llm_executor is None:
            msg = "LLM executor not set"
            raise RuntimeError(msg)
        return await self._llm_executor(ctx)

    async def run_tool_executor(self, tool_call: dict, ctx: RuntimeContext) -> Any:  # noqa: ANN401
        """Run the Tool Execute function."""
        if self._tool_executor is None:
            msg = "Tool executor not set"
            raise RuntimeError(msg)
        return await self._tool_executor(tool_call, ctx)

    async def run_loop_executor(self, ctx: RuntimeContext) -> Any:  # noqa: ANN401
        """Run the Loop Execute function."""
        if self._loop_executor is None:
            msg = "Loop executor not set"
            raise RuntimeError(msg)
        return await self._loop_executor(ctx)

    # ── Inspection ──

    def get_hooks_at(self, point: HookPoint) -> list[dict]:
        """Get all hooks registered at a point."""
        return list(self._hooks.get(point, []))

    def has_router(self) -> bool:
        return self._router is not None

    def has_llm_executor(self) -> bool:
        return self._llm_executor is not None
