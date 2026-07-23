"""
Lania Agent Runtime — 以治理为核心的 Agent 运行时框架。

核心设计理念：
- Runtime 管执行闭环 —— 状态机 + Step Loop，最小必要状态
- Hook 管治理逻辑 —— 12 个挂载点 × 5 种原语类型，无状态纯函数
- 状态分层持有 —— Runtime 持有执行状态，外部服务持有持久化状态

使用方式:
    >>> from src.runtime import AgentRuntime
    >>> agent = AgentRuntime(system_prompt="你是助手")
    >>> response = await agent.run("你好")
"""

from src.runtime._builder import RuntimeBuilder
from src.runtime._runtime import AgentRuntime
from src.runtime._steps import StepRunner
from src.runtime._types import (
    AllowAction,
    BlockAction,
    BudgetSnapshot,
    HandlerInfo,
    HookPoint,
    InterceptResult,
    PauseAction,
    PrimitiveType,
    RunResult,
    SessionSnapshot,
    StreamEvent,
    ToolCallInfo,
)
from src.runtime.config import RuntimeConfig
from src.runtime.context import (
    ContextPayload,
    DefaultSerializer,
    MessageSerializer,
    RuntimeContext,
)
from src.runtime.hooks import (
    ApprovalPolicy,
    BudgetThresholdPolicy,
    CompoundPolicy,
    DualModelCritiqueHook,
    HookRegistry,
    HumanApprovalInterceptor,
    Interceptor,
    Observer,
    RegexContentPolicy,
    ReplanHook,
    SelfCritiqueHook,
    ToolNamePolicy,
    Transformer,
)
from src.runtime.llm import (
    AsyncStreamCollector,
    FinishReason,
    LLMExecutionError,
    LLMExecutor,
    LLMExecutorConfig,
    LLMMessage,
    LLMProvider,
    LLMProviderResponse,
    LLMResponse,
    LLMUsage,
    OpenAILLMExecutor,
    OpenAIProvider,
    RetryPolicy,
    StreamableLLMExecutor,
    ToolCall,
)
from src.runtime.loops import (
    AgentNode,
    ConditionNode,
    FixedNode,
    LoopStrategy,
    LoopStrategyFactory,
    Plan,
    PlanExecuteLoop,
    PlanStep,
    ReActLoop,
    StepResult,
    StepStatus,
    WorkflowDefinition,
    WorkflowLoop,
    WorkflowNode,
)
from src.runtime.pipeline import (
    Pipeline,
    PipelineResult,
    Stage,
    StageInfo,
    StopPipelineError,
)
from src.runtime.plugins import PluggableComponent, Plugin
from src.tools import ToolDispatcher, ToolRegistry, ToolSpec

__all__ = [
    # 核心
    "AgentRuntime",
    "RuntimeBuilder",
    "StepRunner",
    # 类型
    "PrimitiveType",
    "HookPoint",
    "AllowAction",
    "BlockAction",
    "PauseAction",
    "InterceptResult",
    "HandlerInfo",
    "BudgetSnapshot",
    "RunResult",
    "StreamEvent",
    "SessionSnapshot",
    "ToolCallInfo",
    # 原语
    "Observer",
    "Transformer",
    "Interceptor",
    # Loop 策略
    "LoopStrategy",
    "LoopStrategyFactory",
    "ReActLoop",
    "PlanExecuteLoop",
    "WorkflowLoop",
    "WorkflowDefinition",
    "WorkflowNode",
    "FixedNode",
    "AgentNode",
    "ConditionNode",
    "StepResult",
    "StepStatus",
    "Plan",
    "PlanStep",
    # 编排 Hook
    "HumanApprovalInterceptor",
    "ApprovalPolicy",
    "ToolNamePolicy",
    "BudgetThresholdPolicy",
    "RegexContentPolicy",
    "CompoundPolicy",
    "SelfCritiqueHook",
    "DualModelCritiqueHook",
    "ReplanHook",
    # 上下文
    "RuntimeContext",
    "ContextPayload",
    "MessageSerializer",
    "DefaultSerializer",
    # 注册中心
    "HookRegistry",
    # 管线
    "Pipeline",
    "PipelineResult",
    "Stage",
    "StageInfo",
    "StopPipelineError",
    # LLMExecutor
    "LLMExecutor",
    "StreamableLLMExecutor",
    "LLMResponse",
    "LLMUsage",
    "ToolCall",
    "LLMMessage",
    "FinishReason",
    "LLMExecutorConfig",
    "LLMProvider",
    "LLMProviderResponse",
    "OpenAIProvider",
    "OpenAILLMExecutor",
    "AsyncStreamCollector",
    "LLMExecutionError",
    "RetryPolicy",
    # 插件
    "PluggableComponent",
    "Plugin",
    # Tool 原语
    "ToolSpec",
    "ToolRegistry",
    "ToolDispatcher",
    # 配置
    "RuntimeConfig",
]
