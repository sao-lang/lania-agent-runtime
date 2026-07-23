"""
共享类型定义模块。

定义 Agent Runtime 全局通用的：
- 枚举：PrimitiveType, HookPoint
- Protocol：Observer, Transformer, Interceptor
- 数据类：AllowAction, BlockAction, PauseAction, HandlerInfo, BudgetSnapshot
- 类型别名：RouterFn, ExecutorFn, InterceptResult, Event
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Awaitable,
    Callable,
    Protocol,
    TypeAlias,
    TypeVar,
    Union,
    runtime_checkable,
)

T = TypeVar("T")
T_contra = TypeVar("T_contra", contravariant=True)
T_co = TypeVar("T_co", covariant=True)


class PrimitiveType(Enum):
    """原语类型——决定 handler 在 hook 管线中的行为。"""

    OBSERVER = "observer"
    """只读观察，不能修改任何数据流。"""
    TRANSFORM = "transform"
    """可修改流经的数据，但不能阻断。"""
    INTERCEPT = "intercept"
    """可阻断/暂停/放行。"""
    ROUTER = "router"
    """决定下一步去哪里。"""
    EXECUTE = "execute"
    """完全接管一段执行逻辑。"""


class HookPoint(Enum):
    """挂载点枚举——对应 Runtime 执行流程中的关键位置。"""

    SESSION_START = "session_start"
    """会话创建时触发。"""
    SESSION_END = "session_end"
    """会话结束时触发。"""
    SESSION_RESUME = "session_resume"
    """从 pause 状态恢复时触发。"""
    BEFORE_STEP = "before_step"
    """每次 step 执行前触发。"""
    AFTER_STEP = "after_step"
    """每次 step 执行后触发。"""
    BEFORE_SERIALIZE = "before_serialize"
    """序列化 ContextPayload 前触发（仅在 dirty 时执行），
    用于最终格式调整和 provider 适配。"""
    BEFORE_LLM = "before_llm"
    """LLM 调用前触发。"""
    AFTER_LLM = "after_llm"
    """LLM 调用后触发。"""
    BEFORE_TOOL = "before_tool"
    """工具调用前触发。"""
    AFTER_TOOL = "after_tool"
    """工具调用后触发。"""
    ON_ERROR = "on_error"
    """任意异常发生时触发。"""
    ON_STREAM_CHUNK = "on_stream_chunk"
    """流式响应每个 chunk 时触发。"""


# ============ 事件类型 ============

Event = dict[str, Any]
"""通用事件字典类型。"""


# ============ 原语 Protocol ============


@runtime_checkable
class Observer(Protocol[T_co]):
    """只读观察：不能修改任何数据。"""

    async def __call__(self, event: Event, ctx: Any) -> None:
        """观察事件。

        Args:
            event: 事件数据。
            ctx: RuntimeContext 实例（只读）。
        """
        ...


@runtime_checkable
class Transformer(Protocol[T]):
    """可变数据：返回新值替换 data 参数。"""

    async def __call__(self, data: T, ctx: Any) -> T:
        """转换数据。

        Args:
            data: 输入数据。
            ctx: RuntimeContext 实例（只读）。

        Returns:
            转换后的数据。
        """
        ...


@runtime_checkable
class Interceptor(Protocol[T]):
    """可阻断：返回 Allow | Block | Pause。"""

    async def __call__(self, data: T, ctx: Any) -> "InterceptResult":
        """拦截判断。

        Args:
            data: 输入数据。
            ctx: RuntimeContext 实例（只读）。

        Returns:
            AllowAction | BlockAction | PauseAction。
        """
        ...


# ============ Intercept 结果类型 ============


@dataclass
class AllowAction:
    """Intercept 放行结果。"""

    modified: Any | None = None
    """可选的修改后数据，替换原数据继续流转。"""


@dataclass
class BlockAction:
    """Intercept 阻断结果。"""

    reason: str = ""
    """阻断原因描述。"""


@dataclass
class PauseAction:
    """Intercept 暂停结果——等待 Human approval。"""

    approval_id: str = ""
    """审批请求唯一标识。"""
    context: dict[str, Any] = field(default_factory=dict)
    """暂停时附带的上下文信息。"""


InterceptResult = Union[AllowAction, BlockAction, PauseAction]
"""Intercept 返回的联合类型。"""


# ============ 类型别名 ============

RouterFn: TypeAlias = Callable[[Any], Awaitable[str]]
"""
Router 函数签名。
接收 RuntimeContext，返回下一步的 step_id。
"""

T_exec = TypeVar("T_exec")

ExecutorFn: TypeAlias = Callable[[Any], Awaitable[T_exec]]
"""
Executor 函数签名。
接收 RuntimeContext，返回执行结果。
"""

# LLMExecutorFn 支持新旧两种接口
# 新接口：LLMExecutor 对象（有 .execute() 方法）
# 旧接口：ExecutorFn 函数
# 运行时通过 duck typing 检测 L"LLMExecutorFn" 类型别名，仅用于类型标注


# ============ 辅助数据类 ============


@dataclass
class BudgetSnapshot:
    """预算快照——RuntimeContext 中的只读预算信息。"""

    token_used: int = 0
    """已消耗的 token 数量。"""
    token_limit: int = 0
    """token 上限。"""
    step_count: int = 0
    """已执行的 step 数量。"""
    step_limit: int = 0
    """step 上限。"""
    cost_in_cents: int = 0
    """已消耗的成本（美分）。"""


@dataclass
class HandlerInfo:
    """已注册 handler 的元信息。"""

    handler_id: str
    """handler 唯一标识。"""
    point: HookPoint
    """挂载点。"""
    primitive: PrimitiveType
    """原语类型。"""
    handler: Callable
    """handler 可调用对象。"""
    priority: int = 0
    """优先级（值越小越先执行）。"""
    name: str = ""
    """可读名称，用于调试/热加载。"""


# ============ 外部 API 返回类型 ============


@dataclass
class ToolCallInfo:
    """工具调用信息——RunResult 中的工具调用摘要。"""

    name: str = ""
    """工具名称。"""
    arguments: dict[str, Any] = field(default_factory=dict)
    """参数字典。"""
    result: str = ""
    """工具执行结果摘要。"""


@dataclass
class RunResult:
    """run() 的返回结果——包含助理回复和完整会话上下文。

    Attributes:
        content: 助理文本回复。
        session_id: 会话 ID。
        messages: 完整对话历史。
        tool_calls: 本轮调用的工具列表。
        token_used: 本轮累计 token 消耗。
        finish_reason: 结束原因。
        status: 会话结束状态。
    """

    content: str = ""
    """助理文本回复。"""
    session_id: str = ""
    """会话 ID。"""
    messages: list[dict] = field(default_factory=list)
    """完整对话历史。"""
    tool_calls: list[ToolCallInfo] = field(default_factory=list)
    """本轮调用的工具列表。"""
    token_used: int = 0
    """本轮累计 token 消耗。"""
    finish_reason: str = ""
    """结束原因（"stop" | "tool_calls" | "length" | "error"）。"""
    status: str = ""
    """会话结束状态。"""


@dataclass
class StreamEvent:
    """流式事件——run_stream() 产出的逐个事件。

    Attributes:
        type: 事件类型（"text" | "tool_start" | "tool_end" | "error" | "done"）。
        content: 文本片段（type="text" 时）。
        name: 工具名（type="tool_start" | "tool_end" 时）。
        error: 错误信息（type="error" 时）。
        metadata: 附加信息（type="done" 时包含 RunResult 等）。
    """

    type: str = ""
    """事件类型。"""
    content: str | None = None
    """文本片段。"""
    name: str | None = None
    """工具名。"""
    error: str | None = None
    """错误信息。"""
    metadata: dict[str, Any] | None = None
    """附加信息。"""


@dataclass
class SessionSnapshot:
    """会话快照——调试/监控用。

    Attributes:
        session_id: 会话 ID。
        status: Runtime 状态。
        step_count: 已执行 step 数。
        message_count: 消息数。
        total_tokens: 总 token 消耗。
        last_error: 最后错误信息。
    """

    session_id: str = ""
    """会话 ID。"""
    status: str = ""
    """Runtime 状态。"""
    step_count: int = 0
    """已执行 step 数。"""
    message_count: int = 0
    """消息数。"""
    total_tokens: int = 0
    """总 token 消耗。"""
    last_error: str | None = None
    """最后错误信息。"""
