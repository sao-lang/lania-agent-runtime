"""
Provider 抽象接口——LLMProvider。

目的：隔离不同 LLM SDK 的差异，使 LLMExecutor 不依赖具体 SDK。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class LLMProviderResponse:
    """Provider 原始响应的统一包装。

    Attributes:
        content: 文本回复内容。
        tool_calls: Provider 原始格式的工具调用列表（可能为 None）。
        usage: Provider 原始格式的用量信息字典。
        finish_reason: 结束原因字符串。
        model: 实际使用的模型名。
    """

    content: str = ""
    """文本回复内容。"""
    tool_calls: list[dict] | None = None
    """Provider 原始格式的工具调用列表。"""
    usage: dict[str, Any] = field(default_factory=dict)
    """Provider 原始格式的用量信息。"""
    finish_reason: str = "stop"
    """结束原因字符串。"""
    model: str = ""
    """实际使用的模型名。"""


class LLMProvider(ABC):
    """LLM Provider 适配器接口。

    所有 Provider 实现应继承此类，实现 chat 方法。
    chat 方法同时支持非流式和流式两种模式：
      - stream=False: 返回 LLMProviderResponse
      - stream=True:  返回 AsyncIterator[dict]，逐 chunk 产出
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> LLMProviderResponse | AsyncIterator[dict]:
        """调用 LLM API。

        Args:
            messages: 符合 LLM API 格式的消息列表。
            model: 模型名称。
            temperature: 采样温度。
            max_tokens: 最大输出 token 数。
            tools: 工具的 JSON Schema 列表（可选）。
            stream: 是否启用流式模式。
            kwargs: 额外的 Provider 参数。

        Returns:
            stream=False 时返回 LLMProviderResponse；
            stream=True 时返回 AsyncIterator[dict]，每项为一个 chunk。

        Raises:
            Exception: 具体 Provider 异常（如 APITimeoutError, RateLimitError 等）。
        """
        ...
