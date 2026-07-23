"""
LLMExecutor 抽象接口定义。

定义 Execute 原语的 LLM 特化接口：
  - LLMExecutor: 非流式基类
  - StreamableLLMExecutor: 流式扩展接口
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.runtime.context._context import RuntimeContext
    from src.runtime.llm._executors._stream import AsyncStreamCollector
    from src.runtime.llm._models import LLMResponse


class LLMExecutor(ABC):
    """Execute 原语的 LLM 特化。

    语义：完全接管 "messages → LLM API → LLMResponse" 的往返。
    约束：无副作用，不写 ctx.messages，结果通过 return 传回。

    使用方式：
        executor = OpenAILLMExecutor(config)
        response = await executor.execute(ctx)
    """

    @abstractmethod
    async def execute(self, ctx: RuntimeContext) -> LLMResponse:
        """执行 LLM 调用。

        输入：ctx.messages（已序列化的消息数组，[0] 为 system message）。
        输出：LLMResponse（LLM 回复内容 + tool_calls + 用量统计）。

        Args:
            ctx: RuntimeContext 实例，包含 messages 等执行上下文。

        Returns:
            LLMResponse 实例。
        """
        ...


class StreamableLLMExecutor(LLMExecutor, ABC):
    """支持流式的 LLMExecutor 扩展接口。

    非流式 executor 不需要实现此接口。
    流式 executor 同时兼容非流式的 execute() 调用。
    """

    @abstractmethod
    async def execute_stream(
        self,
        ctx: RuntimeContext,
    ) -> tuple[AsyncStreamCollector, LLMResponse]:
        """流式执行 LLM 调用。

        Runtime 可逐 chunk 触发 on_stream_chunk hook，
        流结束后通过 assemble() 获取完整 LLMResponse。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            - collector: 异步流收集器，Runtime 可逐 chunk 触发 onStreamChunk hook。
            - final_response: 完整组装后的 LLMResponse（流结束才可用）。
        """
        ...
