"""
LLMExecutor 模块——Execute 原语的 LLM 特化。

提供统一的 LLM 调用接口，支持：
  - OpenAI / OpenAI-compatible API（GPT-4o, DeepSeek, Qwen 等）
  - Function calling / tool_calls
  - 流式与非流式执行
  - 指数退避重试

使用方式：
    from src.runtime.llm import OpenAILLMExecutor, LLMExecutorConfig

    config = LLMExecutorConfig(model="gpt-4o", api_key="sk-...")
    executor = OpenAILLMExecutor(config)
    response = await executor.execute(ctx)
"""

from src.runtime.llm._config import LLMExecutorConfig
from src.runtime.llm._errors import LLMExecutionError
from src.runtime.llm._executors import AsyncStreamCollector, OpenAILLMExecutor
from src.runtime.llm._interfaces import LLMExecutor, StreamableLLMExecutor
from src.runtime.llm._models import FinishReason, LLMMessage, LLMResponse, LLMUsage, ToolCall
from src.runtime.llm._providers import LLMProvider, LLMProviderResponse, OpenAIProvider
from src.runtime.llm._retry import RetryPolicy

__all__ = [
    # 接口
    "LLMExecutor",
    "StreamableLLMExecutor",
    # 数据模型
    "LLMResponse",
    "LLMUsage",
    "ToolCall",
    "LLMMessage",
    "FinishReason",
    # 配置
    "LLMExecutorConfig",
    # Provider
    "LLMProvider",
    "LLMProviderResponse",
    "OpenAIProvider",
    # Executor
    "OpenAILLMExecutor",
    "AsyncStreamCollector",
    # 错误
    "LLMExecutionError",
    # 重试
    "RetryPolicy",
]
